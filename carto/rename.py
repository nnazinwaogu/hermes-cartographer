"""AST-safe cross-file rename for Python.

Only real identifier occurrences are edited: definition names, loaded/stored
names, arguments, and attribute accesses. Anything whose span is unreliable
(import aliases, ``global``/``nonlocal``, ``except ... as``, match patterns)
becomes a warning instead of an edit.
"""

from __future__ import annotations

import ast
import builtins
import difflib
import hashlib
import keyword
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CartoError
from .indexer import index_file
from .settings import Settings
from .store import Store

_DIFF_CAP = 20_000


@dataclass
class RenamePlan:
    old: str
    new: str
    files: list[str]
    replacements: int
    diff: str
    warnings: list[str] = field(default_factory=list)
    edits: dict[str, list[tuple[int, int, int, str]]] = field(default_factory=dict)
    forced_attributes: bool = False
    digests: dict[str, str] = field(default_factory=dict)


def _validate(old: str, new: str, store: Store) -> None:
    if not old or not new:
        raise CartoError("old and new are both required")
    if old == new:
        raise CartoError(f"old and new are the same name: '{old}'")
    if not old.isidentifier():
        raise CartoError(f"'{old}' is not a Python identifier")
    if not new.isidentifier():
        raise CartoError(f"'{new}' is not a Python identifier")
    if keyword.iskeyword(new):
        raise CartoError(f"'{new}' is a Python keyword")
    if new in dir(builtins):
        raise CartoError(f"'{new}' is a builtin; choose a different name")
    if store.has_symbol(new):
        raise CartoError(
            f"symbol '{new}' already exists; choose a name that does not shadow an existing symbol"
        )


def _char_offset(line: str, byte_offset: int) -> int:
    """Convert an ``ast`` UTF-8 byte column into a ``str`` index."""
    return len(line.encode("utf-8")[:byte_offset].decode("utf-8", "replace"))


def _byte_offset(line: str, char_offset: int) -> int:
    return len(line[:char_offset].encode("utf-8"))


def _definition_span(line: str, token: str, start_byte: int) -> tuple[int, int] | None:
    pattern = re.compile(r"\b" + re.escape(token) + r"\b")
    match = pattern.search(line, _char_offset(line, start_byte))
    if match is None:
        return None
    return _byte_offset(line, match.start()), _byte_offset(line, match.end())


def _collect_warnings(path: str, tree: ast.AST, old: str, warnings: list[str]) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.alias):
            if node.name == old or node.asname == old:
                warnings.append(f"{path}:{node.lineno}: import alias '{old}' is not renamed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)) and old in node.names:
            kind = "global" if isinstance(node, ast.Global) else "nonlocal"
            warnings.append(f"{path}:{node.lineno}: {kind} '{old}' declaration is not renamed")
        elif isinstance(node, ast.ExceptHandler) and node.name == old:
            warnings.append(f"{path}:{node.lineno}: 'except ... as {old}' is not renamed")
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name == old:
            warnings.append(f"{path}:{node.lineno}: match pattern name '{old}' is not renamed")
        elif isinstance(node, ast.keyword) and node.arg == old:
            warnings.append(f"{path}:{node.lineno}: keyword argument '{old}=' is not renamed")


def _collect_edits(
    path: str,
    tree: ast.AST,
    lines: list[str],
    old: str,
    new: str,
    include_attributes: bool,
    warnings: list[str],
) -> dict[tuple[int, int, int], str]:
    edits: dict[tuple[int, int, int], str] = {}

    def add(lineno: int, start: int, end: int) -> None:
        edits[(lineno, start, end)] = new

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name != old:
                continue
            line = lines[node.lineno - 1]
            span = _definition_span(line, old, node.col_offset)
            if span is None:
                warnings.append(f"{path}:{node.lineno}: could not locate definition of '{old}'; skipped")
                continue
            add(node.lineno, span[0], span[1])
        elif isinstance(node, ast.Name):
            if node.id == old:
                add(node.lineno, node.col_offset, node.end_col_offset)
        elif isinstance(node, ast.arg):
            if node.arg == old:
                add(node.lineno, node.col_offset, node.end_col_offset)
        elif isinstance(node, ast.Attribute):
            if node.attr != old or not include_attributes:
                continue
            if node.end_lineno != node.lineno:
                warnings.append(f"{path}:{node.lineno}: multi-line attribute '{old}' is not renamed")
                continue
            end = node.end_col_offset
            add(node.lineno, end - len(old.encode("utf-8")), end)

    return edits


def _apply_edits_to_text(text: str, edits: list[tuple[int, int, int, str]]) -> str:
    """Splice edits per line right-to-left on UTF-8 bytes (``ast`` columns are byte offsets)."""
    lines = text.splitlines(keepends=True)
    by_line: dict[int, list[tuple[int, int, str]]] = {}
    for lineno, start, end, replacement in edits:
        by_line.setdefault(lineno, []).append((start, end, replacement))

    for lineno, line_edits in by_line.items():
        raw = lines[lineno - 1].encode("utf-8")
        for start, end, replacement in sorted(line_edits, key=lambda item: item[0], reverse=True):
            raw = raw[:start] + replacement.encode("utf-8") + raw[end:]
        lines[lineno - 1] = raw.decode("utf-8")

    return "".join(lines)


def _unified_diff(path: str, old_text: str, new_text: str) -> str:
    return "".join(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=2,
        )
    )


def plan_rename(
    root: Path,
    store: Store,
    settings: Settings,
    old: str,
    new: str,
    include_attributes: bool = False,
    max_files: int = 500,
) -> RenamePlan:
    """Compute every edit a rename would make, plus the diff and its warnings.

    Raises:
        CartoError: on an invalid or unsafe request, or if a rewritten file
            would not parse (nothing is written by planning).
    """
    root = Path(root)
    _validate(old, new, store)

    definition_paths = store.python_definition_paths(old)
    if not definition_paths:
        raise CartoError(
            f"no Python definition of '{old}' is indexed; rename supports Python only"
        )
    warnings: list[str] = []

    is_method = any(row["kind"] == "method" for row in store.definitions(old, limit=1000))
    forced = is_method and not include_attributes

    plan = RenamePlan(
        old=old,
        new=new,
        files=[],
        replacements=0,
        diff="",
        warnings=warnings,
        edits={},
        forced_attributes=forced,
    )
    diffs: list[str] = []
    scan_paths = store.python_files()
    if len(scan_paths) > max_files:
        warnings.append(
            f"rename capped at {max_files} of {len(scan_paths)} files; "
            f"occurrences beyond the cap keep '{old}'"
        )
        scan_paths = scan_paths[:max_files]

    # Every scanned Python file is parsed once: definitions and references both
    # need editing, and any file may carry an unsafe construct worth a warning.
    for path in scan_paths:
        full_path = root / path
        try:
            raw = full_path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"{path}: cannot read as UTF-8 ({exc}); skipped")
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            warnings.append(f"{path}: does not parse; skipped")
            continue

        _collect_warnings(path, tree, old, plan.warnings)
        lines = text.splitlines()
        file_edits = _collect_edits(
            path, tree, lines, old, new, include_attributes or is_method, plan.warnings
        )
        if not file_edits:
            continue

        ordered = [
            (lineno, start, end, replacement)
            for (lineno, start, end), replacement in sorted(file_edits.items())
        ]
        new_text = _apply_edits_to_text(text, ordered)
        try:
            ast.parse(new_text)
        except (SyntaxError, ValueError) as exc:
            raise CartoError(
                f"rename would produce invalid syntax in {path}; nothing written"
            ) from exc

        plan.files.append(path)
        plan.edits[path] = ordered
        plan.digests[path] = hashlib.sha1(raw).hexdigest()
        plan.replacements += len(ordered)
        diffs.append(_unified_diff(path, text, new_text))

    plan.diff = "".join(diffs)
    if len(plan.diff) > _DIFF_CAP:
        plan.diff = plan.diff[:_DIFF_CAP] + "\n… diff truncated"
    return plan


def _atomic_write(path: Path, data: bytes) -> None:
    """Write *path* via a sibling temp file, keeping its permission bits.

    ``mkstemp`` creates 0600; without the chmod a rename would silently strip
    group/other read and the executable bit from the replaced source file.
    """
    mode = stat.S_IMODE(path.stat().st_mode)
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".carto-", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as temp:
            temp.write(data)
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def apply_rename(root: Path, store: Store, plan: RenamePlan, settings: Settings) -> int:
    """Write the planned files atomically and re-index only those files.

    Every file is re-read and checked against its plan-time digest before any
    write, so a plan applied after an external edit aborts with nothing
    changed instead of splicing stale byte offsets into new text.
    """
    root = Path(root)
    root_resolved = root.resolve()
    pending: dict[str, tuple[Path, bytes]] = {}

    for path in plan.files:
        full_path = root / path
        if not full_path.resolve().is_relative_to(root_resolved):
            raise CartoError(f"{path} resolves outside {root}; rename refused")
        try:
            raw = full_path.read_bytes()
        except OSError as exc:
            raise CartoError(f"cannot read {path}: {exc}") from exc
        expected = plan.digests.get(path)
        if expected is not None and hashlib.sha1(raw).hexdigest() != expected:
            raise CartoError(f"{path} changed since the rename was planned; nothing written")
        pending[path] = (full_path, raw)

    for path, (full_path, raw) in pending.items():
        text = raw.decode("utf-8")
        new_text = _apply_edits_to_text(text, plan.edits[path])
        ast.parse(new_text)
        _atomic_write(full_path, new_text.encode("utf-8"))
        index_file(store, root, path)

    return len(pending)
