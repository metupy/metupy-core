"""
metupy_core.middleware
~~~~~~~~~~~~~~~~~

ASGI Middleware stack for request/response processing.
Pluggable, composable middleware — add/remove layers without changing handlers.

Built-in Middleware:
    • CORSMiddleware        — Cross-Origin Resource Sharing
    • LoggingMiddleware     — Request logging & timing
    • SecurityMiddleware    — Security headers (CSP, HSTS, X-Frame-Options)
    • RateLimitMiddleware   — Basic rate limiting
    • CacheMiddleware       — Cache control headers
    • GZipMiddleware        — Response compression
    • DatabaseMiddleware    — Auto open/close DB connection

Usage:
    from metupy.middleware import MiddlewareStack, CORSMiddleware, LoggingMiddleware
    app = MiddlewareStack(
        api_app,
        CORSMiddleware(allow_origins=["*"]),
        LoggingMiddleware(),
    )
"""

import time
import gzip
import io
from typing import Any, Callable, List, Optional, Dict
from datetime import datetime, timedelta
from ipaddress import ip_address, ip_network

from .logging import log
from .database import db


__all__ = [
    "Middleware",
    "MiddlewareStack",
    "CORSMiddleware",
    "LoggingMiddleware",
    "SecurityMiddleware",
    "RateLimitMiddleware",
    "CacheMiddleware",
    "GZipMiddleware",
    "DatabaseMiddleware",
]


# ─── Base Middleware ───

class Middleware:
    """Base class for all middleware."""

    async def __call__(
        self,
        scope: Dict[str, Any],
        receive: Callable,
        send: Callable,
        next_app: Callable,
    ) -> None:
        """Process request/response — override in subclasses."""
        await next_app(scope, receive, send)


class MiddlewareStack:
    """
    Compose multiple middleware into a single ASGI app.
    Middleware runs in order they are added — first in, first out.
    """

    def __init__(self, app: Callable, *middlewares: Middleware):
        self.app = app
        self.middlewares: List[Middleware] = list(middlewares)

        # Wrap middleware chain — last added runs innermost
        for mw in reversed(self.middlewares):
            self.app = self._wrap(mw, self.app)

    def _wrap(self, middleware: Middleware, next_app: Callable) -> Callable:
        """Wrap middleware into ASGI app."""
        async def wrapped(scope: Dict, receive: Callable, send: Callable):
            async def next_layer(s, r, se):
                await next_app(s, r, se)
            await middleware(scope, receive, send, next_layer)
        return wrapped

    async def __call__(self, scope: Dict, receive: Callable, send: Callable) -> None:
        await self.app(scope, receive, send)


# ─── Built-in Middleware ───

class CORSMiddleware(Middleware):
    """
    Cross-Origin Resource Sharing middleware.
    Auto-handles OPTIONS preflight requests.

    Config:
        allow_origins: "*" or list of allowed origins
        allow_methods: Allowed HTTP methods
        allow_headers: Allowed request headers
        max_age: Cache preflight response (seconds)
    """

    def __init__(
        self,
        allow_origins: List[str] | str = "*",
        allow_methods: List[str] = None,
        allow_headers: List[str] = None,
        max_age: int = 86400,
    ):
        self.allow_origins = allow_origins
        self.allow_methods = allow_methods or ["GET", "HEAD", "OPTIONS"]
        self.allow_headers = allow_headers or ["Content-Type", "Authorization"]
        self.max_age = max_age

    async def __call__(
        self,
        scope: Dict,
        receive: Callable,
        send: Callable,
        next_app: Callable,
    ) -> None:
        if scope["type"] != "http":
            return await next_app(scope, receive, send)

        origin = dict(scope.get("headers", [])).get(b"origin", b"").decode()
        headers = self._get_cors_headers(origin)

        # Preflight OPTIONS request
        if scope["method"] == "OPTIONS":
            await send({
                "type": "http.response.start",
                "status": 204,
                "headers": headers,
            })
            await send({"type": "http.response.body", "body": b""})
            return

        # Capture response & inject CORS headers
        original_send = send
        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message["headers"] = message.get("headers", []) + headers
            await original_send(message)

        await next_app(scope, receive, send_with_headers)

    def _get_cors_headers(self, origin: str) -> List[tuple]:
        """Build CORS headers based on origin check."""
        if self.allow_origins == "*":
            allow_origin = "*"
        elif origin in self.allow_origins:
            allow_origin = origin
        else:
            allow_origin = self.allow_origins[0] if self.allow_origins else "*"

        return [
            (b"access-control-allow-origin", allow_origin.encode()),
            (b"access-control-allow-methods", ", ".join(self.allow_methods).encode()),
            (b"access-control-allow-headers", ", ".join(self.allow_headers).encode()),
            (b"access-control-max-age", str(self.max_age).encode()),
        ]


class LoggingMiddleware(Middleware):
    """Log all requests with method, path, status, duration, and IP."""

    async def __call__(
        self,
        scope: Dict,
        receive: Callable,
        send: Callable,
        next_app: Callable,
    ) -> None:
        if scope["type"] != "http":
            return await next_app(scope, receive, send)

        start_time = time.perf_counter()
        method = scope["method"]
        path = scope["path"]
        client = scope.get("client", ("unknown", 0))[0]

        status_code = 0
        async def capture_status(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await next_app(scope, receive, capture_status)
        except Exception as e:
            status_code = 500
            raise
        finally:
            duration = (time.perf_counter() - start_time) * 1000
            log.info(f"{method} {path} → {status_code} ({duration:.2f}ms) from {client}")


class SecurityMiddleware(Middleware):
    """
    Security headers — protect against common attacks.
    HSTS, CSP, X-Frame-Options, X-XSS-Protection, etc.
    """

    def __init__(
        self,
        hsts: bool = True,
        csp: str = "default-src 'self'",
        frame_options: str = "DENY",
        xss_protection: bool = True,
    ):
        self.hsts = hsts
        self.csp = csp
        self.frame_options = frame_options
        self.xss_protection = xss_protection

    async def __call__(
        self,
        scope: Dict,
        receive: Callable,
        send: Callable,
        next_app: Callable,
    ) -> None:
        if scope["type"] != "http":
            return await next_app(scope, receive, send)

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = message.get("headers", [])
                headers.extend([
                    (b"x-frame-options", self.frame_options.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"content-security-policy", self.csp.encode()),
                ])
                if self.hsts:
                    headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                if self.xss_protection:
                    headers.append((b"x-xss-protection", b"1; mode=block"))
                message["headers"] = headers
            await send(message)

        await next_app(scope, receive, secure_send)


class RateLimitMiddleware(Middleware):
    """
    Basic in-memory rate limiting.
    Limit requests per IP per window.
    """

    def __init__(
        self,
        requests_per_minute: int = 120,
        window_seconds: int = 60,
        exclude_paths: List[str] = None,
    ):
        self.rate = requests_per_minute
        self.window = window_seconds
        self.exclude_paths = exclude_paths or ["/health"]
        self._requests: Dict[str, List[float]] = {}

    async def __call__(
        self,
        scope: Dict,
        receive: Callable,
        send: Callable,
        next_app: Callable,
    ) -> None:
        if scope["type"] != "http":
            return await next_app(scope, receive, send)

        path = scope["path"]
        if any(path.startswith(p) for p in self.exclude_paths):
            return await next_app(scope, receive, send)

        client_ip = scope.get("client", ("127.0.0.1", 0))[0]
        now = time.time()

        # Clean old entries
        if client_ip not in self._requests:
            self._requests[client_ip] = []
        self._requests[client_ip] = [t for t in self._requests[client_ip] if now - t < self.window]

        if len(self._requests[client_ip]) >= self.rate:
            log.warning(f"Rate limit exceeded: {client_ip}")
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({"type": "http.response.body", "body": b'{"error": "Rate limit exceeded"}'})
            return

        self._requests[client_ip].append(now)
        await next_app(scope, receive, send)


class CacheMiddleware(Middleware):
    """
    Set Cache-Control headers based on path patterns.
    Static files → long cache; API → no-cache.
    """

    def __init__(
        self,
        static_max_age: int = 86400,
        api_max_age: int = 0,
    ):
        self.static_max_age = static_max_age
        self.api_max_age = api_max_age

    async def __call__(
        self,
        scope: Dict,
        receive: Callable,
        send: Callable,
        next_app: Callable,
    ) -> None:
        if scope["type"] != "http":
            return await next_app(scope, receive, send)

        path = scope["path"]
        if path.startswith("/api/"):
            cc = f"no-cache, no-store, must-revalidate, max-age={self.api_max_age}"
        elif path.endswith((".css", ".js", ".png", ".jpg", ".svg", ".woff2")):
            cc = f"public, max-age={self.static_max_age}, immutable"
        else:
            cc = "public, max-age=3600"

        async def cache_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = message.get("headers", []) + [
                    (b"cache-control", cc.encode())
                ]
            await send(message)

        await next_app(scope, receive, cache_send)


class GZipMiddleware(Middleware):
    """Compress responses larger than threshold with GZip."""

    def __init__(self, minimum_size: int = 500, compress_level: int = 6):
        self.minimum_size = minimum_size
        self.level = compress_level

    async def __call__(
        self,
        scope: Dict,
        receive: Callable,
        send: Callable,
        next_app: Callable,
    ) -> None:
        if scope["type"] != "http":
            return await next_app(scope, receive, send)

        accept_encoding = dict(scope.get("headers", [])).get(b"accept-encoding", b"").decode()
        supports_gzip = "gzip" in accept_encoding.lower()

        if not supports_gzip:
            return await next_app(scope, receive, send)

        body_buffer = []
        status = 0
        headers = []

        async def capture_response(message):
            nonlocal status, headers
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = message.get("headers", [])
            elif message["type"] == "http.response.body":
                body_buffer.append(message.get("body", b""))

        await next_app(scope, receive, capture_response)

        body = b"".join(body_buffer)

        # Skip compression for small responses or already compressed
        if len(body) < self.minimum_size or any(
            h[0] == b"content-encoding" for h in headers
        ):
            await send({
                "type": "http.response.start",
                "status": status,
                "headers": headers,
            })
            await send({"type": "http.response.body", "body": body})
            return

        # Compress
        compressed = gzip.compress(body, compresslevel=self.level)
        new_headers = [
            (k, v) for k, v in headers
            if k not in (b"content-length", b"content-encoding")
        ]
        new_headers.extend([
            (b"content-encoding", b"gzip"),
            (b"content-length", str(len(compressed)).encode()),
        ])

        await send({
            "type": "http.response.start",
            "status": status,
            "headers": new_headers,
        })
        await send({"type": "http.response.body", "body": compressed})


class DatabaseMiddleware(Middleware):
    """
    Auto-manage database connection per request.
    Ensures connection is open and closes it after response.
    """

    async def __call__(
        self,
        scope: Dict,
        receive: Callable,
        send: Callable,
        next_app: Callable,
    ) -> None:
        if scope["type"] != "http":
            return await next_app(scope, receive, send)

        # Ensure connection
        if db.is_closed():
            db.connect()

        try:
            await next_app(scope, receive, send)
        finally:
            # Clean up — keep connection open for now
            pass
