"""hermes-cartographer — code intelligence for Hermes Agent."""

from __future__ import annotations

import logging
from pathlib import Path

from . import schemas, tools
from .carto.errors import CartoError
from .carto.paths import detect_root, resolve_root
from .carto.settings import Settings

logger = logging.getLogger(__name__)

_SETTINGS: Settings | None = None


def _build_settings(ctx) -> Settings:
    get = getattr(ctx, "get_config", None)
    if get is None:
        return Settings()
    return Settings.from_config(get)


def _pick_root(settings: Settings) -> Path | None:
    for candidate in settings.roots:
        try:
            return resolve_root(candidate)
        except CartoError:
            continue
    try:
        return detect_root(Path.cwd())
    except Exception:  # noqa: BLE001 - a hook must never raise
        return None


def _inject_map(
    session_id,
    user_message,
    conversation_history,
    is_first_turn,
    model=None,
    platform=None,
    **kwargs,
):
    """pre_llm_call: inject a compact repo map. Must never raise."""
    try:
        settings = _SETTINGS or Settings()
        if settings.inject == "off" or (settings.inject == "first" and not is_first_turn):
            return None
        root = _pick_root(settings)
        if root is None:
            return None

        from .carto.indexer import open_store
        from .carto.maps import render_map

        store = open_store(root, settings, time_budget_ms=settings.hook_index_ms)
        try:
            # Reserve room for the header so the whole payload stays inside the
            # configured budget and never trips the output-spill path.
            text, info = render_map(store, root, max(200, settings.map_budget - 300))
        finally:
            store.close()

        if info["symbols"] == 0:
            return {
                "context": (
                    f"[cartographer] No index for {root} yet. Run "
                    f"`hermes carto index {root}` or call code_map to build one."
                )
            }

        header = (
            f"[cartographer] Repo map for {root} "
            f"({info['files']} files, {info['symbols']} symbols). "
            "Use symbol_find/symbol_refs before reading files; code_map to narrow.\n\n"
        )
        context = header + text
        if len(context) > settings.map_budget:
            cut = context.rfind("\n", 0, settings.map_budget)
            context = context[: cut if cut > 0 else settings.map_budget] + "\n…"
        return {"context": context}
    except Exception:  # noqa: BLE001 - a broken hook must never break a turn
        logger.debug("cartographer: map injection skipped", exc_info=True)
        return None


def _register_skills(ctx) -> None:
    skills_dir = Path(__file__).parent / "skills"
    if not skills_dir.is_dir():
        return
    for child in sorted(skills_dir.iterdir()):
        skill_md = child / "SKILL.md"
        if child.is_dir() and skill_md.exists():
            ctx.register_skill(child.name, skill_md)


def register(ctx) -> None:
    """Register the plugin's tools, hook and bundled skill.

    Must stay side-effect free: the catalog validator imports this module and
    calls ``register()`` against a recording stub with a throwaway HERMES_HOME.
    """
    global _SETTINGS
    _SETTINGS = _build_settings(ctx)
    tools.configure(_SETTINGS)

    ctx.register_tool(
        name="code_map",
        toolset="cartographer",
        schema=schemas.CODE_MAP,
        handler=tools.code_map,
        description="Token-budgeted repo symbol outline",
    )
    ctx.register_tool(
        name="symbol_find",
        toolset="cartographer",
        schema=schemas.SYMBOL_FIND,
        handler=tools.symbol_find,
        description="Find symbol definitions",
    )
    ctx.register_tool(
        name="symbol_refs",
        toolset="cartographer",
        schema=schemas.SYMBOL_REFS,
        handler=tools.symbol_refs,
        description="Find symbol references",
    )
    ctx.register_tool(
        name="symbol_rename",
        toolset="cartographer",
        schema=schemas.SYMBOL_RENAME,
        handler=tools.symbol_rename,
        description="AST-safe Python rename",
    )

    ctx.register_hook("pre_llm_call", _inject_map)
    _register_skills(ctx)
