"""Lightweight FastAPI middleware for desktop token authentication.

When the env var DAX_DESKTOP_TOKEN is set (by __main__.py when --auth-token
is passed), every request must include a matching X-Desktop-Token header.

Exempt paths (no token required):
  - /runtime/ui-react   (HTML page — webview navigation can't set custom headers)
  - /assets/*, /static/*  (JS/CSS bundles loaded by the HTML page)

The HTML response injects the random token into the desktop webview. Every API
route, including /runtime/meta and project browsing, therefore requires the
token whenever the packaged desktop launcher supplies one.
"""

import hmac
import os
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("dax_ui.desktop_auth")

# Paths that are exempt from token enforcement (exact match)
_EXEMPT_PATHS = frozenset({
    "/runtime/ui-react",
    "/app-icon.png",
    "/app-icon-32.png",
})

# Path prefixes that are exempt from token enforcement
_EXEMPT_PREFIXES = (
    "/assets/",
    "/static/",
)


class DesktopTokenMiddleware(BaseHTTPMiddleware):
    """Reject requests without a valid X-Desktop-Token header.

    Only active when DAX_DESKTOP_TOKEN env var is set (desktop mode).
    In dev mode (no env var), all requests pass through.
    """

    async def dispatch(self, request: Request, call_next):
        expected_token = os.environ.get("DAX_DESKTOP_TOKEN", "")
        if not expected_token:
            # Dev mode — no enforcement
            return await call_next(request)

        # Check exempt paths (exact match and prefix match)
        path = request.url.path.rstrip("/")
        if path in _EXEMPT_PATHS:
            return await call_next(request)
        for prefix in _EXEMPT_PREFIXES:
            if request.url.path.startswith(prefix):
                return await call_next(request)

        # Enforce token (timing-safe comparison)
        provided = request.headers.get("X-Desktop-Token", "")
        if not hmac.compare_digest(provided, expected_token):
            logger.warning(
                "Desktop token mismatch on %s (got %d chars, expected %d chars)",
                path,
                len(provided),
                len(expected_token),
            )
            return JSONResponse(
                {"ok": False, "error": "Missing or invalid desktop token"},
                status_code=401,
            )

        return await call_next(request)
