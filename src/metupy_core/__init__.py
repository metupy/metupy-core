"""
Metupy Core
~~~~~~~~~~~

Static site generator with multi-format content, AST-based templating,
and plugin-friendly architecture.

Supported formats: .pym, .py, .md, .rst
License: MIT
"""

__version__ = "0.1.1"
__author__ = "PalembangPy Community"
__license__ = "MIT"

# ─── Core Exports ───

from .logging import log, setup_logging
from .setting import Setting, load_setting, NavItem
from .signal import on, off, emit, connect, disconnect, list_signals, reset
from .utils import (
    get_free_port,
    watch_directory,
    ensure_dir,
    clean_dir,
    copy_file,
    slugify,
    format_date,
    file_hash,
    get_ext,
    is_binary_file,
    walk_files,
    relative_path,
)
from .reader import (
    FileReader,
    read_file,
    read_and_parse,
    detect_format,
    normalize_content,
    is_supported,
    SUPPORTED_EXTENSIONS,
)
from .parsers import (
    ParsedContent,
    BaseParser,
    PymParser,
    MarkdownParser,
    RestructuredTextParser,
    PythonParser,
    get_parser_for_file,
    parse_file,
)
from .renderer import (
    RenderContext,
    BaseRenderer,
    PymRenderer,
    MarkdownRenderer,
    RestructuredTextRenderer,
    PythonRenderer,
    Renderer,
    render_content,
)
from .writer import (
    write_output,
    write_binary,
    copy_assets,
    ensure_dir as ensure_output_dir,
    clean_directory,
    get_output_path,
)
from .middleware import (
    Middleware,
    MiddlewareStack,
    CORSMiddleware,
    LoggingMiddleware,
    SecurityMiddleware,
    RateLimitMiddleware,
    CacheMiddleware,
    GZipMiddleware,
    DatabaseMiddleware,
)
from .server import (
    MetupyServer,
    LiveReloadHandler,
    wsgi_app,
    asgi_app,
    run_server,
)
from .page import Page, LayoutManager, ComponentRegistry, Theme

# ─── Convenience Aliases ───

__all__ = [
    # Core
    "__version__",
    "log",
    "setup_logging",
    # Settings
    "Setting",
    "load_setting",
    "NavItem",
    # Signals
    "on",
    "off",
    "emit",
    "connect",
    "disconnect",
    "list_signals",
    "reset",
    # Utils
    "get_free_port",
    "watch_directory",
    "ensure_dir",
    "clean_dir",
    "copy_file",
    "slugify",
    "format_date",
    "file_hash",
    "get_ext",
    "is_binary_file",
    "walk_files",
    "relative_path",
    # Reader
    "FileReader",
    "read_file",
    "read_and_parse",
    "detect_format",
    "normalize_content",
    "is_supported",
    "SUPPORTED_EXTENSIONS",
    # Parsers
    "ParsedContent",
    "BaseParser",
    "PymParser",
    "MarkdownParser",
    "RestructuredTextParser",
    "PythonParser",
    "get_parser_for_file",
    "parse_file",
    # Renderer
    "RenderContext",
    "BaseRenderer",
    "PymRenderer",
    "MarkdownRenderer",
    "RestructuredTextRenderer",
    "PythonRenderer",
    "Renderer",
    "render_content",
    # Writer
    "write_output",
    "write_binary",
    "copy_assets",
    "ensure_output_dir",
    "clean_directory",
    "get_output_path",
    # Middleware
    "Middleware",
    "MiddlewareStack",
    "CORSMiddleware",
    "LoggingMiddleware",
    "SecurityMiddleware",
    "RateLimitMiddleware",
    "CacheMiddleware",
    "GZipMiddleware",
    "DatabaseMiddleware",
    # Server
    "MetupyServer",
    "LiveReloadHandler",
    "wsgi_app",
    "asgi_app",
    "run_server",
    # Page / Theme / Components
    "Page",
    "LayoutManager",
    "ComponentRegistry",
    "Theme",
]
