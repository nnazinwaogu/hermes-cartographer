"""Plugin settings, coerced from the Hermes config accessor."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

_INJECT_MODES = ("first", "always", "off")


def _clamped_int(value: Any, default: int, low: int, high: int) -> int:
    """Coerce to int, clamp into ``[low, high]``; anything negative or unparsable is ``default``."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < 0:
        return default
    return max(low, min(high, number))


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        items: Iterable[Any] = (value,)
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        return ()
    return tuple(str(item).strip() for item in items if str(item).strip())


def _path_tuple(value: Any) -> tuple[Path, ...]:
    if isinstance(value, (str, Path)):
        items: Iterable[Any] = (value,)
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        return ()
    roots = []
    for item in items:
        text = str(item).strip()
        if text:
            roots.append(Path(text).expanduser())
    return tuple(roots)


@dataclass(frozen=True)
class Settings:
    """Resolved plugin configuration. Every value is already validated."""

    roots: tuple[Path, ...] = ()
    inject: str = "first"
    map_budget: int = 4000
    default_map_budget: int = 6000
    max_file_kb: int = 512
    max_files: int = 20000
    hook_index_ms: int = 500
    excludes: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, get_config: Callable[..., Any]) -> "Settings":
        """Build settings from ``ctx.get_config(key, default)``.

        Unknown or malformed values fall back to the documented defaults; nothing
        raises, because a broken config must not break the plugin.
        """
        defaults = cls()

        def get(key: str, default: Any = None) -> Any:
            try:
                return get_config(key, default)
            except Exception:  # noqa: BLE001 - a config backend must never crash us
                return default

        inject = str(get("inject", defaults.inject)).strip().lower()
        if inject not in _INJECT_MODES:
            inject = defaults.inject

        return cls(
            roots=_path_tuple(get("roots", [])),
            inject=inject,
            map_budget=_clamped_int(get("map_budget", defaults.map_budget), defaults.map_budget, 200, 20000),
            default_map_budget=_clamped_int(
                get("default_map_budget", defaults.default_map_budget),
                defaults.default_map_budget,
                200,
                20000,
            ),
            max_file_kb=_positive_int(get("max_file_kb", defaults.max_file_kb), defaults.max_file_kb),
            max_files=_positive_int(get("max_files", defaults.max_files), defaults.max_files),
            hook_index_ms=_clamped_int(
                get("hook_index_ms", defaults.hook_index_ms), defaults.hook_index_ms, 100, 5000
            ),
            excludes=_string_tuple(get("excludes", [])),
        )
