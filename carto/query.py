"""Query helpers over an open Store. Result dicts use root-relative paths and 1-based lines."""

from __future__ import annotations

import re

from .errors import CartoError
from .store import Store

_MODES = ("exact", "prefix", "fuzzy")
_MAX_SCAN_FILES = 2000


def _definition_row(row: dict) -> dict:
    return {
        "path": row["path"],
        "line": row["lineno"],
        "kind": row["kind"],
        "qualname": row["qualname"],
        "signature": row["signature"],
        "parent": row["parent"],
    }


def _ref_row(path: str, line: int, column: int, kind: str, snippet: str) -> dict:
    return {"path": path, "line": line, "column": column, "kind": kind, "snippet": snippet}


def outline(store: Store, subpath: str | None = None) -> list[dict]:
    """Symbol rows ordered by ``(path, lineno)`` — the repo map's input."""
    return store.outline_rows(subpath)


def find_definitions(
    store: Store,
    name: str,
    kind: str | None = None,
    limit: int = 50,
    mode: str = "exact",
) -> list[dict]:
    """Find definitions by exact name, prefix, or substring.

    Order is deterministic: shorter names first, then path, then line.
    """
    if mode not in _MODES:
        raise CartoError(f"unknown mode '{mode}'; use one of {', '.join(_MODES)}")
    query = (name or "").strip()
    if not query:
        raise CartoError("name is required")
    rows = store.definitions(query, limit=max(1, limit), kind=kind, mode=mode)
    return [_definition_row(row) for row in rows]


def find_references(
    store: Store,
    name: str,
    limit: int = 100,
    include_attributes: bool = False,
    scan_generic: bool = True,
    max_scan_bytes: int = 20_000_000,
) -> tuple[list[dict], dict]:
    """Return references to *name* plus ``(count, truncated, scanned_files)`` metadata.

    Indexed refs come first; non-Python files are then scanned on disk for
    whole-word hits outside the definition line. A name with no indexed
    definition is still searched — references are never pruned by name.
    """
    query = (name or "").strip()
    if not query:
        raise CartoError("name is required")

    results: list[dict] = []
    seen: set[tuple[str, int, int, str]] = set()
    truncated = False

    def add(path: str, line: int, column: int, kind: str, snippet: str) -> None:
        key = (path, line, column, kind)
        if key not in seen:
            seen.add(key)
            results.append(_ref_row(path, line, column, kind, snippet))

    # One extra row tells us whether the index alone already overflows the limit,
    # without loading every reference to a common name such as "self".
    rows = store.references(
        query, limit=limit + 1, include_attributes=include_attributes
    )
    if len(rows) > limit:
        truncated = True
    for row in rows[:limit]:
        add(row["path"], row["lineno"], row["col"], row["kind"], row["snippet"])

    scanned_files = 0
    if scan_generic and len(query) >= 2:
        pattern = re.compile(r"\b" + re.escape(query) + r"\b")
        definition_lines = {
            (row["path"], row["lineno"])
            for row in store.definitions(query, limit=1000, mode="exact")
        }
        scanned_bytes = 0
        for path, _lang in store.non_python_files():
            if len(results) >= limit:
                break
            if scanned_bytes >= max_scan_bytes or scanned_files >= _MAX_SCAN_FILES:
                truncated = True
                break
            try:
                raw = (store.root / path).read_bytes()
            except OSError:
                continue
            scanned_bytes += len(raw)
            scanned_files += 1
            text = raw.decode("utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                if (path, lineno) in definition_lines:
                    continue
                for match in pattern.finditer(line):
                    add(path, lineno, match.start(), "name", line.strip()[:160])
                    if len(results) >= limit:
                        truncated = True
                        break
                if len(results) >= limit:
                    break

    results.sort(key=lambda row: (row["path"], row["line"], row["column"]))
    if len(results) > limit:
        results = results[:limit]
        truncated = True
    return results, {"count": len(results), "truncated": truncated, "scanned_files": scanned_files}
