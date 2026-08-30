"""
metupy_core.cache
~~~~~~~~~~~~

File-based caching system for Metupy.
Tracks file changes and skips reprocessing unchanged content.
Supports both in-memory and persistent disk cache.
"""

import os
import json
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime

from .logging import log


__all__ = ["Cache", "FileCache"]


class Cache:
    """
    Simple in-memory cache with TTL support.
    Used for temporary data during a single build session.
    """

    def __init__(self):
        self._data: Dict[str, tuple[Any, Optional[float]]] = {}

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Store value with optional TTL in seconds."""
        expire_at = None if ttl is None else datetime.now().timestamp() + ttl
        self._data[key] = (value, expire_at)

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve value, return default if missing or expired."""
        item = self._data.get(key)
        if item is None:
            return default
        value, expire_at = item
        if expire_at and datetime.now().timestamp() > expire_at:
            del self._data[key]
            return default
        return value

    def has(self, key: str) -> bool:
        """Check if key exists and not expired."""
        return key in self._data and self.get(key) is not None

    def delete(self, key: str) -> None:
        """Remove key from cache."""
        self._data.pop(key, None)

    def clear(self) -> None:
        """Clear all in-memory data."""
        self._data.clear()
        log.debug("In-memory cache cleared")

    def __contains__(self, key: str) -> bool:
        return self.has(key)


class FileCache:
    """
    Persistent disk cache for tracking file state between builds.
    Stores file hashes and modification times to detect changes.
    """

    def __init__(self, cache_dir: str | Path = ".metupy/cache"):
        self.cache_dir = Path(cache_dir).resolve()
        self._index_path = self.cache_dir / "index.json"
        self._index: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def _ensure_dir(self) -> None:
        """Create cache directory if not exists."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> None:
        """Load cache index from disk."""
        if not self._index_path.exists():
            self._index = {}
            self._loaded = True
            return

        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                self._index = json.load(f)
            self._loaded = True
            log.debug(f"Cache loaded: {len(self._index)} entries")
        except (json.JSONDecodeError, IOError) as e:
            log.warning(f"Failed to load cache index: {e}")
            self._index = {}
            self._loaded = True

    def save(self) -> None:
        """Save cache index to disk."""
        self._ensure_dir()
        try:
            with open(self._index_path, "w", encoding="utf-8") as f:
                json.dump(self._index, f, indent=2)
            log.debug(f"Cache saved: {len(self._index)} entries")
        except IOError as e:
            log.warning(f"Failed to save cache index: {e}")

    def _compute_file_hash(self, file_path: Path) -> str:
        """Calculate MD5 hash of a file for change detection."""
        h = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
            return h.hexdigest()
        except IOError:
            return ""

    def is_changed(self, file_path: Path | str) -> bool:
        """
        Check if file has changed since last build.
        Returns True if file is new, modified, or hash differs.
        """
        if not self._loaded:
            self.load()

        file_path = Path(file_path).resolve()
        if not file_path.exists():
            return True

        rel_path = str(file_path)
        current_mtime = file_path.stat().st_mtime
        current_hash = self._compute_file_hash(file_path)

        entry = self._index.get(rel_path)
        if entry is None:
            log.debug(f"New file detected: {file_path.name}")
            return True

        if entry.get("mtime") != current_mtime or entry.get("hash") != current_hash:
            log.debug(f"File changed: {file_path.name}")
            return True

        return False

    def update(self, file_path: Path | str, extra: Dict[str, Any] | None = None) -> None:
        """Update cache entry for a file after processing."""
        if not self._loaded:
            self.load()

        file_path = Path(file_path).resolve()
        if not file_path.exists():
            return

        rel_path = str(file_path)
        self._index[rel_path] = {
            "mtime": file_path.stat().st_mtime,
            "hash": self._compute_file_hash(file_path),
            "updated_at": datetime.now().isoformat(),
            **(extra or {}),
        }

    def remove(self, file_path: Path | str) -> None:
        """Remove file from cache (called when file is deleted)."""
        file_path = Path(file_path).resolve()
        self._index.pop(str(file_path), None)
        log.debug(f"Removed from cache: {file_path.name}")

    def clear(self) -> None:
        """Clear entire cache and delete cache directory."""
        self._index.clear()
        if self.cache_dir.exists():
            import shutil
            try:
                shutil.rmtree(self.cache_dir)
                log.info("Cache cleared completely")
            except IOError as e:
                log.warning(f"Failed to clear cache directory: {e}")

    def get_stats(self) -> Dict[str, int]:
        """Return cache statistics."""
        return {
            "total_entries": len(self._index),
            "cache_size_files": sum(1 for p in self.cache_dir.rglob("*") if p.is_file()),
        }
