"""LDAP/Active Directory authentication provider for Cleargate.

Handles authentication via LDAP (local fallback when unreachable), group-based
role derivation, and stable user identity via DN-derived user_id. Uses ldap3
library (synchronously wrapped in asyncio.to_thread for async compatibility).

Thread safety: ldap3 Server/Connection objects are created fresh per request
(not pooled) to avoid thread-safety concerns.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from typing import Optional

import structlog
from ldap3 import Server, Connection, ALL, ALL_ATTRIBUTES, Tls
from ldap3.core.exceptions import LDAPException, LDAPBindError, LDAPSocketOpenError

logger = structlog.get_logger(__name__)


class LDAPUnreachable(Exception):
    """Raised when LDAP directory is not accessible (network error, timeout, etc.)"""
    pass


@dataclass(frozen=True)
class LDAPUserResult:
    """Result of successful LDAP authentication."""

    user_id: str  # DN-derived stable identifier (hash of DN)
    username: str  # sAMAccountName
    email: str | None
    display_name: str  # cn
    role: str  # 'admin' or 'lawyer'


class LDAPAuthProvider:
    """LDAP authentication via ldap3, with group-based role mapping."""

    def __init__(
        self,
        url: str,
        bind_dn: str,
        bind_password: str,
        base_dn: str,
        admin_group_dn: str | None = None,
        user_group_dn: str | None = None,
        timeout_seconds: int = 5,
    ) -> None:
        """Initialize LDAP provider.

        Args:
            url: LDAP URL, e.g. 'ldaps://ad.example.com:636' or 'ldap://ad.example.com:389'
            bind_dn: Service account DN for directory queries
            bind_password: Service account password
            base_dn: Base DN for user searches
            admin_group_dn: Group DN for admin role (optional)
            user_group_dn: Group DN for lawyer role (optional)
            timeout_seconds: Connection timeout
        """
        self._url = url
        self._bind_dn = bind_dn
        self._bind_password = bind_password
        self._base_dn = base_dn
        self._admin_group_dn = admin_group_dn
        self._user_group_dn = user_group_dn
        self._timeout_seconds = timeout_seconds

        # Warn if not using TLS
        if url.startswith("ldap://"):
            logger.warning(
                "ldap_auth.insecure_protocol",
                msg="Using plain LDAP (not LDAPS); recommend switching to ldaps://",
            )

    async def authenticate(
        self, username: str, password: str
    ) -> LDAPUserResult | None:
        """Authenticate user via LDAP.

        Flow:
          1. Bind as service account
          2. Search for user by sAMAccountName
          3. Attempt rebind as the user (verify password)
          4. Resolve group memberships to determine role
          5. Return LDAPUserResult or None on failure

        Raises LDAPUnreachable if directory is unreachable.
        Returns None if user not found or password invalid.
        """
        try:
            return await asyncio.to_thread(
                self._authenticate_sync, username, password
            )
        except LDAPUnreachable:
            raise
        except Exception as e:
            logger.warning(
                "ldap_auth.unexpected_error",
                exc_info=True,
                username_hash=hashlib.sha256(username.encode()).hexdigest()[:8],
            )
            raise LDAPUnreachable(f"LDAP authentication failed: {e}") from e

    def _authenticate_sync(self, username: str, password: str) -> LDAPUserResult | None:
        """Synchronous LDAP authentication logic."""

        # Step 1: Connect and bind as service account
        try:
            server = self._make_server()
            service_conn = Connection(
                server,
                user=self._bind_dn,
                password=self._bind_password,
                raise_exceptions=True,
                read_only=True,
            )
            service_conn.bind()
        except (LDAPSocketOpenError, LDAPBindError) as e:
            logger.warning(
                "ldap_auth.service_account_bind_failed",
                url=self._url,
                bind_dn_hash=hashlib.sha256(self._bind_dn.encode()).hexdigest()[:8],
            )
            raise LDAPUnreachable(f"Could not bind as service account: {e}") from e
        except LDAPException as e:
            logger.warning("ldap_auth.ldap_exception_on_bind", msg=str(e))
            raise LDAPUnreachable(f"LDAP error during service bind: {e}") from e

        try:
            # Step 2: Search for user by sAMAccountName
            search_filter = f"(sAMAccountName={self._escape_ldap(username)})"
            service_conn.search(
                search_base=self._base_dn,
                search_filter=search_filter,
                attributes=ALL_ATTRIBUTES,
            )

            entries = service_conn.entries
            if not entries:
                logger.info(
                    "ldap_auth.user_not_found",
                    username_hash=hashlib.sha256(username.encode()).hexdigest()[:8],
                )
                return None

            user_entry = entries[0]
            user_dn = user_entry.entry_dn

            # Step 3: Verify password by attempting user rebind
            try:
                user_conn = Connection(
                    server,
                    user=user_dn,
                    password=password,
                    raise_exceptions=True,
                    read_only=True,
                )
                user_conn.bind()
                user_conn.unbind()
            except LDAPBindError:
                logger.info(
                    "ldap_auth.password_invalid",
                    username_hash=hashlib.sha256(username.encode()).hexdigest()[:8],
                )
                return None

            # Step 4: Determine role from group membership
            role = self._determine_role(service_conn, user_dn)

            # Step 5: Extract email and display name
            email = self._get_attribute_string(user_entry, "mail")
            display_name = self._get_attribute_string(user_entry, "cn") or username

            # Derive stable user_id from DN
            user_id = hashlib.sha256(user_dn.lower().encode()).hexdigest()[:16]

            logger.info(
                "ldap_auth.success",
                username_hash=hashlib.sha256(username.encode()).hexdigest()[:8],
                user_dn_hash=hashlib.sha256(user_dn.encode()).hexdigest()[:8],
                role=role,
            )

            return LDAPUserResult(
                user_id=user_id,
                username=username,
                email=email,
                display_name=display_name,
                role=role,
            )

        finally:
            try:
                service_conn.unbind()
            except Exception:
                pass  # Suppress errors on cleanup

    def _determine_role(self, conn: Connection, user_dn: str) -> str:
        """Check group membership to determine role.

        Returns 'admin' if user is in admin_group_dn, 'lawyer' if in user_group_dn,
        otherwise 'lawyer' (default).
        """
        if self._admin_group_dn:
            if self._is_member_of_group(conn, user_dn, self._admin_group_dn):
                return "admin"

        if self._user_group_dn:
            if self._is_member_of_group(conn, user_dn, self._user_group_dn):
                return "lawyer"

        # Default to lawyer if no group membership check enabled
        return "lawyer"

    def _is_member_of_group(
        self, conn: Connection, user_dn: str, group_dn: str
    ) -> bool:
        """Check if user_dn is a member of group_dn (direct or nested).

        Uses LDAP_MATCHING_RULE_IN_CHAIN OID for recursive group resolution.
        """
        try:
            # Search for the user within the group using recursive lookup
            search_filter = f"(member:1.2.840.113556.1.4.1941:={self._escape_ldap(user_dn)})"
            conn.search(
                search_base=group_dn,
                search_filter=search_filter,
                attributes=["cn"],
            )
            return len(conn.entries) > 0
        except Exception as e:
            logger.warning(
                "ldap_auth.group_check_failed",
                user_dn_hash=hashlib.sha256(user_dn.encode()).hexdigest()[:8],
                group_dn_hash=hashlib.sha256(group_dn.encode()).hexdigest()[:8],
                msg=str(e),
            )
            return False

    async def is_reachable(self) -> bool:
        """Quick connectivity check for health endpoint.

        Returns True if we can reach the LDAP server and bind as service account.
        """
        try:
            await asyncio.to_thread(self._check_reachable_sync)
            return True
        except Exception:
            return False

    def _check_reachable_sync(self) -> None:
        """Synchronous reachability check."""
        server = self._make_server()
        conn = Connection(
            server,
            user=self._bind_dn,
            password=self._bind_password,
            raise_exceptions=True,
        )
        try:
            conn.bind()
        finally:
            try:
                conn.unbind()
            except Exception:
                pass

    def _make_server(self) -> Server:
        """Create ldap3.Server object with appropriate TLS settings."""
        use_ssl = self._url.startswith("ldaps://")
        tls_config = Tls(validate=True, ca_certs_file=None) if use_ssl else None
        return Server(self._url, get_info=ALL, tls=tls_config, connect_timeout=self._timeout_seconds)

    @staticmethod
    def _escape_ldap(value: str) -> str:
        """Escape special characters in LDAP filter values per RFC 4515."""
        special_chars = {
            "*": r"\2a",
            "(": r"\28",
            ")": r"\29",
            "\x00": r"\00",
            "/": r"\2f",
        }
        for char, escaped in special_chars.items():
            value = value.replace(char, escaped)
        return value

    @staticmethod
    def _get_attribute_string(entry, attr_name: str) -> str | None:
        """Safely extract a single string attribute from an LDAP entry."""
        try:
            attr = getattr(entry, attr_name, None)
            if attr is not None:
                if isinstance(attr, (list, tuple)) and len(attr) > 0:
                    return str(attr[0])
                elif isinstance(attr, str):
                    return attr
        except Exception:
            pass
        return None


def get_ldap_provider() -> LDAPAuthProvider | None:
    """Factory function: returns LDAPAuthProvider if LDAP is configured, else None.

    Used in main.py lifespan to conditionally enable LDAP auth.
    """
    from app.config import settings

    if not settings.ldap_url:
        return None

    return LDAPAuthProvider(
        url=settings.ldap_url,
        bind_dn=settings.ldap_bind_dn,
        bind_password=settings.ldap_bind_password,
        base_dn=settings.ldap_base_dn,
        admin_group_dn=settings.ldap_admin_group_dn or None,
        user_group_dn=settings.ldap_user_group_dn or None,
        timeout_seconds=settings.ldap_timeout_seconds,
    )
