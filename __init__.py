"""hermes-cartographer — code intelligence for Hermes Agent."""

from __future__ import annotations

import logging

from . import schemas, tools
from .carto.settings import Settings

logger = logging.getLogger(__name__)

_SETTINGS: Settings | None = None


def _build_settings(ctx) -> Settings:
    get = getattr(ctx, "get_config", None)
    if get is None:
        return Settings()
    return Settings.from_config(get)


def register(ctx) -> None:
    """Register the plugin's tools.

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
