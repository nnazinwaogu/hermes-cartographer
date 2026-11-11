"""Tool handlers.

Contract: every handler takes ``(args: dict, **kwargs)`` and returns a JSON
*string*, including on failure. Nothing is raised into the agent loop.
"""

from __future__ import annotations

import json
import logging
import os

from .carto.errors import CartoError
from .carto.indexer import open_store
from .carto.maps import render_map
from .carto.paths import resolve_root
from .carto.query import find_definitions, find_references
from .carto.settings import Settings

logger = logging.getLogger(__name__)

_SETTINGS: Settings | None = None


def configure(settings: Settings) -> None:
    """Install the settings ``register()`` derived from the Hermes config."""
    global _SETTINGS
    _SETTINGS = settings


def _error(message: str, hint: str) -> str:
    return json.dumps({"error": message, "hint": hint})


def _root_and_settings(args: dict, **kwargs):
    settings = _SETTINGS or Settings()
    raw = args.get("path") or (settings.roots[0] if settings.roots else os.getcwd())
    return resolve_root(raw), settings


def code_map(args: dict, **kwargs) -> str:
    """Return a byte-budgeted symbol outline of the repository at ``args["path"]``."""
    try:
        root, settings = _root_and_settings(args, **kwargs)
        budget = max(500, min(20000, int(args.get("budget") or settings.default_map_budget)))
        store = open_store(root, settings)
        try:
            text, info = render_map(store, root, budget, args.get("subpath"))
        finally:
            store.close()
        return json.dumps({"root": str(root), "text": text, **info})
    except CartoError as exc:
        return _error(str(exc), "pass path=<existing directory> or set the plugin roots config")
    except Exception as exc:  # noqa: BLE001 - a handler must never raise
        logger.exception("code_map failed")
        return _error(f"code_map failed: {exc}", "check the arguments and try again")


def _limit(value, default: int, high: int = 500) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(high, number))


def symbol_find(args: dict, **kwargs) -> str:
    """Find where a symbol is defined, with exact/prefix/fuzzy matching."""
    try:
        name = str(args.get("name") or "").strip()
        if not name:
            return _error("name is required", "pass name=<symbol name>")
        root, settings = _root_and_settings(args, **kwargs)
        store = open_store(root, settings)
        try:
            definitions = find_definitions(
                store,
                name,
                kind=args.get("kind") or None,
                limit=_limit(args.get("limit"), 50),
                mode=str(args.get("mode") or "exact"),
            )
        finally:
            store.close()
        return json.dumps({"query": name, "definitions": definitions, "count": len(definitions)})
    except CartoError as exc:
        return _error(str(exc), "check the name; mode is exact, prefix or fuzzy")
    except Exception as exc:  # noqa: BLE001 - a handler must never raise
        logger.exception("symbol_find failed")
        return _error(f"symbol_find failed: {exc}", "check the arguments and try again")


def symbol_refs(args: dict, **kwargs) -> str:
    """List references to a name: AST-precise for Python, on-disk scan elsewhere."""
    try:
        name = str(args.get("name") or "").strip()
        if not name:
            return _error("name is required", "pass name=<symbol name>")
        root, settings = _root_and_settings(args, **kwargs)
        store = open_store(root, settings)
        try:
            refs, meta = find_references(
                store,
                name,
                limit=_limit(args.get("limit"), 100),
                include_attributes=bool(args.get("include_attributes")),
            )
        finally:
            store.close()
        return json.dumps(
            {
                "name": name,
                "refs": refs,
                "count": meta["count"],
                "truncated": meta["truncated"],
                "scanned_files": meta["scanned_files"],
            }
        )
    except CartoError as exc:
        return _error(str(exc), "check the name and the path")
    except Exception as exc:  # noqa: BLE001 - a handler must never raise
        logger.exception("symbol_refs failed")
        return _error(f"symbol_refs failed: {exc}", "check the arguments and try again")
