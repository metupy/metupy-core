"""
metupy_core.page
~~~~~~~~~~

Page, Layout, Theme, and Component management.
Handles theme loading, layout wrapping, and reusable component rendering.
"""

import re
from pathlib import Path
from typing import Any, Dict, Optional, List, Callable, Type
from dataclasses import dataclass, field

from .logging import log
from .utils import get_ext, slugify
from .renderer import RenderContext


__all__ = [
    "Page",
    "Layout",
    "Theme",
    "Component",
    "ComponentRegistry",
    "LayoutManager",
]


# ═══ Component System ═══

class Component:
    """Base class for all reusable UI components."""
    name: str = ""

    def __init__(self):
        if not self.name:
            self.name = self.__class__.__name__.lower().replace("component", "")

    def render(self, **kwargs: Any) -> str:
        """Render component to HTML — override in subclasses."""
        raise NotImplementedError("Subclasses must implement render()")


class ComponentRegistry:
    """Central registry for all registered components."""

    _components: Dict[str, Type[Component]] = {}
    _instances: Dict[str, Component] = {}

    @classmethod
    def register(cls, name: Optional[str] = None) -> Callable[[Type[Component]], Type[Component]]:
        """Decorator: register a component class."""
        def decorator(component_cls: Type[Component]) -> Type[Component]:
            comp_name = name or component_cls.name or component_cls.__name__.lower()
            cls._components[comp_name] = component_cls
            log.debug(f"Component registered: <{comp_name}>")
            return component_cls
        return decorator

    @classmethod
    def get(cls, name: str) -> Optional[Component]:
        """Get or create component instance by name."""
        if name not in cls._instances:
            comp_cls = cls._components.get(name)
            if not comp_cls:
                return None
            cls._instances[name] = comp_cls()
        return cls._instances[name]

    @classmethod
    def list_all(cls) -> Dict[str, Type[Component]]:
        """Return all registered components."""
        return dict(cls._components)

    @classmethod
    def render(cls, name: str, **kwargs: Any) -> str:
        """Shortcut: get and render component in one call."""
        component = cls.get(name)
        if not component:
            log.warning(f"Component not found: <{name}>")
            return f"<!-- Component not found: {name} -->"
        return component.render(**kwargs)

    @classmethod
    def clear(cls) -> None:
        """Clear all registered components (for reload)."""
        cls._components.clear()
        cls._instances.clear()


# ═══ Layout System ═══

@dataclass
class Layout:
    """Represents a single layout template."""
    name: str
    path: Path
    content: str = field(repr=False)

    def render(self, content: str, context: Dict[str, Any]) -> str:
        """Render layout with content and variable substitution."""
        result = self.content.replace("{{ content }}", content)
        for key, value in context.items():
            result = result.replace(f"{{{{ {key} }}}}", str(value))
        return result


# ═══ Theme System ═══

@dataclass
class Theme:
    """Represents an installed theme with layouts, partials, and assets."""
    name: str
    path: Path
    layouts: Dict[str, Layout] = field(default_factory=dict)
    partials: Dict[str, str] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)

    def get_layout(self, name: str = "page") -> Optional[Layout]:
        """Get layout by name with fallback."""
        return self.layouts.get(name) or self.layouts.get("page")

    def get_partial(self, name: str) -> Optional[str]:
        """Get partial template content by name."""
        return self.partials.get(name)


# ═══ Layout Manager ═══

class LayoutManager:
    """Load and manage themes, layouts, and partials."""

    def __init__(self, theme_dir: Path | str):
        self.theme_dir = Path(theme_dir).resolve()
        self.current_theme: Optional[Theme] = None
        self._cache: Dict[str, str] = {}

    # ─── Theme Loading ───

    def load_theme(self, theme_name: str = "peradocs") -> Theme:
        """Load theme from directory — scans layouts, partials, and config."""
        theme_path = self.theme_dir / theme_name
        if not theme_path.exists():
            log.warning(f"Theme directory not found: {theme_path}")
            return Theme(name=theme_name, path=theme_path)

        layouts_dir = theme_path / "layouts"
        partials_dir = theme_path / "partials"

        # Load layouts
        layouts: Dict[str, Layout] = {}
        if layouts_dir.exists():
            for file in layouts_dir.rglob("*.html"):
                name = file.stem
                layouts[name] = Layout(name=name, path=file, content=file.read_text(encoding="utf-8"))

        # Load partials
        partials: Dict[str, str] = {}
        if partials_dir.exists():
            for file in partials_dir.rglob("*.html"):
                partials[file.stem] = file.read_text(encoding="utf-8")

        # Load theme config (optional)
        config_file = theme_path / "theme.json"
        config: Dict[str, Any] = {}
        if config_file.exists():
            import json
            try:
                config = json.loads(config_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                log.warning(f"Invalid theme.json: {e}")

        self.current_theme = Theme(
            name=theme_name,
            path=theme_path,
            layouts=layouts,
            partials=partials,
            config=config,
        )

        log.info(f"Theme loaded: '{theme_name}' — {len(layouts)} layouts, {len(partials)} partials")
        return self.current_theme

    # ─── Partial Rendering ───

    def render_partial(self, name: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Render a partial template with variable injection."""
        if not self.current_theme:
            return ""
        template = self.current_theme.get_partial(name)
        if not template:
            log.warning(f"Partial not found: {name}")
            return ""
        ctx = context or {}
        result = template
        for key, value in ctx.items():
            result = re.sub(
                r"\{\{\s*" + re.escape(key) + r"\s*\}\}",
                str(value),
                result
            )
        return result

    # ─── Component Tag Processing ───

    def process_component_tags(self, html: str, context: Dict[str, Any]) -> str:
        """Scan and render <x-component /> tags in HTML."""
        pattern = re.compile(r"<x-(\w+)([^>]*?)(?:/>|>(.*?)</x-\1>)", re.DOTALL)

        def render_tag(match: re.Match[str]) -> str:
            comp_name = match.group(1)
            attrs_str = match.group(2)
            inner = match.group(3) or ""

            # Parse attributes
            attrs = {}
            attr_pattern = re.compile(r'(\w+)\s*=\s*["\']([^"\']+)["\']')
            for key, val in attr_pattern.findall(attrs_str):
                attrs[key] = val

            # Merge context + attrs + inner
            kwargs = dict(context)
            kwargs.update(attrs)
            kwargs["children"] = inner

            return ComponentRegistry.render(comp_name, **kwargs)

        return pattern.sub(render_tag, html)

    # ─── Full Page Rendering ───

    def apply_layout(
        self,
        content_html: str,
        layout_name: str,
        context: RenderContext,
        use_components: bool = True,
    ) -> str:
        """Wrap content into layout, process partials and components."""
        if not self.current_theme:
            return content_html

        layout = self.current_theme.get_layout(layout_name)
        if not layout:
            log.warning(f"Layout not found: {layout_name}")
            return content_html

        ctx_dict = context.as_dict()

        # Process components in content
        if use_components:
            content_html = self.process_component_tags(content_html, ctx_dict)

        # Render layout
        result = layout.render(content_html, ctx_dict)

        # Process components in final output
        if use_components:
            result = self.process_component_tags(result, ctx_dict)

        return result

    # ─── Cache Management ───

    def clear_cache(self) -> None:
        """Clear layout cache and component instances."""
        self._cache.clear()
        ComponentRegistry.clear()
        log.debug("Layout and component cache cleared")


# ═══ Page Model ═══

class Page:
    """Represents a single content page with metadata, content, and output path."""

    def __init__(
        self,
        slug: str,
        content: str,
        metadata: Dict[str, Any],
        format: str = "markdown",
    ):
        self.slug = slugify(slug)
        self.title = metadata.get("title", slug.replace("-", " ").title())
        self.content = content
        self.metadata = metadata
        self.format = format
        self.layout = metadata.get("layout", "page")
        self.date = metadata.get("date")
        self.author = metadata.get("author", "")
        self.tags = metadata.get("tags", [])
        self.draft = bool(metadata.get("draft", False))
        self._html: Optional[str] = None

    @property
    def url(self) -> str:
        """Return public URL path for this page."""
        return f"/{self.slug}/" if self.slug != "index" else "/"

    @property
    def is_draft(self) -> bool:
        """Check if page is a draft."""
        return self.draft

    def set_html(self, html: str) -> None:
        """Store rendered HTML."""
        self._html = html

    def get_html(self) -> str:
        """Get cached rendered HTML."""
        return self._html or ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize page to dictionary."""
        return {
            "slug": self.slug,
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "html": self.get_html(),
            "metadata": self.metadata,
            "format": self.format,
            "layout": self.layout,
            "date": self.date,
            "author": self.author,
            "tags": self.tags,
            "draft": self.draft,
        }
