"""Security middleware — rate limiting, body size limits, and response headers.

Fixes:
- SEC-03: Per-IP rate limiting with token bucket algorithm
- SEC-07: Security response headers (X-Frame-Options, CSP, etc.)
- SEC-12: Request body size limit
"""
from __future__ import annotations

import logging
import os
import time
from threading import Lock
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SEC-03: Rate Limiting (token-bucket per IP)
# ---------------------------------------------------------------------------

# Defaults — can be overridden via env vars
_RATE_LIMIT_RPM = int(os.environ.get("DAX_RATE_LIMIT_RPM", "300"))  # requests per minute
_RATE_LIMIT_BURST = int(os.environ.get("DAX_RATE_LIMIT_BURST", "50"))  # max burst

# Exempt paths that should never be rate-limited
_RATE_EXEMPT = frozenset({
    "/docs", "/openapi.json", "/redoc",
    "/runtime/ui", "/runtime/ui-react", "/runtime/ui-legacy",
})
_RATE_EXEMPT_PREFIXES = ("/assets/", "/static/")


class _TokenBucket:
    """Simple per-IP token bucket."""

    __slots__ = ("tokens", "last_refill", "rate", "capacity")

    def __init__(self, rate: float, capacity: int) -> None:
        self.rate = rate            # tokens per second
        self.capacity = capacity    # max burst
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.last_refill = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


# SEC-24: Maximum tracked IPs and eviction interval
_MAX_BUCKETS = 10_000
_EVICTION_INTERVAL = 600  # seconds (10 minutes)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiting middleware (SEC-03)."""

    def __init__(self, app: Any, rpm: int = _RATE_LIMIT_RPM, burst: int = _RATE_LIMIT_BURST) -> None:
        super().__init__(app)
        self._rate = rpm / 60.0  # tokens per second
        self._burst = burst
        self._buckets: dict[str, _TokenBucket] = {}
        self._lock = Lock()
        self._enabled = rpm > 0
        self._last_eviction = time.monotonic()

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if not self._enabled:
            return await call_next(request)

        # Skip rate limiting for static/UI pages
        path = request.url.path.rstrip("/")
        if path in _RATE_EXEMPT:
            return await call_next(request)
        for prefix in _RATE_EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        with self._lock:
            # SEC-24: Periodic eviction of stale buckets to prevent unbounded memory
            now = time.monotonic()
            if now - self._last_eviction > _EVICTION_INTERVAL or len(self._buckets) > _MAX_BUCKETS:
                cutoff = now - _EVICTION_INTERVAL
                stale = [ip for ip, b in self._buckets.items() if b.last_refill < cutoff]
                for ip in stale:
                    del self._buckets[ip]
                self._last_eviction = now

            bucket = self._buckets.get(client_ip)
            if bucket is None:
                bucket = _TokenBucket(self._rate, self._burst)
                self._buckets[client_ip] = bucket
            allowed = bucket.consume()

        if not allowed:
            logger.warning("Rate limit exceeded for %s on %s", client_ip, path)
            return JSONResponse(
                {"ok": False, "error": "rate_limit_exceeded",
                 "message": "Too many requests. Please slow down."},
                status_code=429,
                headers={"Retry-After": str(int(60 / self._rate)) if self._rate > 0 else "60"},
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# SEC-07: Security Headers
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security response headers to every response (SEC-07)."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "font-src 'self' data:"
        )
        return response


# ---------------------------------------------------------------------------
# SEC-12: Request Body Size Limit
# ---------------------------------------------------------------------------

_MAX_BODY_BYTES = int(os.environ.get("DAX_MAX_BODY_BYTES", str(10 * 1024 * 1024)))  # 10 MB

# Paths that may receive larger uploads (enterprise features)
_SIZE_EXEMPT_PATHS = frozenset({
    "/server/import",
    "/server/deploy",
})


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests with Content-Length exceeding the configured limit (SEC-12)."""

    def __init__(self, app: Any, max_bytes: int = _MAX_BODY_BYTES) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if self._max_bytes <= 0:
            return await call_next(request)

        path = request.url.path.rstrip("/")
        if path in _SIZE_EXEMPT_PATHS:
            return await call_next(request)

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except (ValueError, TypeError):
                length = 0
            if length > self._max_bytes:
                return JSONResponse(
                    {"ok": False, "error": "payload_too_large",
                     "message": f"Request body exceeds {self._max_bytes // (1024*1024)}MB limit."},
                    status_code=413,
                )

        return await call_next(request)


# ---------------------------------------------------------------------------
# SEC-19: CSRF Protection — require X-Requested-With on state-changing requests
# ---------------------------------------------------------------------------

_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_CSRF_EXEMPT_PREFIXES = ("/docs", "/openapi.json", "/redoc")


class CSRFMiddleware(BaseHTTPMiddleware):
    """Reject cross-origin state-changing requests without CSRF evidence (SEC-19).

    Accepts any of:
    - X-Requested-With header (any value)
    - Content-Type: application/json (not a "simple" type per CORS spec)
    Browsers cannot send either on a "simple" cross-origin request, which blocks CSRF.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if request.method in _CSRF_SAFE_METHODS:
            return await call_next(request)

        path = request.url.path
        for prefix in _CSRF_EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        # Accept X-Requested-With OR non-simple Content-Type as CSRF proof
        has_xrw = bool(request.headers.get("x-requested-with"))
        content_type = (request.headers.get("content-type") or "").lower()
        has_json_ct = "application/json" in content_type

        if not has_xrw and not has_json_ct:
            return JSONResponse(
                {"ok": False, "error": "csrf_rejected",
                 "message": "Missing X-Requested-With header."},
                status_code=403,
            )

        return await call_next(request)
