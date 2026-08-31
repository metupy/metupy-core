"""
metupy_core.reader
~~~~~~~~~~~~~~

File reading and content loading utilities.
Handles different source formats, encoding detection,
and delegates parsing to the appropriate format-specific parser.

Supported extensions: .pym, .py, .md, .rst

Usage:
    from metupy_core.readers import read_and_parse

    result = read_and_parse("content/index.pym")
    print(result.metadata, result.content)
"""

from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import chardet

from .logging import log
from .parsers import (
    BaseParser,
    get_parser_for_file,
    ParsedContent,
)


__all__ = [
    "FileReader",
    "read_file",
    "read_and_parse",
    "detect_format",
    "normalize_content",
    "is_supported",
    "SUPPORTED_EXTENSIONS",
]


# ─── Constants ───

SUPPORTED_EXTENSIONS = {
    ".pym": "metupy",
    ".py": "python",
    ".md": "markdown",
    ".rst": "restructuredtext",
}

DEFAULT_ENCODING = "utf-8"
FALLBACK_ENCODINGS = ["utf-8-sig", "latin-1", "cp1252", "utf-16"]


# ─── File Reader Class ───

class FileReader:
    """
    Reads and normalizes content files with encoding detection.
    Delegates format-specific parsing to registered parsers.
    """

    def __init__(
        self,
        encoding: Optional[str] = None,
        detect_encoding: bool = True,
        source_dir: Path | None = None,
    ):
        self.encoding = encoding or DEFAULT_ENCODING
        self.detect_encoding = detect_encoding
        self.source_dir = source_dir or Path.cwd().resolve()

    # ─── Read Only ───

    def read(self, file_path: Path | str) -> Tuple[str, Dict[str, Any]]:
        """
        Read raw file content without parsing.
        Detects encoding automatically unless specified otherwise.
        """
        file_path = Path(file_path).resolve()

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not file_path.is_file():
            raise IsADirectoryError(f"Not a file: {file_path}")

        encoding = self._detect_encoding(file_path) if self.detect_encoding else self.encoding

        try:
            raw_content = file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            log.warning(f"Failed to decode with {encoding}, trying fallback encodings...")
            raw_content = self._read_with_fallback(file_path)

        metadata = {
            "path": str(file_path),
            "name": file_path.name,
            "stem": file_path.stem,
            "suffix": file_path.suffix.lower(),
            "format": detect_format(file_path),
            "encoding": encoding,
            "size_bytes": file_path.stat().st_size,
            "modified_at": file_path.stat().st_mtime,
        }

        log.debug(f"Read file: {file_path.name} ({encoding}, {metadata['size_bytes']} bytes)")
        return normalize_content(raw_content), metadata

    # ─── Read + Parse ───

    def read_and_parse(self, file_path: Path | str) -> ParsedContent:
        """
        Read file AND parse it using the appropriate parser.
        This is the primary entry point for content processing.
        """
        file_path = Path(file_path).resolve()
        content, meta = self.read(file_path)

        parser_cls = get_parser_for_file(file_path)
        if not parser_cls:
            log.warning(f"No parser available for: {file_path.suffix}")
            return ParsedContent(
                has_errors=True,
                error_message=f"Unsupported format: {file_path.suffix}",
                format=meta["format"],
            )

        parser: BaseParser = parser_cls(source_dir=self.source_dir)
        result = parser.parse(content)
        result.raw_content = content
        return result

    # ─── Encoding Handling ───

    def _detect_encoding(self, file_path: Path) -> str:
        """Detect file encoding using chardet library."""
        try:
            raw_bytes = file_path.read_bytes()
            if not raw_bytes:
                return DEFAULT_ENCODING

            detection_result = chardet.detect(raw_bytes)
            encoding = detection_result.get("encoding") or DEFAULT_ENCODING
            confidence = detection_result.get("confidence", 0.0)

            encoding = encoding.lower().replace("-", "")
            encoding_map = {
                "utf8": "utf-8",
                "utf8sig": "utf-8-sig",
                "windows1252": "cp1252",
                "iso88591": "latin-1",
            }
            encoding = encoding_map.get(encoding, encoding)

            if confidence < 0.7:
                log.debug(f"Low encoding confidence ({confidence:.2f}) for {file_path.name}, using {encoding}")

            return encoding

        except ImportError:
            log.debug("chardet not available, using default UTF-8")
            return DEFAULT_ENCODING

    def _read_with_fallback(self, file_path: Path) -> str:
        """Try reading with different encodings until success."""
        for enc in FALLBACK_ENCODINGS:
            try:
                return file_path.read_text(encoding=enc)
            except UnicodeDecodeError:
                continue

        log.warning(f"All encodings failed for {file_path.name}, using lossy decode")
        return file_path.read_text(encoding=DEFAULT_ENCODING, errors="replace")


# ─── Format Detection ───

def detect_format(file_path: Path | str) -> str:
    """Detect content format from file extension."""
    file_path = Path(file_path)
    ext = file_path.suffix.lower()
    return SUPPORTED_EXTENSIONS.get(ext, "unknown")


def is_supported(file_path: Path | str) -> bool:
    """Check if file format is supported and has a parser."""
    return detect_format(file_path) != "unknown"


# ─── Content Normalization ───

def normalize_content(content: str) -> str:
    """Normalize raw content before parsing."""
    if content.startswith("\ufeff"):
        content = content[1:]
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    content = "\n".join(line.rstrip() for line in content.split("\n"))
    if not content.endswith("\n"):
        content += "\n"
    return content


# ─── Convenience Functions ───

def read_file(
    file_path: Path | str,
    encoding: Optional[str] = None,
    detect_encoding: bool = True,
) -> Tuple[str, Dict[str, Any]]:
    """Read file content without parsing."""
    reader = FileReader(encoding=encoding, detect_encoding=detect_encoding)
    return reader.read(file_path)


def read_and_parse(
    file_path: Path | str,
    source_dir: Path | None = None,
    encoding: Optional[str] = None,
) -> ParsedContent:
    """Read AND parse file in one call — recommended entry point."""
    reader = FileReader(source_dir=source_dir, encoding=encoding)
    return reader.read_and_parse(file_path)


def read_raw(file_path: Path | str) -> bytes:
    """Read file as raw bytes without decoding."""
    return Path(file_path).read_bytes()


def read_text(
    file_path: Path | str,
    encoding: str = DEFAULT_ENCODING,
) -> str:
    """Simple read text file with specified encoding."""
    return Path(file_path).read_text(encoding=encoding)
