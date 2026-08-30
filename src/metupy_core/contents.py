"""
metupy_core.contents
~~~~~~~~~~~~~~~

Content discovery and management with theme-aware configuration.
Scans content directory based on active theme's structure.
Supports flexible paths, category rules, and incremental builds.

Default theme: peradocs — inspired by Ampera, Palembang.

Usage:
    from metupy.contents import ContentManager

    manager = ContentManager(theme="peradocs")
    pages = manager.discover()
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from .logging import log
from .parsers import parse_file, ParsedContent, get_parser_for_file
from .cache import FileCache
from .signal import emit


__all__ = [
    "ContentFile",
    "ThemeConfig",
    "ContentManager",
    "discover_contents",
]


# ─── Data Structures ───

@dataclass
class ContentFile:
    """Represents a single content file with parsed metadata and content."""
    path: Path
    rel_path: str
    slug: str
    category: str = "default"
    metadata: Dict[str, Any] = field(default_factory=dict)
    content: str = ""
    ast: Optional[Dict[str, Any]] = None
    format: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    is_draft: bool = False
    is_published: bool = True
    errors: Optional[str] = None

    @property
    def output_path(self) -> str:
        """Relative output path for the generated HTML file."""
        if self.slug == "index":
            return "index.html"
        return f"{self.slug}/index.html"

    @property
    def is_page(self) -> bool:
        """Top-level page (root category)."""
        return self.category in ("pages", "root") and "/" not in self.slug

    @property
    def is_post(self) -> bool:
        """Blog post or categorized content."""
        return self.category == "posts" or "/" in self.slug


@dataclass
class ThemeConfig:
    """Defines content structure rules for a specific theme."""
    name: str
    contents_dir: str = "contents"
    categories: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    exclude_dirs: Set[str] = field(
        default_factory=lambda: {"_templates", "_drafts", ".git", "__pycache__", "assets"}
    )
    exclude_files: Set[str] = field(
        default_factory=lambda: {"README.md", ".gitkeep", "LICENSE"}
    )
    index_names: Set[str] = field(default_factory=lambda: {"index", "index_page"})
    sort_by: str = "date"  # "date" | "title" | "path"

    @classmethod
    def for_theme(cls, name: str, custom: Optional[Dict[str, Any]] = None) -> "ThemeConfig":
        """
        Create theme config with preset structure.
        Default theme: peradocs — inspired by Ampera, Palembang.
        """
        presets = {
            "peradocs": {
                "contents_dir": "contents",
                "categories": {
                    "pages": {
                        "path": "",
                        "exclude": ["docs/**", "posts/**", "blog/**"],
                        "sort": "title",
                    },
                    "docs": {
                        "path": "docs",
                        "sort": "path",
                    },
                    "posts": {
                        "path": "posts",
                        "sort": "date",
                        "reverse": True,
                    },
                    "blog": {
                        "path": "blog",
                        "sort": "date",
                        "reverse": True,
                    },
                    "drafts": {
                        "path": "drafts",
                        "draft": True,
                    },
                },
                "exclude_dirs": {"_templates", "assets", "public", ".git", "__pycache__"},
                "sort_by": "path",
            },

            "blog": {
                "contents_dir": "content",
                "categories": {
                    "pages": {"path": "", "exclude": ["posts/**"]},
                    "posts": {"path": "posts", "sort": "date", "reverse": True},
                    "drafts": {"path": "drafts", "draft": True},
                },
            },

            "docs": {
                "contents_dir": "docs",
                "categories": {
                    "docs": {"path": "", "sort": "path"},
                    "api": {"path": "api", "sort": "title"},
                },
                "sort_by": "path",
            },

            "portfolio": {
                "contents_dir": "projects",
                "categories": {
                    "projects": {"path": "", "sort": "date", "reverse": True},
                    "pages": {"path": "pages"},
                },
            },
        }

        base_config = presets.get(name, presets["peradocs"])
        if custom:
            base_config.update(custom)

        return cls(name=name, **base_config)


# ─── Content Manager ───

class ContentManager:
    """
    Theme-aware content discovery engine.
    Adapts scanning rules, categories, and structure based on selected theme.
    Default theme: peradocs.
    """

    def __init__(
        self,
        source_dir: Path | None = None,
        theme: str = "peradocs",
        theme_config: Optional[ThemeConfig] = None,
        custom_config: Optional[Dict[str, Any]] = None,
        cache_dir: Path | str | None = None,
    ):
        self.source_dir = Path(source_dir or Path.cwd()).resolve()
        self.theme = theme
        self.config = theme_config or ThemeConfig.for_theme(theme, custom_config)

        self.contents_dir = self.source_dir / self.config.contents_dir
        self.cache = FileCache(cache_dir or self.source_dir / ".metupy" / "cache")

        self._files: List[ContentFile] = []
        self._discovered = False

        log.debug(
            f"ContentManager initialized — "
            f"theme: '{self.theme}', source: {self.contents_dir}"
        )

    # ─── Main Discovery ───

    def discover(self, force_rebuild: bool = False) -> List[ContentFile]:
        """
        Scan contents directory following theme rules.
        Applies category detection, exclusions, and caching.
        """
        self._files.clear()
        self._discovered = False

        if not self.contents_dir.exists():
            log.warning(f"Contents directory not found: {self.contents_dir}")
            return []

        log.info(f"Scanning contents (theme: {self.theme}): {self.contents_dir}")
        self.cache.load()

        file_count = 0
        for file_path in self._iter_content_files():
            file_count += 1
            content_file = self._process_file(file_path, force_rebuild)
            if content_file:
                self._files.append(content_file)

        self._apply_sorting()

        self.cache.save()
        self._discovered = True

        log.info(f"Discovered {len(self._files)} content file(s) from {file_count} total")
        emit("after_discover", files=self._files, total=file_count, theme=self.theme)
        return self._files

    # ─── File Iteration & Filtering ───

    def _iter_content_files(self) -> List[Path]:
        """Iterate files, applying theme's exclude rules and parser check."""
        files = []
        for path in self.contents_dir.rglob("*"):
            if not path.is_file():
                continue

            if any(part in self.config.exclude_dirs for part in path.parts):
                continue

            if path.name in self.config.exclude_files:
                continue

            if not get_parser_for_file(path):
                continue

            files.append(path)

        files.sort(
            key=lambda p: (
                0 if p.stem in self.config.index_names else 1,
                str(p)
            )
        )
        return files

    # ─── File Processing ───

    def _process_file(self, file_path: Path, force_rebuild: bool) -> Optional[ContentFile]:
        """Parse and categorize a single content file."""
        rel_path = file_path.relative_to(self.contents_dir)
        slug = self._path_to_slug(rel_path)
        category = self._detect_category(rel_path)

        if not force_rebuild and not self.cache.is_changed(file_path):
            log.debug(f"Using cached: {rel_path}")
            return self._build_cached_file(file_path, rel_path, slug, category)

        emit("file_processing", path=file_path, rel_path=rel_path, category=category)
        parsed = parse_file(file_path, self.source_dir)

        if parsed.has_errors:
            log.error(f"Parse failed: {rel_path} — {parsed.error_message}")
            emit("file_failed", path=file_path, error=parsed.error_message)
            return ContentFile(
                path=file_path,
                rel_path=str(rel_path),
                slug=slug,
                category=category,
                errors=parsed.error_message or "Unknown error",
            )

        content_file = ContentFile(
            path=file_path,
            rel_path=str(rel_path),
            slug=slug,
            category=category,
            metadata=parsed.metadata,
            content=parsed.content,
            ast=parsed.ast,
            format=parsed.format,
            updated_at=datetime.fromtimestamp(file_path.stat().st_mtime),
        )

        # Draft detection from metadata or category rules
        content_file.is_draft = (
            content_file.metadata.get("draft", False)
            or content_file.metadata.get("published", True) is False
        )
        content_file.is_published = not content_file.is_draft

        cat_config = self.config.categories.get(category, {})
        if cat_config.get("draft", False):
            content_file.is_draft = True
            content_file.is_published = False

        self.cache.update(file_path)
        emit("file_processed", path=file_path, content_file=content_file)
        log.debug(f"Parsed [{category}]: {rel_path}")
        return content_file

    # ─── Path & Category Logic ───

    def _path_to_slug(self, rel_path: Path) -> str:
        """Convert relative path to URL slug, respecting theme's index rules."""
        path_no_ext = rel_path.with_suffix("")
        slug = str(path_no_ext).replace("\\", "/")

        for index_name in self.config.index_names:
            if slug.endswith(f"/{index_name}"):
                slug = slug[: -(len(index_name) + 1)]
                break
            if slug == index_name:
                slug = "index"
                break

        return slug

    def _detect_category(self, rel_path: Path) -> str:
        """Determine file's category based on theme config and path."""
        rel_str = str(rel_path).replace("\\", "/")

        for cat_name, cat_config in self.config.categories.items():
            cat_path = cat_config.get("path", "")
            if not cat_path:
                continue
            if rel_str.startswith(cat_path + "/") or rel_str == cat_path:
                return cat_name

        for cat_name, cat_config in self.config.categories.items():
            if not cat_config.get("path", ""):
                return cat_name

        return "default"

    def _build_cached_file(self, file_path: Path, rel_path: str, slug: str, category: str) -> ContentFile:
        """Create ContentFile from cached metadata."""
        stat = file_path.stat()
        return ContentFile(
            path=file_path,
            rel_path=rel_path,
            slug=slug,
            category=category,
            updated_at=datetime.fromtimestamp(stat.st_mtime),
        )

    # ─── Sorting ───

    def _apply_sorting(self) -> None:
        """Apply theme-defined sorting per category."""
        for cat_name in self.config.categories:
            cat_files = [f for f in self._files if f.category == cat_name]
            if not cat_files:
                continue

            cat_config = self.config.categories.get(cat_name, {})
            cat_sort = cat_config.get("sort", self.config.sort_by)
            reverse = cat_config.get("reverse", False)

            if cat_sort == "date":
                cat_files.sort(
                    key=lambda f: f.metadata.get("date", f.updated_at),
                    reverse=reverse,
                )
            elif cat_sort == "title":
                cat_files.sort(
                    key=lambda f: f.metadata.get("title", f.slug).lower(),
                    reverse=reverse,
                )
            elif cat_sort == "path":
                cat_files.sort(key=lambda f: f.rel_path, reverse=reverse)

        self._files.sort(key=lambda f: (f.category, f.slug))

    # ─── Query Methods ───

    def get_all(self, include_drafts: bool = False) -> List[ContentFile]:
        """Return all content files, optionally excluding drafts."""
        if not self._discovered:
            self.discover()
        files = self._files
        if not include_drafts:
            files = [f for f in files if f.is_published]
        return files

    def get_categories(self, include_drafts: bool = False) -> Dict[str, List[ContentFile]]:
        """Group files by category defined in theme config."""
        result: Dict[str, List[ContentFile]] = {}
        for f in self.get_all(include_drafts=include_drafts):
            result.setdefault(f.category, []).append(f)
        return result

    def get_by_category(self, category: str, include_drafts: bool = False) -> List[ContentFile]:
        """Get all files in a specific category."""
        return [
            f for f in self.get_all(include_drafts=include_drafts)
            if f.category == category
        ]

    def get_pages(self, include_drafts: bool = False) -> List[ContentFile]:
        """Get top-level pages."""
        return self.get_by_category("pages", include_drafts)

    def get_posts(self, include_drafts: bool = False) -> List[ContentFile]:
        """Get posts/blog content."""
        return self.get_by_category("posts", include_drafts)

    def get_docs(self, include_drafts: bool = False) -> List[ContentFile]:
        """Get documentation content (peradocs theme)."""
        return self.get_by_category("docs", include_drafts)

    def get_by_slug(self, slug: str) -> Optional[ContentFile]:
        """Find file by its slug."""
        for f in self.get_all():
            if f.slug == slug:
                return f
        return None

    def get_template_files(self) -> List[Path]:
        """Collect template files from theme's template directory."""
        templates_dir = self.contents_dir / "_templates"
        if not templates_dir.exists():
            return []
        return list(templates_dir.rglob("*.html")) + list(templates_dir.rglob("*.pym"))


# ─── Convenience Function ───

def discover_contents(
    theme: str = "peradocs",
    contents_dir: Path | str | None = None,
    source_dir: Path | None = None,
    theme_config: Optional[ThemeConfig] = None,
    custom_config: Optional[Dict[str, Any]] = None,
    force_rebuild: bool = False,
) -> List[ContentFile]:
    """Quickly discover contents with specified theme — defaults to peradocs."""
    manager = ContentManager(
        source_dir=source_dir,
        theme=theme,
        theme_config=theme_config,
        custom_config=custom_config,
    )
    if contents_dir:
        manager.contents_dir = Path(contents_dir).resolve()
    return manager.discover(force_rebuild=force_rebuild)
