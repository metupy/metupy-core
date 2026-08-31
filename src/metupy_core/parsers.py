"""
metupy_core.parsers
~~~~~~~~~~~~~~

Parser engine for Metupy content files.
Uses Lark grammar for .pym format parsing.
Delegates .py, .md, .rst to respective parsers.

Supported formats: .pym, .py, .md, .rst
Format: Frontmatter (key: value) --- + Content + Jinja2 tags
"""

import re
import ast
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from dataclasses import dataclass, field

try:
    from lark import Lark, Transformer, v_args
    LARK_AVAILABLE = True
except ImportError:
    LARK_AVAILABLE = False

from .logging import log
from .utils import get_ext


__all__ = [
    "ParsedContent",
    "BaseParser",
    "PymParser",
    "MarkdownParser",
    "RestructuredTextParser",
    "PythonParser",
    "get_parser_for_file",
    "parse_file",
]


# ─── Data Structures ───

@dataclass
class ParsedContent:
    """Result of parsing a content file."""
    metadata: Dict[str, Any] = field(default_factory=dict)
    content: str = ""
    raw_content: str = ""
    ast: Optional[Dict[str, Any]] = None
    format: str = ""
    has_errors: bool = False
    error_message: Optional[str] = None


# ─── Lark Grammar Definition ───

PYM_GRAMMAR = r"""
start: document
document: frontmatter? separator? content_section

// FRONTMATTER — key: value at start of file
frontmatter: (fm_line)+
fm_line: FIELD_KEY ":" _SP? FIELD_VALUE? _NEWLINE?
FIELD_KEY: /[A-Za-z0-9_-]+/
FIELD_VALUE: /.*?(?=\n|$)/
_NEWLINE: /\n/
_SP: /[ \t]+/

// SEPARATOR — ---
separator: SEP_LINE
SEP_LINE: /^[-─]{3,}\s*$/

// CONTENT — Template Nodes & Text
content_section: (node | text_node | line_comment)*
node: loop_block
    | conditional_block
    | variable
    | comment_block

// LINE COMMENT — // single line comment
line_comment: LINE_CM comment_text? _NEWLINE?
LINE_CM: "//"

// CONTROL STRUCTURES — Loops & Conditionals
loop_block: FOR_OPEN expression TAG_CLOSE content_section FOR_END_OPEN TAG_CLOSE
conditional_block: if_part elif_part* else_part? IF_END_OPEN TAG_CLOSE
if_part: IF_OPEN expression TAG_CLOSE content_section
elif_part: ELIF_OPEN expression TAG_CLOSE content_section
else_part: ELSE_OPEN TAG_CLOSE content_section

FOR_OPEN: "{%"i _SP? "for"i _SP?
FOR_END_OPEN: "{%"i _SP? "endfor"i _SP?
IF_OPEN: "{%"i _SP? "if"i _SP?
ELIF_OPEN: "{%"i _SP? "elif"i _SP?
ELSE_OPEN: "{%"i _SP? "else"i _SP?
IF_END_OPEN: "{%"i _SP? "endif"i _SP?

expression: /[^%}]+(?=%})/s

// VARIABLES — {{ var_name }}
variable: VAR_OPEN var_name VAR_CLOSE
var_name: /[^}]+/
VAR_OPEN: "{{"
VAR_CLOSE: "}}"

// COMMENT BLOCK — {# ... #}
comment_block: CM_OPEN comment_text CM_CLOSE
comment_text: /(?:.(?!#}))*/s
CM_OPEN: "{#"
CM_CLOSE: "#}"

// TEXT — Plain text
text_node: TEXT_FRAGMENT+
TEXT_FRAGMENT: /(?:[\/#<{]|{(?!{)|{(?!%)|<(?!\/)|\/(?!\/))?[^\/#<{]*/

// TERMINALS
TAG_CLOSE: "%}"

%ignore _NEWLINE
%ignore _SP
"""


# ─── AST Transformer ───

@v_args(inline=True)
class PymTransformer(Transformer):
    """Transform Lark parse tree into simplified AST dictionary."""

    def document(self, *parts):
        metadata = {}
        content = []
        state = "frontmatter"

        for part in parts:
            if isinstance(part, dict):
                if part.get("_type") == "separator":
                    state = "content"
                elif state == "frontmatter" and part.get("_type") == "fm_item":
                    metadata[part["key"]] = part["value"]
                elif state == "content":
                    content.append(part)

        return {"type": "document", "metadata": metadata, "content": content}

    def frontmatter(self, *lines):
        return list(lines)

    def fm_line(self, key, value):
        key_str = str(key).strip().lower()
        val_str = str(value).strip() if value else ""

        # Konversi tipe data otomatis
        if val_str.lower() in ("true", "false"):
            val_str = val_str.lower() == "true"
        elif val_str.isdigit():
            val_str = int(val_str)

        return {"_type": "fm_item", "key": key_str, "value": val_str}

    def separator(self):
        return {"_type": "separator"}

    def loop_block(self, expr, *body):
        return {
            "type": "for_loop",
            "expression": str(expr).strip(),
            "body": [b for b in body if isinstance(b, dict)],
        }

    def if_part(self, cond, *body):
        return {
            "type": "if",
            "condition": str(cond).strip(),
            "body": [b for b in body if isinstance(b, dict)],
        }

    def elif_part(self, cond, *body):
        return {
            "type": "elif",
            "condition": str(cond).strip(),
            "body": [b for b in body if isinstance(b, dict)],
        }

    def else_part(self, *body):
        return {
            "type": "else",
            "body": [b for b in body if isinstance(b, dict)],
        }

    def conditional_block(self, *branches):
        return {
            "type": "conditional",
            "branches": [b for b in branches if isinstance(b, dict)],
        }

    def variable(self, name):
        return {"type": "variable", "name": str(name).strip()}

    def comment_block(self, text):
        return {"type": "comment", "value": str(text).strip()}

    def text_node(self, *fragments):
        return {"type": "text", "value": "".join(map(str, fragments))}

    def var_name(self, name):
        return str(name).strip()

    def expression(self, expr):
        return str(expr).strip()


# ─── Base Parser ───

class BaseParser:
    """Abstract base class for all content parsers."""

    extensions: Tuple[str, ...] = ()
    has_metadata: bool = False

    def __init__(self, source_dir: Path | None = None):
        self.source_dir = source_dir or Path.cwd()

    def parse(self, text: str) -> ParsedContent:
        """Parse input text and return ParsedContent."""
        raise NotImplementedError("Subclasses must implement parse()")

    def parse_file(self, path: Path | str) -> ParsedContent:
        """Read file from disk and parse it."""
        path = Path(path).resolve()
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            result = self.parse(text)
            result.raw_content = text
            return result
        except IOError as e:
            log.error(f"Cannot read file: {path.name}: {e}")
            return ParsedContent(
                has_errors=True,
                error_message=str(e),
                format=self.extensions[0] if self.extensions else "",
            )


# ─── .pym Parser (Lark-based) ───

class PymParser(BaseParser):
    """
    Parser for Metupy native .pym format.
    Format: Frontmatter (key: value) --- + Markdown + Jinja2 tags
    Uses Lark grammar for full AST generation.
    """

    extensions = ("pym",)
    has_metadata = True

    def __init__(self, source_dir: Path | None = None):
        super().__init__(source_dir)
        self._parser: Optional[Lark] = None
        self._transformer = PymTransformer()

        if not LARK_AVAILABLE:
            log.warning("Lark not installed. Install with: pip install lark")

    def _get_parser(self) -> Optional[Lark]:
        """Lazy-initialize Lark parser."""
        if self._parser is None and LARK_AVAILABLE:
            try:
                self._parser = Lark(
                    PYM_GRAMMAR,
                    parser="lalr",
                    propagate_positions=True,
                    maybe_placeholders=False
                )
            except Exception as e:
                log.error(f"Failed to create Lark parser: {e}")
                return None
        return self._parser

    def parse(self, text: str) -> ParsedContent:
        """Parse .pym file — Frontmatter + Jinja2 + Markdown."""
        if not LARK_AVAILABLE:
            return ParsedContent(
                has_errors=True,
                error_message="Lark not installed",
                format="pym",
            )

        parser = self._get_parser()
        if not parser:
            return ParsedContent(
                has_errors=True,
                error_message="Parser initialization failed",
                format="pym",
            )

        try:
            tree = parser.parse(text)
            ast = self._transformer.transform(tree)

            # Buat konten teks untuk rendering dasar
            content_parts = []
            for node in ast.get("content", []):
                if isinstance(node, dict):
                    if node.get("type") == "text":
                        content_parts.append(node.get("value", ""))
                    elif node.get("type") == "variable":
                        content_parts.append(f"{{{{ {node.get('name', '')} }}}}")
                    elif node.get("type") in ("for_loop", "conditional"):
                        content_parts.append(f"<!-- {node.get('type')} -->")

            return ParsedContent(
                metadata=ast.get("metadata", {}),
                content="".join(content_parts).strip(),
                ast=ast,
                format="pym",
            )

        except Exception as e:
            log.error(f"Parse error: {e}")
            return ParsedContent(
                has_errors=True,
                error_message=str(e),
                format="pym",
            )


# ─── Markdown Parser ───

class MarkdownParser(BaseParser):
    """Parser for Markdown (.md) files with optional frontmatter."""

    extensions = ("md",)
    has_metadata = True

    _frontmatter_pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

    def _parse_frontmatter(self, fm_text: str) -> Dict[str, Any]:
        """Simple YAML-like frontmatter parser."""
        metadata: Dict[str, Any] = {}
        for line in fm_text.strip().splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip().lower()
                value = value.strip()
                if value.lower() in ("true", "false"):
                    value = value.lower() == "true"
                elif value.isdigit():
                    value = int(value)
                metadata[key] = value
        return metadata

    def parse(self, text: str) -> ParsedContent:
        """Parse markdown content with optional frontmatter."""
        metadata: Dict[str, Any] = {}
        content = text

        fm_match = self._frontmatter_pattern.match(text)
        if fm_match:
            metadata = self._parse_frontmatter(fm_match.group(1))
            content = text[fm_match.end():].lstrip("\n")

        return ParsedContent(
            metadata=metadata,
            content=content.strip(),
            format="markdown",
        )


# ─── reStructuredText Parser ───

class RestructuredTextParser(BaseParser):
    """Parser for reStructuredText (.rst) files."""

    extensions = ("rst",)
    has_metadata = True

    def parse(self, text: str) -> ParsedContent:
        """Parse RST content and extract field list metadata."""
        metadata: Dict[str, Any] = {}
        lines = text.splitlines()
        content_start = 0
        field_pattern = re.compile(r"^:(\w+):\s*(.*)$")

        for i, line in enumerate(lines):
            match = field_pattern.match(line)
            if match:
                metadata[match.group(1).lower()] = match.group(2)
                content_start = i + 1
            elif line.strip() and not line.startswith(" "):
                break

        content = "\n".join(lines[content_start:]).strip()
        return ParsedContent(metadata=metadata, content=content, format="rst")


# ─── Python File Parser ───

class PythonParser(BaseParser):
    """Parser for pure Python (.py) files used as content."""

    extensions = ("py",)
    has_metadata = True

    def parse(self, text: str) -> ParsedContent:
        """Parse .py file as content — extract docstring and uppercase variables."""
        metadata: Dict[str, Any] = {}
        content = ""

        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            log.warning(f"Syntax error in Python file: {e.msg}")
            return ParsedContent(has_errors=True, error_message=str(e), format="python")

        docstring = ast.get_docstring(tree)
        if docstring:
            content = docstring

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        try:
                            value = eval(compile(ast.Expression(body=node.value), "<string>", "eval"), {})
                            metadata[target.id.lower()] = value
                        except Exception:
                            pass

        return ParsedContent(metadata=metadata, content=content, format="python")


# ─── Parser Factory ───

_ALL_PARSERS = [PymParser, MarkdownParser, RestructuredTextParser, PythonParser]
_PARSER_MAP: Dict[str, type[BaseParser]] = {
    ext: parser for parser in _ALL_PARSERS for ext in parser.extensions
}


def get_parser_for_file(path: Path | str) -> Optional[type[BaseParser]]:
    """Return appropriate parser class for given file based on extension."""
    return _PARSER_MAP.get(get_ext(path))


def parse_file(path: Path | str, source_dir: Path | None = None) -> ParsedContent:
    """Convenience function: detect parser and parse file in one call."""
    path = Path(path)
    parser_cls = get_parser_for_file(path)

    if not parser_cls:
        log.warning(f"No parser available for file: {path.name}")
        return ParsedContent(has_errors=True, error_message=f"Unsupported format: {path.suffix}")

    parser = parser_cls(source_dir=source_dir)
    return parser.parse_file(path)
