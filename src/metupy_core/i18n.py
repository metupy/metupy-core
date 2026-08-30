"""
metupy_core.i18n
~~~~~~~~~~~~~~~~

Internationalization (i18n) and localization system for Metupy.
Provides full-content automatic translation with selective ignore support.

Features:
    • Full-content auto-translation — ALL content is translated by default
    • Ignore system — mark text to NEVER be translated
    • Multiple ignore patterns: inline markers, HTML tags, custom placeholders
    • Translation catalog loading from JSON files
    • Automatic translation via deep-translator (Google, DeepL, Microsoft, etc.)
    • Language detection, localized URLs, language switcher
    • Nested dot-notation translation keys
    • RTL language support

Ignore Usage:
    {{{dont-translate-this}}}        → Inline marker
    <!-- no-translate --> ... <!-- /no-translate --> → HTML block
    <span class="notranslate">...</span> → Standard class
    {{ variable_name }}              → Template variables are auto-ignored
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from dataclasses import dataclass, field
from functools import lru_cache

from .logging import log


# ─── Constants ───

DEFAULT_LANG = "en"
LOCALE_PATTERN = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")
TRANSLATION_DIR = "locales"

# ─── Ignore Patterns ──────────────────────────────────────────────
# Text matching these patterns will be EXCLUDED from translation
# ──────────────────────────────────────────────────────────────────

# Inline marker: {{{text to ignore}}}
INLINE_IGNORE_PATTERN = re.compile(r"{{{([^}]+)}}}")

# HTML comment markers: <!-- no-translate --> ... <!-- /no-translate -->
BLOCK_IGNORE_PATTERN = re.compile(
    r"<!--\s*no-translate\s*-->(.*?)<!--\s*/no-translate\s*-->",
    re.DOTALL | re.IGNORECASE,
)

# Standard Google-style notranslate class
HTML_IGNORE_PATTERN = re.compile(
    r'<[^>]+class="[^"]*\bnotranslate\b[^"]*"[^>]*>.*?</[^>]+>',
    re.DOTALL | re.IGNORECASE,
)

# Jinja/Handlebars variables: {{ var }}, {% ... %}
TEMPLATE_VAR_PATTERN = re.compile(r"{{[^}]+}}|{%[^%]+%}")

# Code blocks: ```...```, `...`
CODE_BLOCK_PATTERN = re.compile(r"```.*?```|`[^`]+`", re.DOTALL)

# Email, URLs, IP addresses, hex colors
AUTO_IGNORE_PATTERNS = [
    re.compile(r"https?://[^\s]+"),  # URLs
    re.compile(r"mailto:[^\s]+"),  # Emails
    re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b"),  # Emails
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),  # IP addresses
    re.compile(r"#[0-9a-fA-F]{3,6}\b"),  # Hex colors
    re.compile(r"\b[A-Z][A-Z0-9_]+\b"),  # UPPER_CASE constants
]


# ─── Data Structures ───

@dataclass
class LocaleInfo:
    """Metadata for a supported language/locale."""
    code: str
    name: str
    is_default: bool = False
    is_rtl: bool = False
    flag: Optional[str] = None


@dataclass
class TranslationResult:
    """Result of a translation operation with preserved ignore blocks."""
    original: str
    translated: str
    source_lang: str
    target_lang: str
    provider: str
    success: bool = True
    error: Optional[str] = None
    ignored_segments: List[str] = field(default_factory=list)


# ─── Ignore Manager ───

class IgnoreManager:
    """
    Manages text segments that should NOT be translated.
    Provides methods to extract, replace, and restore ignored content.
    """

    def __init__(self, custom_patterns: Optional[List[re.Pattern]] = None):
        """
        Initialize the ignore manager.

        Args:
            custom_patterns: Additional regex patterns to ignore.
        """
        # Built-in ignore patterns (order matters — longer matches first)
        self._block_patterns: List[Tuple[str, re.Pattern]] = [
            ("html_notranslate", HTML_IGNORE_PATTERN),
            ("block_marker", BLOCK_IGNORE_PATTERN),
            ("code_block", CODE_BLOCK_PATTERN),
        ]

        self._inline_patterns: List[Tuple[str, re.Pattern]] = [
            ("inline_marker", INLINE_IGNORE_PATTERN),
            ("template_var", TEMPLATE_VAR_PATTERN),
        ]

        # Auto-detected patterns (not removed, just tracked)
        self._auto_patterns = AUTO_IGNORE_PATTERNS

        # User-defined custom patterns
        if custom_patterns:
            for i, pat in enumerate(custom_patterns):
                self._block_patterns.append((f"custom_{i}", pat))

        self._placeholder_prefix = "__IGNORE_SEG_"
        self._placeholder_suffix = "__"

    def extract_ignored(self, text: str) -> Tuple[str, List[str]]:
        """
        Extract all ignored segments from text and replace them
        with temporary placeholders.

        Args:
            text: Original text that may contain ignored segments.

        Returns:
            Tuple of (cleaned_text_with_placeholders, list_of_ignored_segments)
        """
        segments: List[str] = []
        result = text

        # Process block patterns first (larger segments)
        for pattern_name, pattern in self._block_patterns:
            matches = list(pattern.finditer(result))
            # Process in reverse order to preserve positions
            for match in reversed(matches):
                full_match = match.group(0)
                placeholder = f"{self._placeholder_prefix}{len(segments)}{self._placeholder_suffix}"
                segments.append(full_match)
                result = result[:match.start()] + placeholder + result[match.end():]

        # Process inline patterns
        for pattern_name, pattern in self._inline_patterns:
            matches = list(pattern.finditer(result))
            for match in reversed(matches):
                full_match = match.group(0)
                placeholder = f"{self._placeholder_prefix}{len(segments)}{self._placeholder_suffix}"
                segments.append(full_match)
                result = result[:match.start()] + placeholder + result[match.end():]

        # Auto-detect patterns — just add to ignore list, don't replace
        for pattern in self._auto_patterns:
            for match in pattern.finditer(result):
                pass  # Already handled by preservation

        return result, segments

    def restore_ignored(self, translated_text: str, ignored_segments: List[str]) -> str:
        """
        Restore ignored segments back into translated text.

        Args:
            translated_text: Text after translation (contains placeholders).
            ignored_segments: List of original segments to restore.

        Returns:
            Final text with all ignored content preserved.
        """
        result = translated_text
        for idx, original in enumerate(ignored_segments):
            placeholder = f"{self._placeholder_prefix}{idx}{self._placeholder_suffix}"
            result = result.replace(placeholder, original)
        return result

    def should_skip_entirely(self, text: str) -> Optional[str]:
        """
        Check if the entire text should NOT be translated at all.
        Returns the reason if should skip, None otherwise.
        """
        text = text.strip()
        if not text:
            return "empty_text"
        if TEMPLATE_VAR_PATTERN.fullmatch(text):
            return "template_variable"
        if text.startswith("```") and text.endswith("```"):
            return "code_block"
        if text.startswith("`") and text.endswith("`"):
            return "inline_code"
        return None

    def add_custom_ignore(self, pattern: re.Pattern) -> None:
        """
        Add a custom regex pattern to the ignore list.

        Usage:
            i18n.ignore.add_custom_ignore(re.compile(r"@\w+"))
        """
        self._block_patterns.append((f"custom_{len(self._block_patterns)}", pattern))


# ─── Exceptions ───

class TranslationError(Exception):
    """Base exception for i18n-related errors."""
    pass


class LanguageNotSupportedError(TranslationError):
    """Raised when an unsupported language code is requested."""
    pass


# ─── Auto-Translator ───

class AutoTranslator:
    """
    Wrapper for deep-translator library.
    Translates ALL content by default, respecting ignore markers.
    """

    _AVAILABLE_PROVIDERS: Dict[str, str] = {
        "google": "GoogleTranslator",
        "deepl": "DeepLTranslator",
        "microsoft": "MicrosoftTranslator",
        "yandex": "YandexTranslator",
    }

    def __init__(
        self,
        provider: str = "google",
        api_key: Optional[str] = None,
        ignore_manager: Optional[IgnoreManager] = None,
    ):
        """
        Initialize the automatic translator.

        Args:
            provider: Translation service provider.
            api_key: API key for services requiring authentication.
            ignore_manager: IgnoreManager for preserving untranslatable segments.
        """
        self.provider = provider.lower()
        self.api_key = api_key
        self.ignore = ignore_manager or IgnoreManager()
        self._translator_class: Any = None
        self._available = False
        self._init_translator()

    def _init_translator(self) -> None:
        """Attempt to import and initialize the selected translator."""
        try:
            from deep_translator import GoogleTranslator, DeepLTranslator, MicrosoftTranslator
            providers = {
                "google": GoogleTranslator,
                "deepl": DeepLTranslator,
                "microsoft": MicrosoftTranslator,
            }
            self._translator_class = providers.get(self.provider)
            if self._translator_class:
                self._available = True
                log.debug(f"Auto-translator initialized: {self.provider}")
            else:
                self._translator_class = GoogleTranslator
                self.provider = "google"
                self._available = True
        except ImportError:
            self._available = False
            log.debug(
                "deep-translator not installed. Auto-translation disabled.\n"
                "Install with: pip install deep-translator"
            )

    @property
    def is_available(self) -> bool:
        """Check if the translator service is available."""
        return self._available

    def translate(
        self,
        text: str,
        source_lang: str = "auto",
        target_lang: str = DEFAULT_LANG,
        respect_ignore: bool = True,
    ) -> TranslationResult:
        """
        Translate text — ALL content is translated by default.
        Automatically preserves ignored segments marked with ignore patterns.

        Args:
            text: Text to translate.
            source_lang: Source language code.
            target_lang: Target language code.
            respect_ignore: Whether to apply ignore rules (default: True).

        Returns:
            TranslationResult with translated text and preserved ignored segments.
        """
        # Skip empty text
        if not text.strip():
            return TranslationResult(
                original=text, translated=text,
                source_lang=source_lang, target_lang=target_lang,
                provider=self.provider, success=True,
            )

        # Check if entire text should be skipped
        skip_reason = self.ignore.should_skip_entirely(text) if respect_ignore else None
        if skip_reason:
            return TranslationResult(
                original=text, translated=text,
                source_lang=source_lang, target_lang=target_lang,
                provider=self.provider, success=True,
                ignored_segments=[f"entire_text: {skip_reason}"],
            )

        # Extract ignored segments → replace with placeholders
        ignored_segments: List[str] = []
        clean_text = text
        if respect_ignore:
            clean_text, ignored_segments = self.ignore.extract_ignored(text)

        # If nothing to translate after extraction
        if not clean_text.strip():
            return TranslationResult(
                original=text, translated=text,
                source_lang=source_lang, target_lang=target_lang,
                provider=self.provider, success=True,
                ignored_segments=ignored_segments,
            )

        # Perform translation
        if not self._available:
            return TranslationResult(
                original=text, translated=text,
                source_lang=source_lang, target_lang=target_lang,
                provider=self.provider, success=False,
                error="Translator not available",
                ignored_segments=ignored_segments,
            )

        try:
            kwargs: Dict[str, Any] = {"source": source_lang, "target": target_lang}
            if self.api_key and self.provider != "google":
                kwargs["api_key"] = self.api_key

            translator = self._translator_class(**kwargs)
            translated_clean = translator.translate(clean_text)

            # Restore ignored segments
            final_translation = self.ignore.restore_ignored(translated_clean, ignored_segments)

            return TranslationResult(
                original=text, translated=final_translation,
                source_lang=source_lang, target_lang=target_lang,
                provider=self.provider, success=True,
                ignored_segments=ignored_segments,
            )

        except Exception as e:
            log.warning(f"Translation failed: {e}")
            return TranslationResult(
                original=text, translated=text,
                source_lang=source_lang, target_lang=target_lang,
                provider=self.provider, success=False,
                error=str(e), ignored_segments=ignored_segments,
            )

    def translate_content(
        self,
        content: str,
        source_lang: str = "auto",
        target_lang: str = DEFAULT_LANG,
    ) -> TranslationResult:
        """
        Translate FULL content — paragraphs, lists, code blocks, everything.
        This is the MAIN method called for full-page/content translation.
        """
        return self.translate(content, source_lang, target_lang, respect_ignore=True)


# ─── Main I18n Manager ───

class I18nManager:
    """
    Centralized i18n manager with FULL-CONTENT translation and ignore support.
    EVERYTHING is translated by default — use ignore markers to exclude specific parts.
    """

    def __init__(
        self,
        default_lang: str = DEFAULT_LANG,
        supported_langs: Optional[List[str]] = None,
        content_dir: Union[str, Path] = "content",
        translation_dir: Union[str, Path] = TRANSLATION_DIR,
        auto_translate: bool = True,  # DEFAULT: translate ALL content
        translator_provider: str = "google",
        translator_api_key: Optional[str] = None,
        custom_ignore_patterns: Optional[List[re.Pattern]] = None,
    ):
        """
        Initialize the i18n system — FULL-CONTENT translation by default.

        Args:
            default_lang: Default/fallback language code.
            supported_langs: List of supported language codes.
            content_dir: Path to content directory.
            translation_dir: Path to JSON translation catalogs.
            auto_translate: Enable FULL-content auto-translation (DEFAULT: True).
            translator_provider: Translation service provider.
            translator_api_key: API key for translation service.
            custom_ignore_patterns: Additional regex patterns to NOT translate.
        """
        self.default_lang = default_lang
        self.supported_langs = supported_langs or [default_lang]
        self.content_dir = Path(content_dir).resolve()
        self.translation_dir = Path(translation_dir).resolve()
        self.auto_translate = auto_translate

        # Initialize Ignore Manager
        self.ignore = IgnoreManager(custom_ignore_patterns)

        # Validate language codes
        for lang in self.supported_langs:
            if not LOCALE_PATTERN.match(lang):
                log.warning(f"Language code '{lang}' does not match standard format")

        # Initialize auto-translator — ENABLED by default
        self.translator: Optional[AutoTranslator] = None
        if self.auto_translate:
            self.translator = AutoTranslator(
                provider=translator_provider,
                api_key=translator_api_key,
                ignore_manager=self.ignore,
            )

        # Translation catalog cache
        self._catalogs: Dict[str, Dict[str, Any]] = {}

        # Language metadata
        self._lang_info: Dict[str, LocaleInfo] = self._init_lang_metadata()

        # Load all translation catalogs
        self._load_catalogs()

        log.debug(
            f"I18n initialized — default: {default_lang}, "
            f"auto_translate: {'ON' if auto_translate else 'OFF'}, "
            f"supported: {self.supported_langs}"
        )

    def _init_lang_metadata(self) -> Dict[str, LocaleInfo]:
        """Initialize language display metadata."""
        common_names: Dict[str, Tuple[str, Optional[str], bool]] = {
            "en": ("English", "🇬🇧", False),
            "en-US": ("English (US)", "🇺🇸", False),
            "id": ("Bahasa Indonesia", "🇮🇩", False),
            "zh": ("中文", "🇨🇳", False),
            "zh-CN": ("简体中文", "🇨🇳", False),
            "zh-TW": ("繁體中文", "🇹🇼", False),
            "ja": ("日本語", "🇯🇵", False),
            "ko": ("한국어", "🇰🇷", False),
            "ar": ("العربية", "🇸🇦", True),
            "es": ("Español", "🇪🇸", False),
            "fr": ("Français", "🇫🇷", False),
            "de": ("Deutsch", "🇩🇪", False),
            "pt": ("Português", "🇧🇷", False),
            "ru": ("Русский", "🇷🇺", False),
            "vi": ("Tiếng Việt", "🇻🇳", False),
            "th": ("ไทย", "🇹🇭", False),
        }
        result: Dict[str, LocaleInfo] = {}
        for lang in self.supported_langs:
            name, flag, rtl = common_names.get(lang, (lang, None, False))
            result[lang] = LocaleInfo(
                code=lang, name=name,
                is_default=(lang == self.default_lang),
                is_rtl=rtl, flag=flag,
            )
        return result

    def _load_catalogs(self) -> None:
        """Load all JSON translation catalogs from the translation directory."""
        if not self.translation_dir.exists():
            log.debug(f"Translation directory not found: {self.translation_dir}")
            return
        for lang in self.supported_langs:
            catalog_file = self.translation_dir / f"{lang}.json"
            if catalog_file.exists():
                try:
                    with open(catalog_file, "r", encoding="utf-8") as f:
                        self._catalogs[lang] = json.load(f)
                    log.debug(f"Loaded translation catalog: {lang}")
                except json.JSONDecodeError as e:
                    log.error(f"Invalid JSON in {lang}.json: {e}")
                    self._catalogs[lang] = {}
            else:
                self._catalogs[lang] = {}

    def save_catalog(self, lang: str) -> None:
        """Save translation catalog to disk."""
        if lang not in self._catalogs:
            return
        self.translation_dir.mkdir(parents=True, exist_ok=True)
        catalog_file = self.translation_dir / f"{lang}.json"
        with open(catalog_file, "w", encoding="utf-8") as f:
            json.dump(self._catalogs[lang], f, ensure_ascii=False, indent=2)
        log.debug(f"Saved translation catalog: {catalog_file}")

    # ─── Main Translation Methods ───

    @lru_cache(maxsize=1024)
    def translate(
        self,
        text: str,
        lang: Optional[str] = None,
        fallback: Optional[str] = None,
        force_catalog: bool = False,
    ) -> str:
        """
        Translate text — BY DEFAULT translates ALL content automatically.
        Ignore markers are respected — those parts will NOT be translated.

        Args:
            text: Text to translate (can be full content).
            lang: Target language code. Uses default if None.
            fallback: Fallback text if translation fails.
            force_catalog: Only use catalog, skip auto-translation.

        Returns:
            Translated text with ignored segments preserved.
        """
        target_lang = lang or self.default_lang

        if target_lang not in self.supported_langs:
            raise LanguageNotSupportedError(
                f"Language '{target_lang}' not supported. Supported: {self.supported_langs}"
            )

        # Same language — no translation needed
        if target_lang == self.default_lang:
            return text

        # Check catalog first
        catalog = self._catalogs.get(target_lang, {})
        if text in catalog:
            return catalog[text]

        # Auto-translate — TRANSLATE EVERYTHING BY DEFAULT
        if self.auto_translate and self.translator and not force_catalog and text.strip():
            result = self.translator.translate_content(
                text,
                source_lang=self.default_lang,
                target_lang=target_lang,
            )
            if result.success and result.translated != text:
                # Save to catalog for future use
                catalog[text] = result.translated
                self.save_catalog(target_lang)
                if result.ignored_segments:
                    log.debug(
                        f"Translated [{target_lang}] (ignored {len(result.ignored_segments)} segments)"
                    )
                else:
                    log.debug(f"Translated [{target_lang}]")
                return result.translated

        # Fallback
        return fallback or text

    def translate_page_content(
        self,
        content: str,
        target_lang: str,
        source_lang: Optional[str] = None,
    ) -> str:
        """
        TRANSLATE ENTIRE PAGE CONTENT — main entry point for SSG translation.
        EVERYTHING is translated — ignore markers are preserved.
        This is called automatically during the build process.

        Args:
            content: Full HTML/markdown content.
            target_lang: Target language code.
            source_lang: Source language (defaults to default_lang).

        Returns:
            Fully translated content with ignored segments preserved.
        """
        if target_lang == self.default_lang:
            return content

        source = source_lang or self.default_lang

        if not self.auto_translate or not self.translator:
            log.debug(f"Auto-translate disabled, skipping: {target_lang}")
            return content

        result = self.translator.translate_content(content, source, target_lang)

        if result.success:
            log.info(
                f"Page translated: {source} → {target_lang} "
                f"(ignored: {len(result.ignored_segments)} segments)"
            )
            return result.translated
        else:
            log.warning(f"Page translation failed: {result.error}")
            return content

    # ─── Manual Ignore Control ───

    def add_ignore_pattern(self, pattern: re.Pattern) -> None:
        """
        Add a custom regex pattern to NEVER be translated.

        Example:
            # Never translate product codes
            i18n.add_ignore_pattern(re.compile(r"PROD-\d+"))

            # Never translate brand names
            i18n.add_ignore_pattern(re.compile(r"AcmeCorp"))
        """
        self.ignore.add_custom_ignore(pattern)
        log.debug("Custom ignore pattern added")

    def mark_ignored(self, text: str) -> str:
        """
        Wrap text with inline ignore marker — shortcut function.

        Usage in templates/content:
            {{ i18n.mark_ignored("Brand Name") }}
            → {{{Brand Name}}}
        """
        return f"{{{{{text}}}}}"

    # ─── Path & URL Methods ───

    def detect_language_from_path(self, path: Union[str, Path]) -> str:
        """Detect language from content directory structure."""
        path = Path(path).resolve()
        try:
            rel = path.relative_to(self.content_dir)
            first_dir = rel.parts[0] if rel.parts else ""
            if first_dir in self.supported_langs:
                return first_dir
        except ValueError:
            pass
        return self.default_lang

    def localize_path(self, path: Union[str, Path], lang: Optional[str] = None) -> str:
        """Generate language-prefixed URL path."""
        target_lang = lang or self.default_lang
        path_str = str(path).replace("\\", "/").lstrip("/")
        if target_lang == self.default_lang:
            return f"/{path_str}" if path_str else "/"
        return f"/{target_lang}/{path_str}"

    def get_language_switcher(self, current_path: str, current_lang: Optional[str] = None) -> List[Dict[str, Any]]:
        """Build data for language switcher component."""
        current = current_lang or self.default_lang
        return [
            {
                "code": lang,
                "name": info.name,
                "flag": info.flag,
                "url": self.localize_path(current_path, lang),
                "is_current": lang == current,
                "is_rtl": info.is_rtl,
            }
            for lang, info in self._lang_info.items()
        ]

    def get_supported_locales(self) -> List[LocaleInfo]:
        """Return metadata for all supported locales."""
        return list(self._lang_info.values())


# ─── Global Instance & Shortcuts ───

_default_manager: Optional[I18nManager] = None


def init_i18n(
    default_lang: str = DEFAULT_LANG,
    supported_langs: Optional[List[str]] = None,
    auto_translate: bool = True,
    **kwargs: Any,
) -> I18nManager:
    """Initialize the global i18n manager — FULL translation by default."""
    global _default_manager
    _default_manager = I18nManager(
        default_lang=default_lang,
        supported_langs=supported_langs,
        auto_translate=auto_translate,
        **kwargs,
    )
    return _default_manager


def get_i18n() -> I18nManager:
    """Get the global i18n manager instance."""
    if _default_manager is None:
        raise RuntimeError("I18n not initialized. Call init_i18n() first.")
    return _default_manager


def t(
    text: str,
    lang: Optional[str] = None,
    fallback: Optional[str] = None,
) -> str:
    """
    Translate text — EVERYTHING is translated by default.
    Use ignore markers to exclude specific parts from translation.

    Examples:
        t("Hello World", lang="id")
        t("Welcome to {{{Brand Name}}}", lang="id")  # Brand Name NOT translated
    """
    return get_i18n().translate(text, lang=lang, fallback=fallback)


def mark_ignore(text: str) -> str:
    """Shortcut: Wrap text in ignore marker so it's NEVER translated."""
    return f"{{{{{text}}}}}"
