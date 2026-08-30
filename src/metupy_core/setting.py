"""
metupy_core.setting
~~~~~~~~~~~~~~~

Load, validate, and manage Metupy configuration.
Reads from pymconfig.py or any *.pymconfig.py file in the project root.
Handles navigation tree building based on content directory structure.
Supported content formats: .pym, .py, .md, .rst
"""

import os
import sys
import importlib.util
from pathlib import Path
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, field, asdict

from .utils import get_ext


__all__ = ["NavItem", "Setting", "load_setting", "build_navigation_tree"]


CONFIG_FILENAMES = [
    "pymconfig.py",
    "pymconfig.pymconfig.py",
    "config.pymconfig.py",
    "site.pymconfig.py",
]

# Supported content file extensions
CONTENT_EXTENSIONS = {"pym", "py", "md", "rst"}


@dataclass
class NavItem:
    """Represent a single navigation menu item."""
    label: str
    url: str
    is_folder: bool = False
    children: List["NavItem"] = field(default_factory=list)


@dataclass
class Setting:
    """Unified configuration container for Metupy."""

    # ═══ Site Information (sesuai pymconfig.py) ═══
    site_name: str = "Metupy Site"
    site_version: str = "1.0.0"
    site_description: str = ""
    site_author: str = ""
    site_keywords: List[str] = field(default_factory=list)
    site_lang: str = "id"
    site_timezone: str = "Asia/Jakarta"
    site_url: str = ""
    site_base_url: str = "/"

    # ═══ Theme Configuration ═══
    active_theme: str = "peradocs"
    theme_dir: str = "themes/peradocs"
    theme_use_darkmode: bool = True
    theme_use_search: bool = True

    # ═══ Build Paths ═══
    content_dir: str = "content"
    output_dir: str = "public"
    assets_dir: str = "content/assets"

    # ═══ Build Setting ═══
    build_minify_html: bool = False
    build_minify_css: bool = False
    build_generate_sitemap: bool = True
    build_generate_feed: bool = True
    build_cache_enabled: bool = True
    build_pretty_urls: bool = True

    # ═══ Server Configuration ═══
    dev_host: str = "localhost"
    dev_port: int = 3000
    dev_live_reload: bool = True
    dev_watch_files: bool = True

    # ═══ GitHub Deployment ═══
    github_username: str = ""
    github_repo_name: str = ""
    github_branch: str = "gh-pages"
    github_repo_url: str = ""
    github_pages_url: str = ""

    # ═══ Navigation ═══
    navigation: List[str] = field(default_factory=list)

    # ═══ Auto Generated ═══
    config_generated: str = ""
    config_signature: str = ""

    # ─── Dynamic Properties ───
    @property
    def content_path(self) -> Path:
        """Return absolute path to content source directory."""
        return Path(self.content_dir).resolve()

    @property
    def output_path(self) -> Path:
        """Return absolute path to output directory."""
        return Path(self.output_dir).resolve()

    @property
    def header_nav(self) -> List[NavItem]:
        """Build header navigation from NAVIGATION config list."""
        return build_navigation_tree(self.content_path, self.navigation)

    @property
    def sidebar_menu(self) -> List[NavItem]:
        """Build sidebar menu from all content items NOT in NAVIGATION list."""
        all_items = self._scan_all_content_items()
        header_keys = {item.label.lower().replace(" ", "-") for item in self.header_nav}
        sidebar_items = [
            item for item in all_items
            if item.label.lower().replace(" ", "-") not in header_keys
        ]
        return sidebar_items

    def _scan_all_content_items(self) -> List[NavItem]:
        """Scan content directory → NavItem list."""
        if not self.content_path.exists():
            return []

        items = []
        for name in sorted(os.listdir(self.content_path)):
            if name.startswith((".", "_")):
                continue
            path = self.content_path / name
            if path.is_dir():
                items.append(NavItem(
                    label=name.replace("-", " ").title(),
                    url=f"/{name}/",
                    is_folder=True,
                    children=self._scan_folder_children(path, name)
                ))
            elif path.is_file() and get_ext(name) in CONTENT_EXTENSIONS:
                slug = Path(name).stem.lower().replace(" ", "-")
                label = Path(name).stem.replace("-", " ").title()
                items.append(NavItem(label=label, url=f"/{slug}/", is_folder=False))
        return items

    def _scan_folder_children(self, folder_path: Path, parent_slug: str) -> List[NavItem]:
        """Recursively scan folder contents."""
        children = []
        for name in sorted(os.listdir(folder_path)):
            if name.startswith((".", "_")):
                continue
            path = folder_path / name
            if path.is_file() and get_ext(name) in CONTENT_EXTENSIONS:
                slug = Path(name).stem.lower().replace(" ", "-")
                label = Path(name).stem.replace("-", " ").title()
                children.append(NavItem(
                    label=label,
                    url=f"/{parent_slug}/{slug}/",
                    is_folder=False
                ))
        return children

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve config value with dot notation support."""
        if "." in key:
            value = self
            for part in key.split("."):
                value = getattr(value, part, None)
                if value is None:
                    return default
            return value
        return getattr(self, key, default)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize all setting to dictionary."""
        data = asdict(self)
        data["header_nav"] = [n.__dict__ for n in self.header_nav]
        data["sidebar_menu"] = [n.__dict__ for n in self.sidebar_menu]
        return data


def _find_config_file(root_dir: Path) -> Optional[Path]:
    """Locate configuration file in project root."""
    for name in CONFIG_FILENAMES:
        path = root_dir / name
        if path.is_file():
            return path

    for path in root_dir.glob("*.pymconfig.py"):
        if path.is_file():
            return path

    return None


def _load_config_module(config_path: Path) -> Dict[str, Any]:
    """Load Python config file → convert UPPER_CASE → snake_case."""
    if not config_path.exists():
        return {}

    parent_dir = str(config_path.parent.resolve())
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    try:
        spec = importlib.util.spec_from_file_location("pymconfig", config_path)
        if spec is None or spec.loader is None:
            print(f"⚠️  Invalid config file: {config_path.name}")
            return {}

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        config = {}
        for key, value in vars(module).items():
            if not key.startswith("_"):
                # Convert SITE_NAME → site_name
                config[key.lower()] = value

        return config

    except Exception as e:
        print(f"❌ Error loading {config_path.name}: {e}")
        return {}
    finally:
        if parent_dir in sys.path:
            sys.path.remove(parent_dir)


def load_setting(root_dir: str | Path | None = None) -> Setting:
    """Load configuration from pymconfig.py or use defaults."""
    if root_dir is None:
        root_dir = Path.cwd()
    else:
        root_dir = Path(root_dir).resolve()

    config_file = _find_config_file(root_dir)
    setting_dict = {}

    if config_file:
        print(f"Loaded config: {config_file.name}")
        user_config = _load_config_module(config_file)
        setting_dict.update(user_config)
    else:
        print("No pymconfig.py found — using defaults")

    return Setting(**setting_dict)


def build_navigation_tree(content_dir: Path, selected_items: List[str]) -> List[NavItem]:
    """Build navigation menu structure from NAVIGATION list."""
    if not content_dir.exists():
        return []

    nav_items = []

    for item_name in selected_items:
        item_path = content_dir / item_name

        # Item is a folder → dropdown
        if item_path.is_dir():
            children = []
            for child_file in sorted(item_path.iterdir()):
                if (child_file.is_file()
                    and get_ext(child_file.name) in CONTENT_EXTENSIONS
                    and not child_file.name.startswith(("_", "."))):
                    slug = Path(child_file.stem).lower().replace(" ", "-")
                    label = Path(child_file.stem).replace("-", " ").title()
                    children.append(NavItem(
                        label=label,
                        url=f"/{item_name}/{slug}/",
                        is_folder=False
                    ))
            nav_items.append(NavItem(
                label=item_name.replace("-", " ").title(),
                url=f"/{item_name}/",
                is_folder=True,
                children=children
            ))

        # Item is a file → direct link
        else:
            found = False
            for ext in CONTENT_EXTENSIONS:
                file_path = content_dir / f"{item_name}.{ext}"
                if file_path.is_file():
                    label = item_name.replace("-", " ").title()
                    nav_items.append(NavItem(
                        label=label,
                        url=f"/{item_name}/",
                        is_folder=False
                    ))
                    found = True
                    break
            # Not found → still create link
            if not found:
                nav_items.append(NavItem(
                    label=item_name.replace("-", " ").title(),
                    url=f"/{item_name}/",
                    is_folder=False
                ))

    return nav_items
