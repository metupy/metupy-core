"""metupy_core.config
Configuration Loader — Load and expose project configuration.

Dynamically loads pymconfig.py as a module and provides
attribute-style access to all uppercase variables.
"""

import importlib.util
import sys
from pathlib import Path
from typing import Any

from metupy_core.exception import ConfigError


class Config:
    """Load and expose project configuration from pymconfig.py.

    Dynamically imports the Python config file as a module and provides
    attribute-style access to all uppercase variables defined therein.
    """

    def __init__(self, root_dir: str | Path | None = None) -> None:
        """Initialize the configuration loader.

        Args:
            root_dir: Absolute or relative path to the project root directory.
                If None, uses current working directory.
        """
        self.root: Path = Path(root_dir).resolve() if root_dir else Path.cwd().resolve()
        self._config_module: Any = None
        self.load()

    def load(self) -> None:
        """Load the pymconfig.py file as a Python module.

        Searches in:
            1. self.root / "pymconfig.py"

        Raises:
            ConfigError: If config file not found or cannot be imported.
        """
        # Search in possible locations
        possible_paths = [
            self.root / "pymconfig.py",
        ]

        config_path: Path | None = None
        for path in possible_paths:
            if path.exists():
                config_path = path
                break

        if not config_path:
            searched = "\n  ".join(str(p) for p in possible_paths)
            raise ConfigError(
                f"pymconfig.py not found.\n"
                f"Searched in:\n  {searched}\n"
                f"Run `pym init` to create a new project."
            )

        # Load as module
        spec = importlib.util.spec_from_file_location("metupy_config", config_path)
        if spec is None or spec.loader is None:
            raise ConfigError(f"Failed to load config from: {config_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules["metupy_config"] = module
        spec.loader.exec_module(module)
        self._config_module = module

    def __getattr__(self, name: str) -> Any:
        """Retrieve a configuration variable by name.

        Args:
            name: The uppercase variable name from pymconfig.py.

        Returns:
            The value of the requested configuration variable.

        Raises:
            ConfigError: If the variable does not exist in config.
        """
        if not name.isupper():
            raise ConfigError(
                f"Config variables must be UPPERCASE (got: '{name}').\n"
                f"Check your pymconfig.py file."
            )

        if not hasattr(self._config_module, name):
            raise ConfigError(
                f"Configuration variable '{name}' not found.\n"
                f"Check pymconfig.py or add the variable."
            )

        return getattr(self._config_module, name)

    def get(self, name: str, default: Any = None) -> Any:
        """Safely get a config value with fallback default.

        Args:
            name: Variable name (uppercase).
            default: Value to return if variable not found.

        Returns:
            The config value or default.
        """
        try:
            return self.__getattr__(name)
        except ConfigError:
            return default


# ─── Convenience Export ────────────────────────────────────────────
def load_config(root_dir: str | Path | None = None) -> Config:
    """Load and return a Config instance.

    Args:
        root_dir: Project root directory. Defaults to CWD.

    Returns:
        Config instance.
    """
    return Config(root_dir)
