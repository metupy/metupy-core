"""
metupy_core.logging
~~~~~~~~~~~~~~

Unified logging and terminal output system for Metupy.
All terminal output throughout the application MUST go through this module.
Direct print() calls in core code are strictly prohibited.
Provides consistent formatting, color support, and configurable verbosity.
"""

import sys
from typing import Optional
from enum import Enum


class LogLevel(Enum):
    """Available logging verbosity levels."""
    DEBUG = 0
    INFO = 1
    SUCCESS = 2
    WARNING = 3
    ERROR = 4
    SILENT = 5


class Colors:
    """ANSI color codes for terminal output. Auto-disabled on non-TTY."""
    reset = "\033[0m"
    bold = "\033[1m"
    gray = "\033[90m"
    cyan = "\033[36m"
    green = "\033[32m"
    yellow = "\033[33m"
    red = "\033[31m"
    magenta = "\033[35m"


def _supports_color() -> bool:
    """Check if current terminal supports ANSI colors."""
    if not sys.stdout.isatty():
        return False
    if sys.platform.startswith("win"):
        return "WT_SESSION" in sys.environ or "TERM_PROGRAM" in sys.environ
    return True


class Logger:
    """
    Main logger instance used throughout Metupy.
    All output goes through this class — no direct print() allowed.
    """

    def __init__(self, level: LogLevel = LogLevel.INFO, enable_color: bool = True):
        self.level = level
        self.color = enable_color and _supports_color()
        self._prefix = {
            LogLevel.DEBUG: "[DEBUG]",
            LogLevel.INFO: "[INFO]",
            LogLevel.SUCCESS: "[OK]",
            LogLevel.WARNING: "[WARN]",
            LogLevel.ERROR: "[ERROR]",
        }
        self._color_map = {
            LogLevel.DEBUG: Colors.gray,
            LogLevel.INFO: Colors.cyan,
            LogLevel.SUCCESS: Colors.green,
            LogLevel.WARNING: Colors.yellow,
            LogLevel.ERROR: Colors.red,
        }

    def _should_print(self, level: LogLevel) -> bool:
        """Check if message at given level should be printed."""
        return self.level.value <= level.value

    def _format(self, level: LogLevel, message: str) -> str:
        """Apply prefix, color and styling to message."""
        prefix = self._prefix.get(level, "")
        if self.color:
            color_code = self._color_map.get(level, "")
            return f"{color_code}{prefix} {message}{Colors.reset}"
        return f"{prefix} {message}"

    def debug(self, message: str) -> None:
        """Verbose debugging information."""
        if self._should_print(LogLevel.DEBUG):
            sys.stderr.write(self._format(LogLevel.DEBUG, message) + "\n")
            sys.stderr.flush()

    def info(self, message: str) -> None:
        """General informational messages."""
        if self._should_print(LogLevel.INFO):
            sys.stderr.write(self._format(LogLevel.INFO, message) + "\n")
            sys.stderr.flush()

    def success(self, message: str) -> None:
        """Successful operation messages."""
        if self._should_print(LogLevel.SUCCESS):
            sys.stderr.write(self._format(LogLevel.SUCCESS, message) + "\n")
            sys.stderr.flush()

    def warning(self, message: str) -> None:
        """Non-critical issues or warnings."""
        if self._should_print(LogLevel.WARNING):
            sys.stderr.write(self._format(LogLevel.WARNING, message) + "\n")
            sys.stderr.flush()

    def error(self, message: str) -> None:
        """Error messages or failures."""
        if self._should_print(LogLevel.ERROR):
            sys.stderr.write(self._format(LogLevel.ERROR, message) + "\n")
            sys.stderr.flush()

    def header(self, title: str) -> None:
        """Print section header with visual separator."""
        if not self._should_print(LogLevel.INFO):
            return
        line = "=" * 50
        if self.color:
            sys.stderr.write(f"\n{Colors.bold}{Colors.magenta}{title}{Colors.reset}\n")
            sys.stderr.write(f"{Colors.gray}{line}{Colors.reset}\n\n")
        else:
            sys.stderr.write(f"\n{title}\n{line}\n\n")
        sys.stderr.flush()

    def raw(self, message: str = "") -> None:
        """Raw unformatted output — use only for special cases."""
        sys.stderr.write(message + "\n")
        sys.stderr.flush()

    def set_level(self, level: LogLevel | str) -> None:
        """Change verbosity level at runtime."""
        if isinstance(level, str):
            level = LogLevel[level.upper()]
        self.level = level


# ─── Default Global Instance ───
log = Logger()


def get_logger() -> Logger:
    """Return the global logger instance for consistent usage."""
    return log


def set_verbose(enabled: bool = True) -> None:
    """Shortcut to enable debug logging."""
    log.set_level(LogLevel.DEBUG if enabled else LogLevel.INFO)


def set_silent(enabled: bool = True) -> None:
    """Shortcut to suppress all output except errors."""
    log.set_level(LogLevel.ERROR if enabled else LogLevel.INFO)
