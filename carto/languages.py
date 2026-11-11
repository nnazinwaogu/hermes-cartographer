"""Language detection and per-file scanning.

Python is AST-precise; every other supported language gets a defs-only
regex scan. A file that cannot be parsed yields an empty scan, never an
exception: one broken file must not break the index.
"""

from __future__ import annotations

import ast
import builtins
import re
from dataclasses import dataclass, field

_BUILTIN_NAMES = frozenset(dir(builtins))

_LANG_BY_SUFFIX = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "java",
    ".kts": "java",
    ".c": "c",
    ".h": "c",
    ".cc": "c",
    ".cpp": "c",
    ".hpp": "c",
    ".cs": "c",
}


@dataclass(frozen=True)
class Symbol:
    """One definition. ``qualname`` is dotted; ``parent`` is the enclosing symbol name."""

    path: str
    name: str
    qualname: str
    kind: str
    lineno: int
    end_lineno: int
    signature: str = ""
    parent: str = ""


@dataclass(frozen=True)
class Ref:
    """One name occurrence. ``col`` is the 0-based UTF-8 byte offset ast reports."""

    path: str
    name: str
    lineno: int
    col: int
    kind: str
    snippet: str


@dataclass
class FileScan:
    symbols: list[Symbol] = field(default_factory=list)
    refs: list[Ref] = field(default_factory=list)
    lines: int = 0


def detect_lang(name: str) -> str:
    """Return the language for a filename, or ``"other"``."""
    lowered = name.lower()
    for suffix, lang in _LANG_BY_SUFFIX.items():
        if lowered.endswith(suffix):
            return lang
    return "other"


def _unparse(node: ast.AST, fallback: str) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 - unparse is best-effort for display only
        return fallback


def _signature(node: ast.AST) -> str:
    args = node.args
    positional = list(args.posonlyargs) + list(args.args)
    first_default = len(positional) - len(args.defaults)
    parts: list[str] = []

    for index, arg in enumerate(positional):
        text = arg.arg
        if arg.annotation is not None:
            text += ": " + _unparse(arg.annotation, "...")
        if index >= first_default:
            text += "=" + _unparse(args.defaults[index - first_default], "...")
        parts.append(text)

    if args.vararg is not None:
        parts.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        parts.append("*")

    for index, arg in enumerate(args.kwonlyargs):
        text = arg.arg
        if arg.annotation is not None:
            text += ": " + _unparse(arg.annotation, "...")
        default = args.kw_defaults[index]
        if default is not None:
            text += "=" + _unparse(default, "...")
        parts.append(text)

    if args.kwarg is not None:
        parts.append("**" + args.kwarg.arg)

    return "(" + ", ".join(parts) + ")"


def _add_symbol(
    out: list[Symbol],
    rel_path: str,
    node: ast.AST,
    name: str,
    kind: str,
    qualname: str,
    parent: str,
    signature: str = "",
) -> None:
    out.append(
        Symbol(
            path=rel_path,
            name=name,
            qualname=qualname,
            kind=kind,
            lineno=node.lineno,
            end_lineno=getattr(node, "end_lineno", None) or node.lineno,
            signature=signature,
            parent=parent,
        )
    )


def _walk_symbols(
    body: list[ast.stmt], rel_path: str, scope: str, parent: str, out: list[Symbol]
) -> None:
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = scope + node.name
            _add_symbol(
                out,
                rel_path,
                node,
                node.name,
                "method" if parent else "function",
                qualname,
                parent,
                _signature(node),
            )
            _walk_symbols(node.body, rel_path, qualname + ".", node.name, out)
        elif isinstance(node, ast.ClassDef):
            qualname = scope + node.name
            _add_symbol(out, rel_path, node, node.name, "class", qualname, parent)
            _walk_symbols(node.body, rel_path, qualname + ".", node.name, out)
        elif not scope:
            target = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
            elif isinstance(node, ast.AnnAssign):
                target = node.target
            if isinstance(target, ast.Name) and target.id.isupper():
                _add_symbol(out, rel_path, node, target.id, "constant", target.id, "")


def _snippet(lines: list[str], lineno: int) -> str:
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1].strip()[:160]
    return ""


def collect_python_refs(tree: ast.AST, rel_path: str, lines: list[str]) -> list[Ref]:
    """Collect loaded names and attribute accesses with exact positions.

    ``ast`` reports columns as UTF-8 byte offsets; an attribute's start is its
    end offset minus the name's encoded length, because the attribute has no
    offset of its own.
    """
    seen: set[tuple[str, int, int, str]] = set()
    refs: list[Ref] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            name = node.id
            if not isinstance(node.ctx, ast.Load) or len(name) <= 1 or name in _BUILTIN_NAMES:
                continue
            kind = "name"
            line = node.lineno
            col = node.col_offset
        elif isinstance(node, ast.Attribute):
            name = node.attr
            if len(name) <= 1:
                continue
            kind = "attr"
            # The attribute name sits at the END of the expression, so a value
            # wrapped over lines (``(\n x\n).upper()``) puts it on end_lineno;
            # node.lineno would point at the opening bracket.
            line = node.end_lineno or node.lineno
            col = node.end_col_offset - len(name.encode("utf-8"))
        else:
            continue

        key = (name, line, col, kind)
        if key in seen:
            continue
        seen.add(key)
        refs.append(Ref(rel_path, name, line, col, kind, _snippet(lines, line)))

    refs.sort(key=lambda ref: (ref.lineno, ref.col))
    return refs


def scan_python(rel_path: str, text: str) -> FileScan:
    """Collect Python symbols and references. A broken file yields an empty scan."""
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return FileScan(lines=len(lines))

    symbols: list[Symbol] = []
    _walk_symbols(tree.body, rel_path, "", "", symbols)
    return FileScan(
        symbols=symbols,
        refs=collect_python_refs(tree, rel_path, lines),
        lines=len(lines),
    )


@dataclass(frozen=True)
class _Pattern:
    regex: re.Pattern[str]
    kind: str


_JS_PATTERNS = (
    _Pattern(re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\("), "function"),
    _Pattern(re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)"), "class"),
    _Pattern(
        re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\()"),
        "constant",
    ),
    _Pattern(re.compile(r"\b(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)"), "type"),
)

_GO_PATTERNS = (
    _Pattern(re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\("), "function"),
    _Pattern(re.compile(r"^type\s+([A-Za-z_]\w*)\s+(?:struct|interface)"), "type"),
)

_RUST_PATTERNS = (
    _Pattern(re.compile(r"\bfn\s+([A-Za-z_]\w*)"), "function"),
    _Pattern(re.compile(r"\b(?:struct|enum|trait)\s+([A-Za-z_]\w*)"), "type"),
)

_C_PATTERNS = (_Pattern(re.compile(r"\b(?:class|interface|enum|struct)\s+(\w+)"), "class"),)

_PATTERNS_BY_LANG = {
    "javascript": _JS_PATTERNS,
    "typescript": _JS_PATTERNS,
    "go": _GO_PATTERNS,
    "rust": _RUST_PATTERNS,
    "java": _C_PATTERNS,
    "c": _C_PATTERNS,
}

_MAX_SCANNED_LINE = 500


def scan_generic(rel_path: str, text: str, lang: str) -> FileScan:
    """Defs-only regex scan for non-Python languages. First match per line wins."""
    patterns = _PATTERNS_BY_LANG.get(lang, ())
    lines = text.splitlines()
    symbols: list[Symbol] = []
    if patterns:
        for index, line in enumerate(lines, 1):
            if len(line) > _MAX_SCANNED_LINE:
                continue
            for pattern in patterns:
                match = pattern.regex.search(line)
                if match:
                    name = match.group(1)
                    symbols.append(
                        Symbol(
                            path=rel_path,
                            name=name,
                            qualname=name,
                            kind=pattern.kind,
                            lineno=index,
                            end_lineno=index,
                        )
                    )
                    break
    return FileScan(symbols=symbols, lines=len(lines))
