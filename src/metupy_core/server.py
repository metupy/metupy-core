"""
metupy_core.server
~~~~~~~~~~~~~

Development server with live reload.
Provides WSGI and ASGI application interfaces for production deployment.

Usage:
    # Development
    server = MetupyServer()
    server.start()

    # Production WSGI (Gunicorn, etc.)
    from metupy.server import wsgi_app
    app = wsgi_app(directory="public")

    # Production ASGI (Uvicorn, etc.)
    from metupy.server import asgi_app
    app = asgi_app(directory="public")
"""

import socket
import threading
from pathlib import Path
from typing import Callable, Optional, Any
from http.server import HTTPServer, SimpleHTTPRequestHandler

from .logging import log
from .utils import get_free_port, watch_directory


__all__ = [
    "MetupyServer",
    "LiveReloadHandler",
    "wsgi_app",
    "asgi_app",
    "run_server",
]


# ─── HTTP Request Handler ───

class LiveReloadHandler(SimpleHTTPRequestHandler):
    """Custom HTTP handler that serves static files with development-friendly headers."""

    def __init__(self, *args, **kwargs):
        self.directory = kwargs.pop("directory", "public")
        super().__init__(*args, directory=self.directory, **kwargs)

    def end_headers(self) -> None:
        """Set cache control headers."""
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, format, *args) -> None:
        """Suppress default logging."""
        log.debug(f"HTTP {format % args}")


# ─── WSGI Application ───

def wsgi_app(directory: str | Path = "public") -> Callable:
    """
    Create a WSGI application for production deployment.
    Compatible with: Gunicorn, uWSGI, mod_wsgi, etc.

    Usage:
        gunicorn --bind 0.0.0.0:8000 metupy.server:app
    """
    directory = Path(directory).resolve()

    def app(environ: dict, start_response: Callable) -> list[bytes]:
        """WSGI application callable."""
        path = environ.get("PATH_INFO", "/")
        method = environ.get("REQUEST_METHOD", "GET")

        if method != "GET" and method != "HEAD":
            start_response("405 Method Not Allowed", [("Content-Type", "text/plain")])
            return [b"Method Not Allowed"]

        # Resolve file path
        file_path = directory / path.lstrip("/")
        if file_path.is_dir():
            file_path = file_path / "index.html"

        if not file_path.exists() or not file_path.is_file():
            start_response("404 Not Found", [("Content-Type", "text/plain")])
            return [b"Not Found"]

        # Read and serve file
        try:
            content = file_path.read_bytes()
            content_type = _guess_mime_type(file_path.name)
            headers = [
                ("Content-Type", content_type),
                ("Content-Length", str(len(content))),
                ("Cache-Control", "public, max-age=3600"),
            ]
            start_response("200 OK", headers)
            return [content]
        except Exception as e:
            log.error(f"WSGI error: {e}")
            start_response("500 Internal Server Error", [("Content-Type", "text/plain")])
            return [b"Internal Server Error"]

    return app


# ─── ASGI Application ───

def asgi_app(directory: str | Path = "public") -> Callable:
    """
    Create an ASGI application for production deployment.
    Compatible with: Uvicorn, Hypercorn, Daphne, etc.

    Usage:
        uvicorn metupy.server:app --host 0.0.0.0 --port 8000
    """
    directory = Path(directory).resolve()

    async def app(scope: dict, receive: Callable, send: Callable) -> None:
        """ASGI application callable."""
        if scope["type"] != "http":
            return

        path = scope.get("path", "/")
        method = scope.get("method", "GET")

        if method not in ("GET", "HEAD"):
            await send({
                "type": "http.response.start",
                "status": 405,
                "headers": [(b"content-type", b"text/plain")],
            })
            await send({"type": "http.response.body", "body": b"Method Not Allowed"})
            return

        # Resolve file path
        file_path = directory / path.lstrip("/")
        if file_path.is_dir():
            file_path = file_path / "index.html"

        if not file_path.exists() or not file_path.is_file():
            await send({
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-type", b"text/plain")],
            })
            await send({"type": "http.response.body", "body": b"Not Found"})
            return

        # Read and serve file
        try:
            content = file_path.read_bytes()
            content_type = _guess_mime_type(file_path.name).encode("utf-8")

            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", content_type),
                    (b"content-length", str(len(content)).encode("utf-8")),
                    (b"cache-control", b"public, max-age=3600"),
                ],
            })
            await send({"type": "http.response.body", "body": content})
        except Exception as e:
            log.error(f"ASGI error: {e}")
            await send({
                "type": "http.response.start",
                "status": 500,
                "headers": [(b"content-type", b"text/plain")],
            })
            await send({"type": "http.response.body", "body": b"Internal Server Error"})

    return app


# ─── MIME Type Helper ───

def _guess_mime_type(filename: str) -> str:
    """Simple MIME type detection for common file types."""
    ext = Path(filename).suffix.lower()
    mime_types = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
    }
    return mime_types.get(ext, "application/octet-stream")


# ─── Development Server ───

class MetupyServer:
    """Development server with file watching and auto-rebuild support."""

    def __init__(
        self,
        content_dir: str | Path = "contents",
        output_dir: str | Path = "public",
        port: int = 3000,
        host: str = "localhost",
    ):
        self.content_dir = Path(content_dir).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.port = port
        self.host = host
        self.server: Optional[HTTPServer] = None
        self._watch_thread: Optional[threading.Thread] = None
        self._running = False
        self.last_rebuild = 0.0

    # ─── Public API ───

    def start(self, rebuild_callback: Optional[Callable] = None) -> None:
        """Start the HTTP server and file watcher thread."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        log.debug(f"Output directory ensured: {self.output_dir}")

        self.port = get_free_port(self.host, self.port)
        log.debug(f"Using port: {self.port}")

        handler = lambda *args, **kwargs: LiveReloadHandler(
            *args, directory=self.output_dir, **kwargs
        )
        self.server = HTTPServer((self.host, self.port), handler)
        self._running = True

        self._start_file_watcher(rebuild_callback)

        local_ip = self._get_local_ip()
        log.info("Development server started")
        log.info(f"  Local:   http://{self.host}:{self.port}")
        log.info(f"  Network: http://{local_ip}:{self.port}")
        log.info(f"  Watching: {self.content_dir}")
        log.info("Press Ctrl+C to stop")

        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        """Gracefully stop the server and watcher."""
        self._running = False
        if self.server:
            self.server.shutdown()
        log.info("Development server stopped")

    # ─── Internal Helpers ───

    def _start_file_watcher(self, callback: Optional[Callable] = None) -> None:
        """Initialize background thread for file change detection."""
        def on_change(path: Path) -> None:
            if not self._running:
                return
            if path.name.startswith(".") or path.suffix in {".swp", "~", ".tmp"}:
                return
            log.info(f"Detected change: {path.relative_to(Path.cwd())} — rebuilding...")
            self.last_rebuild = Path.cwd().stat().st_mtime
            if callback:
                callback()

        self._watch_thread = threading.Thread(
            target=self._watch_loop,
            args=(on_change,),
            daemon=True,
        )
        self._watch_thread.start()
        log.debug("File watcher thread started")

    def _watch_loop(self, on_change: Callable[[Path], None]) -> None:
        """Watch content and config directories for changes."""
        watch_directory(self.content_dir, on_change, interval=1.0)
        watch_directory(Path.cwd(), on_change, file_pattern="metupyconfig.py", interval=1.0)

    def _get_local_ip(self) -> str:
        """Retrieve local network IP address for LAN access."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return self.host


# ─── Convenience Function ───

def run_server(
    content_dir: str | Path = "contents",
    output_dir: str | Path = "public",
    port: int = 3000,
    host: str = "localhost",
    rebuild_callback: Optional[Callable] = None,
) -> None:
    """Start development server with specified configuration."""
    server = MetupyServer(content_dir, output_dir, port, host)
    server.start(rebuild_callback)
