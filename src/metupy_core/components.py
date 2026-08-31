"""
metupy_core.components
~~~~~~~~~~~~~~~~~

Component system following shadcn/ui pattern:
- Built-in components available by default
- User can copy component template to local ./components/ folder
- Once present in project folder, USER version takes full precedence
- Edit directly in components/ — no decorator, no registration needed

Workflow:
  1. Use <Button /> in .pym → uses built-in component
  2. Run `pym add Button` → copies template to ./components/Button.py
  3. Edit components/Button.py → changes apply automatically on next build
  4. Delete the file → falls back to built-in component
"""

import importlib.util
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from dataclasses import dataclass

from .logging import log


__all__ = [
    "ComponentInfo",
    "ComponentLoader",
    "get_loader",
    "render_component",
    "get_component",
    "list_components",
    "copy_builtin_component",
]


@dataclass
class ComponentInfo:
    """Metadata about a component including its source."""
    name: str
    source: str  # 'builtin' | 'user'
    file_path: Optional[Path]
    render_func: Callable


class ComponentLoader:
    """
    Manages component loading with priority rules.
    User-defined components in ./components/ always take precedence.
    """

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = Path(project_dir or Path.cwd()).resolve()
        self.user_components_dir = self.project_dir / "components"
        self._builtin_cache: Dict[str, Callable] = {}
        self._user_cache: Dict[str, Callable] = {}
        self._scanned = False

    # ─── User Components Loading ───

    def scan_user_components(self) -> int:
        """Scan components directory and load all user-defined components."""
        self._user_cache.clear()

        if not self.user_components_dir.exists():
            log.debug("User components directory not found — using built-ins only")
            return 0

        count = 0
        for file in self.user_components_dir.glob("*.py"):
            if self._load_user_component(file):
                count += 1

        self._scanned = True
        log.debug(f"Loaded {count} user component(s)")
        return count

    def _load_user_component(self, file_path: Path) -> bool:
        """Load a single component from user's components directory."""
        name = file_path.stem

        try:
            spec = importlib.util.spec_from_file_location(f"components.{name}", file_path)
            if not spec or not spec.loader:
                log.warning(f"Cannot load component file: {file_path.name}")
                return False

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, "render") and callable(module.render):
                self._user_cache[name] = module.render
                log.debug(f"User component loaded: <{name}>")
                return True

            log.warning(f"Component <{name}> has no render() function")
            return False

        except Exception as e:
            log.error(f"Failed to load component <{name}>: {e}")
            return False

    # ─── Component Retrieval & Rendering ───

    def get(self, name: str) -> Optional[Callable]:
        """
        Get component render function by name.
        User-defined components always take precedence over built-ins.
        """
        if name in self._user_cache:
            return self._user_cache[name]
        return self._builtin_cache.get(name)

    def get_info(self, name: str) -> Optional[ComponentInfo]:
        """Get full component information including source and file path."""
        if name in self._user_cache:
            return ComponentInfo(
                name=name,
                source="user",
                file_path=self.user_components_dir / f"{name}.py",
                render_func=self._user_cache[name],
            )

        builtin = self._builtin_cache.get(name)
        if builtin:
            return ComponentInfo(
                name=name,
                source="builtin",
                file_path=None,
                render_func=builtin,
            )

        return None

    def render(self, name: str, attrs: Dict[str, Any], children: Any = None) -> str:
        """
        Render a component with given attributes and children.
        Converts kebab-case attributes to snake_case automatically.
        """
        if not self._scanned:
            self.scan_user_components()

        info = self.get_info(name)
        if not info:
            log.warning(f"Component <{name}> not found")
            return f"<!-- Component not found: {name} -->"

        try:
            kwargs = dict(attrs)

            if children is not None:
                kwargs["children"] = children
                kwargs["content"] = children

            # Normalize kebab-case to snake_case
            normalized = {}
            for key, value in kwargs.items():
                normalized[key.replace("-", "_")] = value

            result = info.render_func(**normalized)
            return str(result)

        except Exception as e:
            log.error(f"Error rendering <{name}> [{info.source}]: {e}")
            return f"<!-- Error rendering {name}: {e} -->"

    # ─── Built-in Component Registration ───

    def register_builtin(self, name: str, func: Callable) -> None:
        """Register a built-in component provided by Metupy core."""
        self._builtin_cache[name] = func
        log.debug(f"Built-in component registered: <{name}>")

    def list_all(self) -> Dict[str, Dict[str, Any]]:
        """List all available components with their source information."""
        if not self._scanned:
            self.scan_user_components()

        result = {}
        all_names = set(self._user_cache.keys()) | set(self._builtin_cache.keys())

        for name in all_names:
            info = self.get_info(name)
            if info:
                result[name] = {
                    "source": info.source,
                    "file": str(info.file_path) if info.file_path else None,
                }

        return result

    # ─── CLI: Copy Built-in to User Project ───

    def copy_to_user(self, name: str) -> Tuple[bool, str]:
        """
        Copy built-in component template to user's components directory.
        Similar to `shadcn-ui add`.
        """
        if name not in self._builtin_cache:
            return False, f"Built-in component <{name}> does not exist"

        self.user_components_dir.mkdir(parents=True, exist_ok=True)
        target_file = self.user_components_dir / f"{name}.py"

        if target_file.exists():
            return False, f"Component file already exists: {target_file}"

        template = self._get_component_template(name)

        try:
            target_file.write_text(template, encoding="utf-8")
            # Load immediately after creation
            self._load_user_component(target_file)
            log.info(f"Component <{name}> copied to {target_file}")
            return True, f"Successfully created: {target_file}"
        except IOError as e:
            return False, f"Failed to write file: {e}"

    def _get_component_template(self, name: str) -> str:
        """Return customizable template code for built-in components."""
        templates = {
            "Button": '''"""Button Component - Customize freely!"""

def render(
    text: str = "",
    href: str = "#",
    variant: str = "default",
    class_name: str = "",
    **kwargs
):
    """
    Button element — customize styles, variants, and behavior here.

    Args:
        text: Visible button label
        href: Target link URL
        variant: default | primary | secondary | outline | ghost
        class_name: Additional CSS classes
    """
    base_class = "btn"
    variant_class = f"btn-{variant}"
    classes = f"{base_class} {variant_class} {class_name}".strip()

    return f'<a href="{href}" class="{classes}">{text}</a>'
''',

            "Card": '''"""Card Component - Customize freely!"""

def render(
    title: str = "",
    children: str = "",
    class_name: str = "",
    **kwargs
):
    """
    Card container — customize layout and styling here.

    Args:
        title: Optional card header
        children: Card content
        class_name: Additional CSS classes
    """
    return f'''
<div class="card {class_name}">
    {f'<h3 class="card-title">{title}</h3>' if title else ""}
    <div class="card-body">{children}</div>
</div>
'''.strip()
''',

            "Icon": '''"""Icon Component - Customize freely!"""

def render(
    name: str = "default",
    size: str = "24",
    class_name: str = "",
    **kwargs
):
    """
    Icon element — customize icon system here.

    Args:
        name: Icon identifier
        size: Pixel size or CSS value
        class_name: Additional CSS classes
    """
    return f'<span class="icon icon-{name} {class_name}" style="font-size:{size}px"></span>'
''',
        }

        return templates.get(name, f'''"""Custom {name} Component"""

def render(**kwargs):
    """Customize this component — edit the render function!"""
    return f'<div class="{name.lower()}">{kwargs.get("children", "")}</div>'
''')


# ─── Global Instance ───

_component_loader: Optional[ComponentLoader] = None


def get_loader() -> ComponentLoader:
    """Get or create the global ComponentLoader instance."""
    global _component_loader
    if _component_loader is None:
        _component_loader = ComponentLoader()
    return _component_loader


# ─── Public API ───

def render_component(name: str, attrs: Dict[str, Any], children: Any = None) -> str:
    """Render a component — called from the template renderer."""
    return get_loader().render(name, attrs, children)


def get_component(name: str) -> Optional[Callable]:
    """Get component render function directly."""
    return get_loader().get(name)


def list_components() -> Dict[str, Dict[str, Any]]:
    """List all registered components with their source."""
    return get_loader().list_all()


def copy_builtin_component(name: str) -> Tuple[bool, str]:
    """CLI command: copy built-in component to user project."""
    return get_loader().copy_to_user(name)
