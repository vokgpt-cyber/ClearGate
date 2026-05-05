"""HTTP telemetry middleware for analytics and audit logging.

Records metadata (not body!) for every request: method, path, status, latency,
user, IP. Maps routes to semantic event types (auth.login, anonymize.done, etc.)
and logs them to the audit_log service (assumed to exist on app.state).

Privacy: NEVER log request/response bodies, only metadata.
"""

from __future__ import annotations

import re
import time
from typing import Any, Awaitable, Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = structlog.get_logger(__name__)


class TelemetryMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that records telemetry events for every request."""

    # Paths that don't merit recording (too noisy or self-referential).
    SKIP_PATHS = {"/health", "/api/admin/events", "/metrics"}

    # Path prefixes to skip (static assets, Next.js internals).
    SKIP_PREFIXES = ("/_next/", "/static/", "/.well-known/")

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        # Route regex patterns -> event type mappings.
        # These are checked in order; first match wins.
        self._route_patterns: list[tuple[re.Pattern[str], str, str]] = [
            # (regex, method_filter, event_type)
            (re.compile(r"^/api/auth/login$"), "POST", "auth.login"),
            (re.compile(r"^/api/auth/logout$"), "POST", "auth.logout"),
            (re.compile(r"^/api/auth/me$"), "GET", "auth.me"),
            (re.compile(r"^/api/sessions$"), "POST", "session.created"),
            (re.compile(r"^/api/sessions/\d+$"), "GET", "session.info"),
            (re.compile(r"^/api/documents/upload$"), "POST", "document.uploaded"),
            (re.compile(r"^/api/sessions/.+/anonymize$"), "POST", "anonymize.done"),
            (re.compile(r"^/api/sessions/.+/deep-scan$"), "POST", "deep_scan.done"),
            (re.compile(r"^/api/sessions/.+/llm$"), "POST", "llm.send"),
            (re.compile(r"^/api/feedback$"), "POST", "feedback.submitted"),
            (re.compile(r"^/api/feedback/mine$"), "GET", "feedback.list"),
            (re.compile(r"^/api/client-errors$"), "POST", "client_error.reported"),
            (re.compile(r"^/api/admin/users$"), "GET", "admin.users.list"),
            (re.compile(r"^/api/admin/users$"), "POST", "admin.users.created"),
            (re.compile(r"^/api/admin/users/.+$"), "PATCH", "admin.users.modified"),
            (re.compile(r"^/api/admin/feedback$"), "GET", "admin.feedback.list"),
            (re.compile(r"^/api/admin/feedback/.+$"), "PATCH", "admin.feedback.replied"),
            (re.compile(r"^/api/admin/errors$"), "GET", "admin.errors.list"),
            (re.compile(r"^/api/admin/analytics/.+$"), "GET", "admin.analytics.query"),
        ]

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Intercept request, measure latency, log event, return response."""
        path = request.url.path
        method = request.method

        # Skip noisy paths and static assets.
        if path in self.SKIP_PATHS or any(
            path.startswith(prefix) for prefix in self.SKIP_PREFIXES
        ):
            return await call_next(request)

        # Capture start time and client info.
        start_time = time.time()
        client_host = request.client.host if request.client else "unknown"

        # Measure the handler.
        response: Response = await call_next(request)
        latency_ms = (time.time() - start_time) * 1000

        # Determine event type by matching route patterns.
        event_type = self._match_route(path, method)
        if event_type is None:
            event_type = "http.request"  # generic fallback

        # Extract user_id from cookie or query if available.
        user_id = self._extract_user_id(request)

        # Build event payload (no request/response body!).
        event_payload = {
            "method": method,
            "path": path,
            "status_code": response.status_code,
            "latency_ms": round(latency_ms, 2),
            "user_id": user_id,
            "client_ip": client_host,
            "user_agent": request.headers.get("user-agent", ""),
            "response_size_bytes": int(response.headers.get("content-length", "0"))
            or None,
        }

        # Log the event.
        if response.status_code >= 500:
            logger.error(
                event_type,
                **event_payload,
                msg_issue="server_error",
            )
        elif response.status_code >= 400:
            logger.warning(event_type, **event_payload)
        else:
            logger.info(event_type, **event_payload)

        # Record to audit_log if present on app state.
        # (Phase 3 parallel work initializes app.state.audit_log)
        if hasattr(request.app.state, "audit_log"):
            try:
                await request.app.state.audit_log.record(
                    event_type=event_type,
                    user_id=user_id,
                    ip_address=client_host,
                    user_agent=request.headers.get("user-agent", ""),
                    payload=event_payload,
                )
            except Exception as e:
                logger.exception("telemetry.audit_log_failed", exc=e)
                # Non-fatal; don't break the response.

        return response

    def _match_route(self, path: str, method: str) -> str | None:
        """Try to match path+method against known route patterns.

        Returns event_type or None if no match.
        """
        for regex, method_filter, event_type in self._route_patterns:
            if method == method_filter and regex.match(path):
                return event_type
        return None

    @staticmethod
    def _extract_user_id(request: Request) -> str | None:
        """Extract user_id from cg_session cookie if present.

        This is a best-effort extraction; it does not validate the token
        (that's the job of auth middleware on actual endpoints).
        """
        # Try cookie first.
        cookie_val = request.cookies.get("cg_session")
        if cookie_val:
            # Could decode the JWT here if needed, but for now just
            # log that a session existed. The auth service will validate it
            # properly on the real endpoint.
            return "authenticated"  # or extract sub from JWT if decoding

        # Try query param (less secure, but sometimes useful for WebSocket).
        user_id = request.query_params.get("user_id")
        return user_id if user_id else None
