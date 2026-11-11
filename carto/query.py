"""Query helpers over an open Store. Result dicts use root-relative paths and 1-based lines."""

from __future__ import annotations

from .errors import CartoError
from .store import Store

_MODES = ("exact", "prefix", "fuzzy")


def _definition_row(row: dict) -> dict:
    return {
        "path": row["path"],
        "line": row["lineno"],
        "kind": row["kind"],
        "qualname": row["qualname"],
        "signature": row["signature"],
        "parent": row["parent"],
    }


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
