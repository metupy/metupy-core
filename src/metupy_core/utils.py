"""
metupy_core.utils
~~~~~~~~~~~~

Utility functions and helpers used across Metupy.
"""

import os
import re
import sys
import time
import socket
import shutil
import hashlib
import fnmatch
from pathlib import Path
from datetime import datetime
from typing import Generator, Callable, Any, Iterable


__all__ = [
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
]


def get_free_port(host: str = "localhost", start_port: int = 3000) -> int:
    """
    Find first available port starting from `start_port`.
    Returns `start_port` if available, otherwise increments.
    """
    port = start_port
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
                return port
        except OSError:
            port += 1


def watch_directory(
    dir_path: Path | str,
    callback: Callable[[Path], None],
    interval: float = 1.0,
    file_pattern: str | None = None,
) -> None:
    """
    Watch directory for file changes (create, modify, delete).
    Calls `callback(changed_path)` on each change.
    Runs in infinite loop — intended to run in a thread.
    """
    dir_path = Path(dir_path).resolve()
    if not dir_path.exists():
        return

    last_snapshot: dict[Path, float] = {}

    def take_snapshot() -> dict[Path, float]:
        snap = {}
        for path in walk_files(dir_path, recursive=True):
            if file_pattern and not fnmatch.fnmatch(path.name, file_pattern):
                continue
            try:
                snap[path] = path.stat().st_mtime
            except (FileNotFoundError, PermissionError):
                continue
        return snap

    last_snapshot = take_snapshot()

    while True:
        time.sleep(interval)
        current = take_snapshot()

        # Check added / modified
        for path, mtime in current.items():
            if path not in last_snapshot or mtime > last_snapshot[path]:
                callback(path)

        # Check deleted
        for path in last_snapshot:
            if path not in current:
                callback(path)

        last_snapshot = current


def ensure_dir(path: Path | str) -> Path:
    """Ensure directory exists, create if not. Returns Path."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def clean_dir(path: Path | str) -> None:
    """Delete all contents of a directory without removing the dir itself."""
    path = Path(path)
    if not path.exists():
        return
    for item in path.iterdir():
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        except Exception as e:
            print(f"Could not remove {item}: {e}")


def copy_file(src: Path | str, dest: Path | str) -> None:
    """Copy file from src to dest, creating parent directories if needed."""
    src, dest = Path(src), Path(dest)
    ensure_dir(dest.parent)
    shutil.copy2(src, dest)


def slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    text = str(text).strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text


def format_date(dt: datetime | str | None, fmt: str = "%Y-%m-%d") -> str:
    """Format datetime object or string to readable date string."""
    if dt is None:
        return ""
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    return dt.strftime(fmt)


def file_hash(path: Path | str) -> str:
    """Calculate MD5 hash of a file for cache busting or comparison."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_ext(path: Path | str) -> str:
    """Get lowercase file extension without dot, e.g. 'md', 'pym'."""
    return Path(path).suffix.lower().lstrip(".")


def is_binary_file(path: Path | str) -> bool:
    """Check if file is binary (avoid reading as text)."""
    try:
        with open(path, "tr") as f:
            f.read(1024)
        return False
    except UnicodeDecodeError:
        return True


def walk_files(
    dir_path: Path | str,
    recursive: bool = True,
    exts: Iterable[str] | None = None,
    ignore: list[str] | None = None,
) -> Generator[Path, None, None]:
    """
    Walk through all files in a directory, recursively or not.
    Filter by extensions and ignore patterns.
    """
    dir_path = Path(dir_path).resolve()
    ignore = ignore or [".git", "__pycache__", "node_modules", ".metupy"]
    exts = set(e.lstrip(".") for e in (exts or []))

    for item in dir_path.iterdir():
        if any(fnmatch.fnmatch(item.name, pat) for pat in ignore):
            continue

        if item.is_dir():
            if recursive:
                yield from walk_files(item, recursive, exts, ignore)
            continue

        if item.is_file():
            if exts:
                if get_ext(item) not in exts:
                    continue
            yield item


def relative_path(path: Path | str, base: Path | str) -> Path:
    """Return path relative to base, handling cross-OS edge cases."""
    return Path(path).resolve().relative_to(Path(base).resolve())
