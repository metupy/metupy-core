"""
metupy_core.generators
~~~~~~~~~~~~~~~~~

Site generation orchestration.
Coordinates content discovery, parsing, rendering, and output writing.
Handles build pipeline, incremental builds, global context, and i18n multi-language translation.

Features:
    • Full multi-language site generation (i18n integration)
    • Automatic content translation for all configured languages
    • Incremental build support with file caching
    • Global context + per-page context
    • Asset copying and output management
    • Signal hooks for build lifecycle events

Usage:
    from metupy_core.generators import SiteGenerator

    generator = SiteGenerator(
        default_lang="en",
        supported_langs=["en", "id", "zh-CN"],
        auto_translate=True
    )
    generator.build()
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass

from .logging import log
from .contents import ContentManager, ContentFile
from .reader import read_and_parse
from .renderer import Renderer, RenderContext
from .writer import write_output, copy_assets, get_output_path
from .signal import emit
from .cache import FileCache
from .i18n import I18nManager, init_i18n, get_i18n


__all__ = [
    "BuildResult",
    "SiteGenerator",
]


# ─── Build Result ───

@dataclass
class BuildResult:
    """Result of a build operation with statistics including multi-language output."""
    total_files: int = 0
    rendered: int = 0
    skipped: int = 0
    failed: int = 0
    total_languages: int = 1
    translations_generated: int = 0
    output_dir: Optional[Path] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    @property
    def duration(self) -> float:
        """Build duration in seconds."""
        if not self.start_time or not self.end_time:
            return 0.0
        return (self.end_time - self.start_time).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for logging."""
        return {
            "total_source_files": self.total_files,
            "rendered": self.rendered,
            "skipped": self.skipped,
            "failed": self.failed,
            "languages": self.total_languages,
            "translations": self.translations_generated,
            "duration": f"{self.duration:.2f}s",
        }


# ─── Site Generator ───

class SiteGenerator:
    """
    Main site generation orchestrator with full i18n support.
    Manages the complete build pipeline:
        discover → parse → render → translate (per language) → write → copy assets
    """

    def __init__(
        self,
        source_dir: Path | None = None,
        output_dir: Path | None = None,
        theme: str = "peradocs",
        template: str = "base.html",
        site_config: Dict[str, Any] | None = None,
        # ─── i18n Configuration ───
        default_lang: str = "en",
        supported_langs: Optional[List[str]] = None,
        auto_translate: bool = True,
        translator_provider: str = "google",
    ):
        """
        Initialize the site generator with internationalization support.

        Args:
            source_dir: Root directory of the project.
            output_dir: Directory for generated HTML files.
            theme: Theme name to use.
            template: Default base template.
            site_config: Site-wide configuration dictionary.
            default_lang: Primary language code (no prefix in URL).
            supported_langs: List of all language codes to generate.
            auto_translate: Enable automatic translation of all content.
            translator_provider: Translation service (google, deepl, microsoft).
        """
        self.source_dir = Path(source_dir or Path.cwd()).resolve()
        self.output_dir = Path(output_dir or self.source_dir / "public").resolve()
        self.theme = theme
        self.template = template

        # Site configuration
        self.site_config = site_config or {}
        self.default_lang = default_lang
        self.supported_langs = supported_langs or [default_lang]
        self.auto_translate = auto_translate

        # ─── Initialize I18n Manager ───
        init_i18n(
            default_lang=default_lang,
            supported_langs=self.supported_langs,
            content_dir=self.source_dir / "contents",
            auto_translate=auto_translate,
            translator_provider=translator_provider,
        )
        self.i18n = get_i18n()
        log.debug(
            f"I18n initialized — default: {default_lang}, "
            f"languages: {self.supported_langs}, "
            f"auto_translate: {'ON' if auto_translate else 'OFF'}"
        )

        # Global context available to all templates
        self.global_context: Dict[str, Any] = {
            "site_name": self.site_config.get("site_name", "Peradocs Site"),
            "site_description": self.site_config.get("site_description", ""),
            "site_url": self.site_config.get("site_url", "/"),
            "theme": theme,
            "build_time": datetime.now(),
            "default_lang": self.default_lang,
            "supported_langs": self.supported_langs,
            "i18n": self.i18n,
            "t": self.i18n.translate,
            "mark_ignore": self.i18n.mark_ignored,
        }

        # Core components
        self.content_manager = ContentManager(
            source_dir=self.source_dir,
            theme=theme,
        )
        self.renderer = Renderer(
            template_dir=self.source_dir / "contents" / "_templates",
            globals=self.global_context,
        )
        self.cache = FileCache(self.source_dir / ".metupy" / "cache")

        log.debug(
            f"SiteGenerator initialized — theme: {theme}, "
            f"output: {self.output_dir}, languages: {self.supported_langs}"
        )

    # ─── Main Build Pipeline ───

    def build(self, force_rebuild: bool = False, include_drafts: bool = False) -> BuildResult:
        """
        Run full site generation pipeline for ALL supported languages.

        Pipeline per source file:
            1. Parse content → 2. Render for default lang → 3. Translate to other langs → 4. Write all outputs
        """
        result = BuildResult(
            start_time=datetime.now(),
            output_dir=self.output_dir,
            total_languages=len(self.supported_langs),
        )

        emit("build_started", generator=self, force_rebuild=force_rebuild)
        log.info(
            f"Building site — languages: {self.supported_langs} "
            f"(auto-translate: {'ON' if self.auto_translate else 'OFF'})"
        )

        # Step 1: Discover all source content files
        files = self.content_manager.discover(force_rebuild=force_rebuild)
        if not include_drafts:
            files = [f for f in files if f.is_published]
        result.total_files = len(files)

        # Step 2: Prepare output directory
        self._prepare_output_dir()

        # Step 3: Process each file → generate for ALL languages
        for content_file in files:
            translations_count = self._process_file_all_languages(
                content_file, result, force_rebuild
            )
            result.translations_generated += translations_count

        # Step 4: Copy static assets (single copy — shared across all languages)
        self._copy_assets()

        # Step 5: Finalize
        self.cache.save()
        result.end_time = datetime.now()

        emit("build_finished", result=result)
        log.info(f"Build complete — {result.to_dict()}")
        return result

    # ─── Multi-Language File Processing ───

    def _process_file_all_languages(
        self,
        content_file: ContentFile,
        result: BuildResult,
        force_rebuild: bool,
    ) -> int:
        """
        Process one source file and generate output for ALL supported languages.
        Returns number of translated variants generated.
        """
        emit("file_build_start", file=content_file)
        translations_created = 0

        # Skip unchanged files (cache check applies to all language variants)
        if not force_rebuild and self.cache.is_unchanged(content_file.path):
            all_exist = all(
                (self.output_dir / self._get_lang_output_path(content_file, lang)).exists()
                for lang in self.supported_langs
            )
            if all_exist:
                log.debug(f"Skipped (unchanged): {content_file.rel_path}")
                result.skipped += 1
                emit("file_build_skipped", file=content_file)
                return 0

        # Parse source file ONCE — shared for all languages
        parsed = read_and_parse(content_file.path, source_dir=self.source_dir)
        if parsed.has_errors:
            log.error(f"❌ Parse failed: {content_file.rel_path} — {parsed.error_message}")
            result.failed += 1
            emit("file_build_failed", file=content_file, error=parsed.error_message)
            return 0

        # Build base context — language-neutral
        base_context = {
            **self.global_context,
            **content_file.metadata,
            "content_file": content_file,
            "all_pages": self.content_manager.get_pages(),
            "all_posts": self.content_manager.get_posts(),
        }

        # ─── Generate for EACH supported language ───
        for lang in self.supported_langs:
            html = self._render_for_language(parsed, base_context, content_file, lang)

            # Determine output path — default lang has no prefix
            output_path = self._get_lang_output_path(content_file, lang)

            # Write output
            full_output = self.output_dir / output_path
            write_output(html, full_output)

            # Count non-default languages as translations
            if lang != self.default_lang:
                translations_created += 1

            log.debug(f"[{lang}] Rendered: {content_file.rel_path} → {output_path}")
            emit("file_lang_complete", file=content_file, lang=lang, output_path=output_path)

        result.rendered += 1
        self.cache.update(content_file.path)
        emit("file_build_complete", file=content_file)
        return translations_created

    def _render_for_language(
        self,
        parsed,
        base_context: Dict[str, Any],
        content_file: ContentFile,
        target_lang: str,
    ) -> str:
        """
        Render content for a specific language.
        Auto-translates page content if target != default language.
        """
        # Create language-specific context
        lang_context = {
            **base_context,
            "lang": target_lang,
            "current_lang": target_lang,
            "is_default_lang": (target_lang == self.default_lang),
            "language_switcher": self.i18n.get_language_switcher(
                current_path=f"/{content_file.output_path}",
                current_lang=target_lang,
            ),
        }

        # Auto-translate content if target is not default language
        if target_lang != self.default_lang and self.auto_translate:
            original_content = parsed.content
            translated_content = self.i18n.translate_page_content(
                content=original_content,
                target_lang=target_lang,
                source_lang=self.default_lang,
            )
            # Update parsed content with translated version
            parsed = parsed.__class__(
                content=translated_content,
                metadata=parsed.metadata,
                html=getattr(parsed, "html", None),
            )

        # Render template with language context
        return self.renderer.render(
            parsed,
            context=RenderContext(lang_context),
            template=content_file.metadata.get("template", self.template),
        )

    def _get_lang_output_path(self, content_file: ContentFile, lang: str) -> Path:
        """
        Generate output path for a given language.
        Default lang → /about/index.html (no prefix)
        Other langs → /id/about/index.html (prefixed)
        """
        base = Path(content_file.output_path)
        if lang == self.default_lang:
            return base
        return Path(lang) / base

    # ─── Helper Methods ───

    def _prepare_output_dir(self) -> None:
        """Create output directory and language sub-directories if needed."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Create language directories for non-default languages
        for lang in self.supported_langs:
            if lang != self.default_lang:
                (self.output_dir / lang).mkdir(exist_ok=True)
        log.debug(f"Output directory ready: {self.output_dir}")

    def _copy_assets(self) -> None:
        """Copy static assets — shared across ALL languages (no duplication)."""
        assets_dir = self.source_dir / "contents" / "assets"
        if assets_dir.exists():
            stats = copy_assets(assets_dir, self.output_dir / "assets")
            log.info(f"Assets copied — {stats}")

    # ─── Utility Methods ───

    def clean(self) -> None:
        """Remove output directory and clear all caches."""
        import shutil

        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
            log.info(f"Removed output directory: {self.output_dir}")

        self.cache.clear()
        self.renderer.clear_cache()
        log.info("Cache cleared")

    def get_context(self) -> Dict[str, Any]:
        """Get global context dictionary including i18n utilities."""
        return self.global_context.copy()
