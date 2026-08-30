"""
metupy_core.renderer
~~~~~~~~~~~~~~~

Rendering engine for Metupy content.
Converts parsed content (AST, metadata, raw text) into final HTML.
Supports template injection, variable resolution, and component rendering.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
import re

from .logging import log
from .parsers import ParsedContent
from .signal import emit
from .setting import load_setting


__all__ = [
    "RenderContext",
    "BaseRenderer",
    "PymRenderer",
    "MarkdownRenderer",
    "RestructuredTextRenderer",
    "PythonRenderer",
    "Renderer",
    "render_content",
]


# ─── Render Context ───

class RenderContext:
    """Safe execution context for template rendering."""

    def __init__(
        self,
        metadata: Dict[str, Any],
        global_vars: Optional[Dict[str, Any]] = None,
        helpers: Optional[Dict[str, Any]] = None,
    ):
        self._metadata = dict(metadata)
        self._global_vars = global_vars or {}
        self._helpers = helpers or {}
        self._builtins = {
            "now": datetime.now,
            "str": str,
            "int": int,
            "float": float,
            "len": len,
            "enumerate": enumerate,
            "zip": zip,
            "True": True,
            "False": False,
            "None": None,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from context: metadata → global_vars → helpers → builtins."""
        if key in self._metadata:
            return self._metadata[key]
        if key in self._global_vars:
            return self._global_vars[key]
        if key in self._helpers:
            return self._helpers[key]
        if key in self._builtins:
            return self._builtins[key]
        return default

    def set(self, key: str, value: Any) -> None:
        """Set/update value in context."""
        self._metadata[key] = value

    def update(self, **kwargs: Any) -> None:
        """Update context with additional variables."""
        self._metadata.update(kwargs)

    def as_dict(self) -> Dict[str, Any]:
        """Flatten all context layers into a single dictionary."""
        result = dict(self._builtins)
        result.update(self._helpers)
        result.update(self._global_vars)
        result.update(self._metadata)
        return result


# ─── Safe Expression Evaluator ───

_SAFE_EXPR_PATTERN = re.compile(r"^[a-zA-Z0-9_ \t\[\]()\"'.,:+\-*/%<>=!&|^~]+$")
_DANGEROUS_TOKENS = {"import", "exec", "eval", "open", "globals", "locals", "os", "sys", "__"}

def _safe_eval(expression: str, context: Dict[str, Any]) -> Any:
    """Evaluate expression safely with restricted environment."""
    expr = expression.strip()
    if not expr:
        return True

    if not _SAFE_EXPR_PATTERN.match(expr):
        log.warning(f"Unsafe expression rejected: {expr}")
        return False

    for token in _DANGEROUS_TOKENS:
        if token in expr:
            log.warning(f"Dangerous token blocked: {token}")
            return False

    try:
        return eval(expr, {"__builtins__": {}}, context)
    except NameError:
        return False
    except Exception as e:
        log.debug(f"Expression evaluation failed: {e}")
        return False


# ─── Value Parser for Direct Assignment ───

def _parse_raw_value(raw: Any, context: Dict[str, Any]) -> Any:
    """Parse raw value from assignment: evaluate expressions, keep literals."""
    if not isinstance(raw, str):
        return raw
    raw = raw.strip()
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    if raw.lower() in ("none", "null"):
        return None
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        pass
    if _SAFE_EXPR_PATTERN.match(raw) and not any(tok in raw for tok in _DANGEROUS_TOKENS):
        try:
            return eval(raw, {"__builtins__": {}}, context)
        except Exception:
            pass
    return raw


# ─── Base Renderer ───

class BaseRenderer:
    """Abstract base class for all format-specific renderers."""

    format_name: str = "base"

    def __init__(
        self,
        template_dir: Optional[Path] = None,
        global_vars: Optional[Dict[str, Any]] = None,
    ):
        if template_dir is None:
            try:
                settings = load_settings()
                self.template_dir = Path(settings.theme_dir).resolve() / "templates"
            except Exception:
                self.template_dir = Path.cwd() / "themes" / "peradocs" / "templates"
        else:
            self.template_dir = Path(template_dir).resolve()

        self.global_vars = global_vars or {}
        self._template_cache: Dict[str, str] = {}

    def render(
        self,
        content: ParsedContent,
        context: Optional[RenderContext] = None,
        template: Optional[str] = None,
    ) -> str:
        """Render parsed content to HTML. Must be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement render()")

    def _load_template(self, template_name: str) -> Optional[str]:
        """Load template file from template directory with caching."""
        if template_name in self._template_cache:
            return self._template_cache[template_name]

        template_path = self.template_dir / template_name
        if not template_path.exists():
            log.warning(f"Template not found: {template_path}")
            return None

        try:
            template = template_path.read_text(encoding="utf-8")
            self._template_cache[template_name] = template
            return template
        except IOError as e:
            log.error(f"Cannot read template {template_name}: {e}")
            return None

    def _apply_template(self, content_html: str, template: str, context: RenderContext) -> str:
        """Inject rendered content into template, replacing {{ content }}."""
        ctx = context.as_dict()
        result = template.replace("{{ content }}", content_html)

        def replace_var(match: re.Match[str]) -> str:
            var_name = match.group(1).strip()
            value = ctx.get(var_name, f"{{{{ {var_name} }}}}")
            return str(value)

        result = re.sub(r"{{\s*([^}]+)\s*}}", replace_var, result)
        return result


# ─── .pym Renderer ───

class PymRenderer(BaseRenderer):
    """Renderer for native .pym format."""

    format_name = "pym"

    def render(
        self,
        content: ParsedContent,
        context: Optional[RenderContext] = None,
        template: Optional[str] = None,
    ) -> str:
        """Render .pym AST to HTML."""
        ctx = context or RenderContext(content.metadata, self.global_vars)
        ast = content.ast

        emit("before_render", content=content, context=ctx, format="pym")

        if not ast or "content" not in ast:
            html = content.content
        else:
            html = self._render_ast_nodes(ast["content"], ctx)

        if not template:
            template = content.metadata.get("template", "page.html")

        template_str = self._load_template(template)
        if template_str:
            html = self._apply_template(html, template_str, ctx)

        emit("after_render", content=content, result=html, format="pym")
        return html

    def _render_ast_nodes(self, nodes: List[Dict[str, Any]], ctx: RenderContext) -> str:
        """Recursively render AST nodes to HTML."""
        parts: List[str] = []
        ctx_dict = ctx.as_dict()

        for node in nodes:
            node_type = node.get("type")

            if node_type == "text":
                parts.append(node.get("value", ""))

            elif node_type == "variable":
                var_name = node.get("name", "").strip()
                value = ctx.get(var_name, f"{{{{ {var_name} }}}}")
                parts.append(str(value))

            elif node_type in ("set_variable", "direct_assignment"):
                var_name = node.get("name", "").strip()
                raw_value = node.get("value")
                final_value = _parse_raw_value(raw_value, ctx_dict)
                ctx.set(var_name, final_value)
                ctx_dict = ctx.as_dict()

            elif node_type == "for_loop":
                expr = node.get("expression", "")
                body = node.get("body", [])
                parts.append(self._render_for_loop(expr, body, ctx))

            elif node_type == "conditional":
                branches = node.get("branches", [])
                parts.append(self._render_conditional(branches, ctx))

            elif node_type == "component":
                parts.append(self._render_component(node, ctx))

        return "".join(parts)

    def _render_for_loop(self, expr: str, body: List[Dict[str, Any]], ctx: RenderContext) -> str:
        """Render for-loop block."""
        try:
            if " in " not in expr:
                return f"<!-- Invalid for loop: {expr} -->"
            var_name, iter_name = expr.split(" in ", 1)
            var_name = var_name.strip()
            iter_name = iter_name.strip()

            iterable = ctx.get(iter_name, [])
            if not hasattr(iterable, "__iter__") or isinstance(iterable, (str, bytes)):
                return f"<!-- Not iterable: {iter_name} -->"

            result: List[str] = []
            for item in iterable:
                ctx.set(var_name, item)
                result.append(self._render_ast_nodes(body, ctx))
            return "".join(result)
        except Exception as e:
            log.error(f"For loop render error: {e}")
            return f"<!-- Loop Error: {e} -->"

    def _render_conditional(self, branches: List[Dict[str, Any]], ctx: RenderContext) -> str:
        """Render if/elif/else conditional."""
        ctx_dict = ctx.as_dict()
        for branch in branches:
            branch_type = branch.get("type")
            body = branch.get("body", [])

            if branch_type == "else":
                return self._render_ast_nodes(body, ctx)

            condition = branch.get("condition", "").strip()
            if _safe_eval(condition, ctx_dict):
                return self._render_ast_nodes(body, ctx)
        return ""

    def _render_component(self, node: Dict[str, Any], ctx: RenderContext) -> str:
        """Render custom component."""
        name = node.get("name", "")
        attrs = node.get("attrs", {})
        body = node.get("body", [])
        body_html = self._render_ast_nodes(body, ctx)

        attr_str = " ".join(f'{k}="{v}"' for k, v in attrs.items())
        if attr_str:
            attr_str = " " + attr_str

        return f"<{name}{attr_str}>{body_html}</{name}>"


# ─── Markdown Renderer ───

class MarkdownRenderer(BaseRenderer):
    """Renderer for Markdown content."""

    format_name = "markdown"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._md_available = self._check_markdown()

    def _check_markdown(self) -> bool:
        """Check if markdown library is installed."""
        try:
            import markdown  # noqa: F401
            return True
        except ImportError:
            log.warning("markdown library not installed. Install with: pip install markdown")
            return False

    def render(
        self,
        content: ParsedContent,
        context: Optional[RenderContext] = None,
        template: Optional[str] = None,
    ) -> str:
        """Render Markdown to HTML."""
        ctx = context or RenderContext(content.metadata, self.global_vars)

        emit("before_render", content=content, context=ctx, format="markdown")

        if not template:
            template = content.metadata.get("template", "page.html")

        if not self._md_available:
            html = f"<pre>{content.content}</pre>"
        else:
            import markdown
            html = markdown.markdown(
                content.content,
                extensions=["fenced_code", "tables", "toc"],
            )

        template_str = self._load_template(template)
        if template_str:
            html = self._apply_template(html, template_str, ctx)

        emit("after_render", content=content, result=html, format="markdown")
        return html


# ─── reStructuredText Renderer ───

class RestructuredTextRenderer(BaseRenderer):
    """Renderer for reStructuredText content."""

    format_name = "restructuredtext"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._rst_available = self._check_docutils()

    def _check_docutils(self) -> bool:
        """Check if docutils is installed."""
        try:
            from docutils.core import publish_string  # noqa: F401
            return True
        except ImportError:
            log.warning("docutils not installed. Install with: pip install docutils")
            return False

    def render(
        self,
        content: ParsedContent,
        context: Optional[RenderContext] = None,
        template: Optional[str] = None,
    ) -> str:
        """Render reStructuredText to HTML."""
        ctx = context or RenderContext(content.metadata, self.global_vars)

        emit("before_render", content=content, context=ctx, format="rst")

        if not template:
            template = content.metadata.get("template", "page.html")

        if not self._rst_available:
            html = f"<pre>{content.content}</pre>"
        else:
            from docutils.core import publish_string
            html = publish_string(
                content.content,
                writer_name="html",
                settings_overrides={"halt_level": 2},
            ).decode("utf-8")

        template_str = self._load_template(template)
        if template_str:
            html = self._apply_template(html, template_str, ctx)

        emit("after_render", content=content, result=html, format="rst")
        return html


# ─── Python File Renderer ───

class PythonRenderer(BaseRenderer):
    """Renderer for Python (.py) content files."""

    format_name = "python"

    def render(
        self,
        content: ParsedContent,
        context: Optional[RenderContext] = None,
        template: Optional[str] = None,
    ) -> str:
        """Render Python file docstring as HTML."""
        ctx = context or RenderContext(content.metadata, self.global_vars)

        emit("before_render", content=content, context=ctx, format="python")

        if not template:
            template = content.metadata.get("template", "page.html")

        docstring = content.content or ""
        html = f"<div class='python-content'><pre>{docstring}</pre></div>"

        template_str = self._load_template(template)
        if template_str:
            html = self._apply_template(html, template_str, ctx)

        emit("after_render", content=content, result=html, format="python")
        return html


# ─── Unified Renderer ───

class Renderer:
    """Unified renderer that automatically selects the appropriate renderer."""

    _renderer_map: Dict[str, type[BaseRenderer]] = {
        "pym": PymRenderer,
        "markdown": MarkdownRenderer,
        "restructuredtext": RestructuredTextRenderer,
        "python": PythonRenderer,
    }

    def __init__(
        self,
        template_dir: Optional[Path] = None,
        global_vars: Optional[Dict[str, Any]] = None,
    ):
        self.template_dir = template_dir
        self.global_vars = global_vars or {}
        self._renderers: Dict[str, BaseRenderer] = {}

    def _get_renderer(self, format_name: str) -> Optional[BaseRenderer]:
        """Get or create renderer for given format."""
        if format_name in self._renderers:
            return self._renderers[format_name]

        renderer_cls = self._renderer_map.get(format_name)
        if not renderer_cls:
            log.warning(f"No renderer available for format: {format_name}")
            return None

        renderer = renderer_cls(
            template_dir=self.template_dir,
            global_vars=self.global_vars,
        )
        self._renderers[format_name] = renderer
        return renderer

    def render(
        self,
        content: ParsedContent,
        context: Optional[RenderContext] = None,
        template: Optional[str] = None,
    ) -> str:
        """Auto-detect format and render to HTML."""
        renderer = self._get_renderer(content.format)
        if not renderer:
            return f"<pre>{content.content}</pre>"

        return renderer.render(content, context=context, template=template)

    def clear_cache(self) -> None:
        """Clear template cache for all renderers."""
        for renderer in self._renderers.values():
            renderer._template_cache.clear()
        log.debug("Renderer template cache cleared")


# ─── Convenience Function ───

def render_content(
    content: ParsedContent,
    template: Optional[str] = None,
    template_dir: Optional[Path] = None,
    global_vars: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """Convenience function: render content in one call."""
    renderer = Renderer(template_dir=template_dir, global_vars=global_vars)
    ctx = RenderContext(content.metadata, global_vars, context)
    return renderer.render(content, context=ctx, template=template)
