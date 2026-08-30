<p align="center">
  <img src="https://raw.githubusercontent.com/palembangpy/metupy/main/src/metupy/assets/metupy.png" alt="Metupy Logo" width="120" height="120">
  <br>
  <strong>Fast • Simple • Extensible</strong>
  <br>
  Core utilities and foundational components for Metupy static site generator.
</p>

<p align="center">
  <img src="https://img.shields.io/pypi/v/metupy-core?style=for-the-badge&color=blue" alt="PyPI Version">
  <img src="https://img.shields.io/badge/tests-passing-green?style=for-the-badge" alt="Tests Passing">
  <img src="https://img.shields.io/badge/python-3.9+-blue?style=for-the-badge" alt="Python Version">
  <img src="https://img.shields.io/badge/license-MIT-yellow?style=for-the-badge" alt="License">
</p>

---


### Metupy
Metupy Core provides the essential building blocks used across the Metupy ecosystem:
- **Signal** System — Event-driven hooks for plugins and lifecycle management
- **Utilities** — File operations, path handling, port detection, date formatting, and more
- **Writer** — Output writing, asset copying, and directory management

### Installation

```bash
pip install metupy-core
```

### Quick Start

```python
from metupy_core.signal import on, emit
from metupy_core.writer import write_output, copy_assets
from metupy_core.utils import slugify, get_free_port
```

### Project Structure

```bash
src/metupy_core/
├── __init__.py       # Package entry point & public API
├── api.py             # High-level public interface
├── cache.py           # Caching system & memory management
├── components.py      # UI component blueprints
├── config.py          # Configuration loading & validation
├── contents.py        # Content processing & data models
├── database.py        # Local database & storage layer
├── exception.py       # Custom exceptions & error handling
├── generators.py      # Static file & page generators
├── i18n.py            # Internationalization & multi-language
├── logging.py         # Logging setup & output formatting
├── middleware.py      # Request/response middleware
├── parsers.py         # Markdown & file parsers
├── reader.py          # File system reading & watching
├── renderer.py        # Template rendering engine
├── server.py          # Development HTTP server
├── setting.py         # User settings & defaults
├── signal.py          # Event system & hooks
├── utils.py           # Shared utilities & helpers
└── writer.py          # File output & asset management

```

<p align="center">
  <img src="https://img.shields.io/badge/Made%20with-Python-3776AB?style=flat-square" alt="Made with Python">
  <br><br>
  MIT License — see LICENSE file for details
</p>
