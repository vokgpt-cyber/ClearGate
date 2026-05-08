"""Authentication endpoints: login, logout, current-user lookup.

There is intentionally **no** self-registration endpoint -- all user
accounts are provisioned by the ``cleargate-admin`` CLI (Sprint B.5).
A pilot deployment has a fixed set of lawyers; opening registration
would be a footgun for an on-premise tool.
"""

from __future__ import annotations

from collections import defaultdict, deque
from time import monotonic
from typing import Annotated

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.config import settings
from app.services.auth import AuthService, get_auth_service
from app.services.auth_ldap import LDAPAuthProvider, LDAPUnreachable
from app.services.user_store import UserRecord, UserStore

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_LOGIN_RATE_WINDOW_SECONDS = 300
_LOGIN_RATE_MAX_FAILURES = 8
_login_failures: dict[str, deque[float]] = defaultdict(deque)


# ----------------------------------------------------------------------
# DI plumbing
# ----------------------------------------------------------------------

# UserStore is attached to the FastAPI app state at startup, rather than
# being a module-level singleton, because the DB path comes from settings
# and we want tests to be able to swap it out.


def get_user_store_from_request() -> UserStore:
    """Dependency stub -- overridden in main.py via app.dependency_overrides
    once the concrete UserStore is instantiated during lifespan startup."""
    raise RuntimeError(
        "UserStore dependency not wired up; check main.py lifespan initialisation"
    )


def get_ldap_provider_from_request() -> LDAPAuthProvider | None:
    """Dependency stub -- overridden in main.py via app.dependency_overrides.

    Returns None if LDAP is not configured, otherwise returns the configured
    LDAPAuthProvider instance. main.py sets this during startup if settings.ldap_url is set.
    """
    return None


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class UserPublic(BaseModel):
    """User view safe to return over HTTP -- no password hash, no internals."""

    user_id: str
    username: str
    is_active: bool
    role: str = "lawyer"

    @classmethod
    def from_record(cls, rec: UserRecord) -> "UserPublic":
        return cls(
            user_id=rec.user_id,
            username=rec.username,
            is_active=rec.is_active,
            role=getattr(rec, "role", "lawyer") or "lawyer",
        )


class LoginResponse(BaseModel):
    user: UserPublic


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _set_session_cookie(response: Response, token: str, max_age_seconds: int) -> None:
    """Install the session cookie on a response, with deployment flags."""
    response.set_cookie(
        key=settings.cleargate_auth_cookie_name,
        value=token,
        max_age=max_age_seconds,
        httponly=True,
        secure=settings.cleargate_auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.cleargate_auth_cookie_name,
        path="/",
        secure=settings.cleargate_auth_cookie_secure,
        samesite="lax",
    )


def _resolve_user_from_cookie(
    cookie_value: str | None,
    auth: AuthService,
    users: UserStore,
) -> UserRecord | None:
    """Shared cookie -> active-user resolution used by /me and middleware."""
    if not cookie_value:
        return None
    token = auth.verify_session_token(cookie_value)
    if token is None:
        return None
    rec = users.get_by_id(token.user_id)
    if rec is None or not rec.is_active:
        return None
    return rec


def _login_rate_key(http_request: Request, username: str) -> str:
    client_host = http_request.client.host if http_request.client else "unknown"
    return f"{client_host}:{username.strip().casefold()}"


def _prune_login_failures(key: str, now: float) -> deque[float]:
    attempts = _login_failures[key]
    cutoff = now - _LOGIN_RATE_WINDOW_SECONDS
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    return attempts


def _enforce_login_rate_limit(key: str) -> None:
    attempts = _prune_login_failures(key, monotonic())
    if len(attempts) >= _LOGIN_RATE_MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
        )


def _record_login_failure(key: str) -> None:
    attempts = _prune_login_failures(key, monotonic())
    attempts.append(monotonic())


def _clear_login_failures(key: str) -> None:
    _login_failures.pop(key, None)


# ----------------------------------------------------------------------
# Reusable dependency: current authenticated user
# ----------------------------------------------------------------------


async def get_current_user(
    users: Annotated[UserStore, Depends(get_user_store_from_request)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
    cg_session: Annotated[str | None, Cookie(alias="cg_session")] = None,
) -> UserRecord:
    """FastAPI dependency: resolve the active user or raise 401.

    Every protected router (sessions, anonymize, documents) consumes this
    via ``Depends(get_current_user)``.  We re-fetch the ``UserRecord`` on
    every request -- this is what lets an admin disable a user mid-session
    and have the change take effect immediately rather than after the
    cookie TTL expires.

    Why the cookie alias is hardcoded instead of read from
    ``settings.cleargate_auth_cookie_name``: FastAPI needs the alias at
    decoration time, and the setting is effectively a constant for any
    given deployment.  Changing it requires a restart anyway.
    """
    rec = _resolve_user_from_cookie(cg_session, auth, users)
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            # WWW-Authenticate is advisory for browsers; we use cookies
            # not Basic auth, but the header makes curl/log diagnostics
            # a touch friendlier when chasing 401s.
            headers={"WWW-Authenticate": "Cookie"},
        )
    return rec


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    http_request: Request,
    response: Response,
    users: Annotated[UserStore, Depends(get_user_store_from_request)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
    ldap: Annotated[LDAPAuthProvider | None, Depends(get_ldap_provider_from_request)],
) -> LoginResponse:
    """Verify credentials (LDAP-first, then local), issue a signed session cookie."""
    login_key = _login_rate_key(http_request, request.username)
    _enforce_login_rate_limit(login_key)

    # Step 1: try LDAP first if configured.
    user_record = None
    if ldap is not None:
        try:
            ldap_result = await ldap.authenticate(request.username, request.password)
        except LDAPUnreachable:
            logger.warning("auth.login.ldap_unreachable", exc_info=True)
            ldap_result = None
        if ldap_result is not None:
            # LDAP succeeded; sync into local user store.
            user_record = users.get_or_create_from_ldap(
                ldap_dn=ldap_result.user_id,
                username=ldap_result.username,
                email=ldap_result.email,
                display_name=ldap_result.display_name,
                role=ldap_result.role,
            )

    # Step 2: fall back to local password if LDAP didn't authenticate.
    if user_record is None:
        local = users.get_by_username(request.username)
        if local is None or not local.is_active or local.password_hash is None:
            # Dummy verify to equalise timing on unknown-user vs bad-password.
            auth.verify_password(
                request.password,
                "$argon2id$v=19$m=65536,t=2,p=1$"
                "ZGVhZGJlZWZkZWFkYmVlZg$"  # fixed 16-byte dummy salt
                "Ym9ndXNib2d1c2JvZ3Vzbm90YXJlYWxoYXNoMTIzNDU2Nzg",
            )
            logger.info("auth.login.failed", username=request.username, reason="no_such_user_or_inactive")
            _record_login_failure(login_key)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )

        if not auth.verify_password(request.password, local.password_hash):
            logger.info("auth.login.failed", user_id=local.user_id, reason="bad_password")
            _record_login_failure(login_key)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )

        # Transparently upgrade the hash if our Argon2 parameters have changed.
        if auth.needs_rehash(local.password_hash):
            try:
                new_hash = auth.hash_password(request.password)
                users.update_password(local.user_id, new_hash)
            except Exception:
                # Non-fatal -- a failed rehash shouldn't block login.
                logger.warning("auth.login.rehash_failed", user_id=local.user_id, exc_info=True)

        user_record = local

    # Record login + issue cookie.
    users.record_login(user_record.user_id)
    token = auth.issue_session_token(user_record.user_id)
    _set_session_cookie(response, token, auth.max_age_seconds)
    _clear_login_failures(login_key)
    logger.info("auth.login.ok", user_id=user_record.user_id, username=user_record.username)
    return LoginResponse(user=UserPublic.from_record(user_record))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    """Clear the session cookie.  No-op if already logged out."""
    _clear_session_cookie(response)


@router.get("/me", response_model=UserPublic)
async def me(
    current_user: Annotated[UserRecord, Depends(get_current_user)],
) -> UserPublic:
    """Return the currently logged-in user, or 401 if the cookie is absent/invalid.

    Frontend calls this on app boot to decide whether to show the login
    page or the main UI.
    """
    return UserPublic.from_record(current_user)
