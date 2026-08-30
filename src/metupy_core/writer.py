"""
metupy_core.writer
~~~~~~~~~~~~~

Output writing and file system utilities.
Handles writing rendered HTML, copying assets, and directory management.
Ensures proper encoding, permissions, and error handling.

Usage:
    from metupy.writers import write_output, copy_assets

    write_output(html_content, Path("public/index.html"))
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import shutil

from .logging import log


__all__ = [
    "write_output",
    "write_binary",
    "copy_assets",
    "ensure_dir",
    "clean_directory",
    "get_output_path",
]


# ─── Text Output ───

def write_output(content: str, output_path: Path, encoding: str = "utf-8") -> None:
    """
    Write rendered text content to output file.
    Creates parent directories automatically.
    """
    ensure_dir(output_path.parent)

    try:
        output_path.write_text(content, encoding=encoding)
        log.debug(f"Wrote: {output_path}")
    except IOError as e:
        log.error(f"Failed to write {output_path}: {e}")
        raise


def write_binary(data: bytes, output_path: Path) -> None:
    """Write binary content (images, fonts, etc.)."""
    ensure_dir(output_path.parent)
    try:
        output_path.write_bytes(data)
        log.debug(f"Wrote binary: {output_path}")
    except IOError as e:
        log.error(f"Failed to write binary {output_path}: {e}")
        raise


# ─── Directory Utilities ───

def ensure_dir(directory: Path) -> None:
    """Create directory and all parent directories if they don't exist."""
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
        log.debug(f"Created directory: {directory}")


def clean_directory(directory: Path, exclude: List[str] | None = None) -> None:
    """
    Remove all contents of a directory without deleting the directory itself.
    Preserve files/directories in exclude list.
    """
    exclude = exclude or []
    if not directory.exists():
        return

    for item in directory.iterdir():
        if item.name in exclude:
            continue
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        except Exception as e:
            log.warning(f"Could not remove {item}: {e}")

    log.debug(f"Cleaned directory: {directory}")


# ─── Asset Copying ───

def copy_assets(source_dir: Path, target_dir: Path, overwrite: bool = True) -> Dict[str, int]:
    """
    Recursively copy all static assets from source to target.
    Returns statistics: copied, skipped, total.
    """
    stats = {"copied": 0, "skipped": 0, "total": 0}

    if not source_dir.exists():
        log.debug(f"Assets directory not found: {source_dir}")
        return stats

    ensure_dir(target_dir)

    for src_path in source_dir.rglob("*"):
        if not src_path.is_file():
            continue

        stats["total"] += 1
        rel_path = src_path.relative_to(source_dir)
        dest_path = target_dir / rel_path

        # Skip if exists and not forced
        if not overwrite and dest_path.exists():
            stats["skipped"] += 1
            continue

        ensure_dir(dest_path.parent)
        try:
            shutil.copy2(src_path, dest_path)
            stats["copied"] += 1
        except IOError as e:
            log.warning(f"Failed to copy asset {rel_path}: {e}")

    log.debug(f"Assets copied: {stats}")
    return stats


# ─── Path Utilities ───

def get_output_path(
    slug: str,
    base_dir: Path,
    extension: str = ".html",
) -> Path:
    """
    Generate output file path from content slug.
    Example: "about" → base_dir / "about" / "index.html"
    """
    if slug == "index":
        return base_dir / f"index{extension}"
    return base_dir / slug / "index.html"
