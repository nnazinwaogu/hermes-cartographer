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
