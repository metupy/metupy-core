"""
metupy_core.api
~~~~~~~~~

Dynamic REST API endpoints for Metupy — Hybrid Mode.
All entities use UUID v4 identifiers. Built on Peewee ORM + ASGI.
Can be mounted alongside static files for full dynamic capability.

Endpoints:
    GET  /api/v1/content          — List all published content
    GET  /api/v1/content/:uuid   — Single content by UUID
    GET  /api/v1/content/slug/:slug — Single content by slug
    GET  /api/v1/tags             — All tags
    GET  /api/v1/tags/:slug/content — Content by tag
    GET  /api/v1/assets           — List assets
    GET  /api/v1/settings         — Public site settings
    GET  /api/v1/health           — Health check

Usage:
    from metupy_core.api import create_api_app
    app = create_api_app()
"""

import json
from typing import Any, Dict, List, Optional, Callable
from urllib.parse import parse_qs
from pathlib import Path

from .database import (
    db, Content, Tag, ContentTag, Asset, Setting,
    init_database, query_content,
)
from .logging import log


__all__ = [
    "create_api_app",
    "APIError",
]


# ─── Custom Exceptions ───

class APIError(Exception):
    """API-friendly error with status code."""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


# ─── Helper Functions ───

def _parse_query_string(query_string: bytes) -> Dict[str, Any]:
    """Parse URL query string into dictionary."""
    raw = parse_qs(query_string.decode("utf-8", errors="replace"))
    return {
        k: v[0] if len(v) == 1 else v
        for k, v in raw.items()
    }


def _json_dump(data: Any) -> bytes:
    """JSON dump with UTF-8 support."""
    return json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")


async def _send_json(
    send: Callable,
    status: int,
    data: Any,
    headers: Optional[List[tuple]] = None,
) -> None:
    """Send standardized JSON response."""
    body = _json_dump(data)
    response_headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"access-control-allow-origin", b"*"),
    ]
    if headers:
        response_headers.extend(headers)

    await send({
        "type": "http.response.start",
        "status": status,
        "headers": response_headers,
    })
    await send({
        "type": "http.response.body",
        "body": body,
    })


# ─── API App Factory ───

def create_api_app(
    database_url: Optional[str | Path] = None,
    prefix: str = "/api/v1",
    init_db: bool = True,
):
    """
    Create fully-featured ASGI API application.

    Args:
        database_url: Path to SQLite database
        prefix: URL prefix for all endpoints (e.g., /api/v1)
        init_db: Auto-initialize database schema on startup
    """

    if init_db:
        init_database(database_url)
        log.debug(f"API initialized — prefix: {prefix}")

    # ─── Main ASGI Application ───

    async def app(scope: Dict[str, Any], receive: Callable, send: Callable) -> None:
        """Main request router."""
        if scope["type"] != "http":
            return

        path = scope.get("path", "/")
        method = scope.get("method", "GET")

        # CORS Preflight
        if method == "OPTIONS":
            return await _handle_options(send)

        # Not under API prefix → skip
        if not path.startswith(prefix):
            return

        try:
            await _route_request(method, path, prefix, scope, send)
        except APIError as e:
            await _send_json(send, e.status_code, {
                "error": True,
                "status": e.status_code,
                "detail": e.detail,
            })
        except Exception as e:
            log.error(f"API Error: {e}")
            await _send_json(send, 500, {
                "error": True,
                "status": 500,
                "detail": "Internal server error",
            })

    # ─── Router ───

    async def _route_request(
        method: str, path: str, prefix: str, scope: Dict, send: Callable
    ) -> None:
        """Match path to endpoint handler."""
        # GET /api/v1/health
        if path == f"{prefix}/health" and method == "GET":
            await _health_check(send)

        # GET /api/v1/content
        elif path == f"{prefix}/content" and method == "GET":
            params = _parse_query_string(scope.get("query_string", b""))
            await _list_content(params, send)

        # GET /api/v1/content/:uuid
        elif path.startswith(f"{prefix}/content/") and method == "GET":
            uuid_or_slug = path[len(f"{prefix}/content/") :]
            if uuid_or_slug == "slug":
                return  # handled below
            await _get_content_detail(uuid_or_slug, send)

        # GET /api/v1/content/slug/:slug
        elif path.startswith(f"{prefix}/content/slug/") and method == "GET":
            slug = path[len(f"{prefix}/content/slug/") :]
            await _get_content_by_slug(slug, send)

        # GET /api/v1/tags
        elif path == f"{prefix}/tags" and method == "GET":
            await _list_tags(send)

        # GET /api/v1/tags/:slug/content
        elif path.startswith(f"{prefix}/tags/") and path.endswith("/content") and method == "GET":
            tag_slug = path[len(f"{prefix}/tags/") : -len("/content")]
            params = _parse_query_string(scope.get("query_string", b""))
            await _list_content_by_tag(tag_slug, params, send)

        # GET /api/v1/assets
        elif path == f"{prefix}/assets" and method == "GET":
            await _list_assets(send)

        # GET /api/v1/settings
        elif path == f"{prefix}/settings" and method == "GET":
            await _get_public_settings(send)

        else:
            raise APIError(404, "Endpoint not found")

    # ─── Endpoint Handlers ───

    async def _handle_options(send: Callable) -> None:
        """CORS preflight response."""
        await send({
            "type": "http.response.start",
            "status": 204,
            "headers": [
                (b"access-control-allow-origin", b"*"),
                (b"access-control-allow-methods", b"GET, OPTIONS"),
                (b"access-control-allow-headers", b"Content-Type"),
            ],
        })
        await send({"type": "http.response.body", "body": b""})

    async def _health_check(send: Callable) -> None:
        """API & database health check."""
        db_status = "connected" if not db.is_closed() else "disconnected"
        await _send_json(send, 200, {
            "status": "ok",
            "database": db_status,
            "version": "1.0.0",
        })

    async def _list_content(params: Dict[str, Any], send: Callable) -> None:
        """List published content with filters & pagination."""
        limit = min(int(params.get("limit", 20)), 100)
        offset = int(params.get("offset", 0))
        tag_param = params.get("tag")
        format_param = params.get("format")
        order = params.get("order", "published_at DESC")

        items = query_content(
            limit=limit,
            offset=offset,
            published_only=True,
            tag=tag_param,
            format=format_param,
            order_by=order,
        )

        await _send_json(send, 200, {
            "data": items,
            "meta": {
                "limit": limit,
                "offset": offset,
                "count": len(items),
            },
        })

    async def _get_content_detail(uuid: str, send: Callable) -> None:
        """Get single content by UUID v4."""
        try:
            item = Content.get(Content.uuid == uuid)
            if not item.is_published:
                raise APIError(403, "Content not published")
            await _send_json(send, 200, {"data": item.to_dict()})
        except Content.DoesNotExist:
            raise APIError(404, "Content not found")

    async def _get_content_by_slug(slug: str, send: Callable) -> None:
        """Get single content by slug instead of UUID."""
        try:
            item = Content.get(Content.slug == slug)
            if not item.is_published:
                raise APIError(403, "Content not published")
            await _send_json(send, 200, {"data": item.to_dict()})
        except Content.DoesNotExist:
            raise APIError(404, "Content not found")

    async def _list_tags(send: Callable) -> None:
        """Get all tags with content count."""
        query = Tag.select().order_by(Tag.name)
        items = []
        for tag in query:
            count = (
                ContentTag.select()
                .join(Content)
                .where(
                    (ContentTag.tag == tag) &
                    (Content.is_published == True)
                )
                .count()
            )
            items.append({**tag.to_dict(), "count": count})

        await _send_json(send, 200, {"data": items})

    async def _list_content_by_tag(tag_slug: str, params: Dict[str, Any], send: Callable) -> None:
        """List published content filtered by tag slug."""
        limit = min(int(params.get("limit", 20)), 100)
        offset = int(params.get("offset", 0))

        items = query_content(
            limit=limit,
            offset=offset,
            tag=tag_slug,
            published_only=True,
        )

        await _send_json(send, 200, {
            "data": items,
            "meta": {"tag": tag_slug, "limit": limit, "offset": offset},
        })

    async def _list_assets(send: Callable) -> None:
        """List all tracked assets."""
        query = Asset.select().order_by(Asset.uploaded_at.desc()).limit(100)
        items = [a.to_dict() for a in query]
        await _send_json(send, 200, {"data": items})

    async def _get_public_settings(send: Callable) -> None:
        """Expose public site configuration."""
        public_keys = ["site_name", "site_description", "site_url", "theme"]
        settings = {}
        for key in public_keys:
            val = Setting.get_value(key)
            if val is not None:
                settings[key] = val
        await _send_json(send, 200, {"data": settings})

    return app
