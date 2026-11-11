"""hermes-cartographer — code intelligence for Hermes Agent."""

from __future__ import annotations

import logging
import shlex
import sys
from pathlib import Path

from . import schemas, tools
from .carto.errors import CartoError
from .carto.paths import detect_root, pick_root, resolve_root
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
        from .carto.maps import clamp_budget, render_map

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
            # Keep the ellipsis inside the budget too: a callback payload that
            # overflows trips the spill path and costs the model a file read.
            limit = max(1, settings.map_budget - 2)
            cut = context.rfind("\n", 0, limit)
            context = context[: cut if cut > 0 else limit] + "\n…"
        return {"context": context}
    except Exception:  # noqa: BLE001 - a broken hook must never break a turn
        logger.debug("cartographer: map injection skipped", exc_info=True)
        return None


_HELP_TEXT = """carto — code intelligence

  carto index [path]              build or refresh the index
  carto map [path] [--budget N]   print a budgeted symbol outline
  carto find <name> [path]        find definitions (file:line kind qualname)
  carto refs <name> [path] [--attrs]  list references
  carto stats [path]              show index statistics
  carto help                      show this help"""


def _default_root(settings: Settings) -> Path:
    return pick_root(settings)


def _format_index(report) -> str:
    parts = [
        f"indexed {report.indexed} files",
        f"{report.symbols} symbols",
        f"{report.refs} refs",
        f"{report.duration_ms} ms",
    ]
    if report.removed:
        parts.append(f"{report.removed} removed")
    if report.truncated:
        parts.append("truncated at the time budget")
    return " · ".join(parts)


def _format_stats(data: dict) -> str:
    if not data["indexed"]:
        return f"root: {data['root']}\nno index yet — run `hermes carto index {data['root']}`"
    languages = ", ".join(f"{name} {count}" for name, count in sorted(data["languages"].items()))
    kinds = ", ".join(f"{name} {count}" for name, count in sorted(data["kinds"].items()))
    kilobytes = data["db_bytes"] / 1024
    return "\n".join(
        [
            f"root: {data['root']}",
            f"index: {data['db']} ({kilobytes:.1f} KB)",
            f"files: {data['files']}  symbols: {data['symbols']}  refs: {data['refs']}",
            f"languages: {languages or 'none'}",
            f"kinds: {kinds or 'none'}",
            f"last index: {data['last_index_at'] or 'never'} ({data['last_index_ms'] or '-'} ms)",
        ]
    )


def _format_definitions(store, name: str) -> str:
    from .carto.query import find_definitions

    rows = find_definitions(store, name)
    if not rows:
        return f"no definition of '{name}'"
    return "\n".join(
        f"{row['path']}:{row['line']}  {row['kind']} {row['qualname']}{row['signature']}"
        for row in rows
    )


def _format_references(store, name: str, attrs: bool) -> str:
    from .carto.query import find_references

    rows, meta = find_references(store, name, include_attributes=attrs)
    if not rows:
        return f"no references to '{name}'"
    lines = [f"{row['path']}:{row['line']}:{row['column']}  {row['snippet']}" for row in rows]
    notes = []
    if meta["scanned_files"]:
        notes.append(f"scanned {meta['scanned_files']} non-Python files")
    if meta["truncated"]:
        notes.append("truncated")
    if notes:
        lines.append("(" + ", ".join(notes) + ")")
    return "\n".join(lines)


def _run(command: str, settings: Settings, root=None, name=None, budget=None, attrs=False) -> str:
    """One implementation of every subcommand; the slash and CLI surfaces only parse into it."""
    from .carto.indexer import open_store, stats, sync
    from .carto.maps import clamp_budget, render_map

    root_path = resolve_root(root or _default_root(settings))
    if command == "index":
        return _format_index(sync(root_path, settings))
    if command == "stats":
        return _format_stats(stats(root_path, settings))
    if command not in ("map", "find", "refs"):
        raise CartoError(f"unknown subcommand '{command}'")
    if command in ("find", "refs") and not name:
        raise CartoError(f"usage: carto {command} <name>")

    store = open_store(root_path, settings)
    try:
        if command == "map":
            text, _info = render_map(
                store, root_path, clamp_budget(budget, settings.default_map_budget)
            )
            return text.rstrip("\n")
        if command == "find":
            return _format_definitions(store, name)
        return _format_references(store, name, attrs)
    finally:
        store.close()


def _parse_slash_args(command: str, tokens: list[str]):
    root = name = None
    budget = None
    attrs = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--attrs":
            attrs = True
            index += 1
            continue
        if token == "--budget" or token.startswith("--budget="):
            if token.startswith("--budget="):
                value = token.split("=", 1)[1]
                index += 1
            else:
                index += 1
                if index >= len(tokens):
                    raise ValueError("--budget needs a number")
                value = tokens[index]
                index += 1
            budget = int(value)
            continue
        if token.startswith("-"):
            raise ValueError(f"unknown option '{token}'")
        if command in ("find", "refs") and name is None:
            name = token
        elif root is None:
            root = token
        else:
            raise ValueError(f"unexpected argument '{token}'")
        index += 1
    if command in ("find", "refs") and not name:
        raise ValueError(f"usage: carto {command} <name>")
    return root, name, budget, attrs


def _split_args(raw: str) -> list[str]:
    """Tokenize slash arguments without eating Windows path backslashes."""
    try:
        tokens = shlex.split(raw, posix=False)
    except ValueError:
        tokens = raw.split()
    return [
        token[1:-1] if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'" else token
        for token in tokens
    ]


def _slash(raw_args: str) -> str:
    """`/carto` handler: chat-ready text, never raises."""
    try:
        settings = _SETTINGS or Settings()
        tokens = _split_args(raw_args or "")
        if not tokens or tokens[0] in ("help", "-h", "--help"):
            return _HELP_TEXT
        command = tokens[0]
        if command not in ("index", "map", "find", "refs", "stats"):
            return f"carto: unknown subcommand '{command}'\n\n{_HELP_TEXT}"
        root, name, budget, attrs = _parse_slash_args(command, tokens[1:])
        return _run(command, settings, root=root, name=name, budget=budget, attrs=attrs)
    except CartoError as exc:
        return f"carto: {exc}"
    except ValueError as exc:
        return f"carto: {exc}"
    except Exception as exc:  # noqa: BLE001 - a slash command must never raise
        logger.debug("cartographer: /carto failed", exc_info=True)
        return f"carto: failed: {exc}"


def _setup_cli(parser) -> None:
    subparsers = parser.add_subparsers(dest="carto_command")

    index = subparsers.add_parser("index", help="Build or refresh the index")
    index.add_argument("path", nargs="?", default=None, help="Repository root (default: workspace)")

    map_parser = subparsers.add_parser("map", help="Print a budgeted symbol outline")
    map_parser.add_argument("path", nargs="?", default=None)
    map_parser.add_argument("--budget", type=int, default=None, help="Character budget")

    find = subparsers.add_parser("find", help="Find symbol definitions")
    find.add_argument("name")
    find.add_argument("path", nargs="?", default=None)

    refs = subparsers.add_parser("refs", help="List references to a name")
    refs.add_argument("name")
    refs.add_argument("path", nargs="?", default=None)
    refs.add_argument("--attrs", action="store_true", help="Include attribute accesses")

    stats = subparsers.add_parser("stats", help="Show index statistics")
    stats.add_argument("path", nargs="?", default=None)


def _cli(args) -> int:
    """`hermes carto ...` handler: prints text and returns the process exit code."""
    command = getattr(args, "carto_command", None)
    settings = _SETTINGS or Settings()
    if command is None:
        print(_HELP_TEXT)
        return 0
    try:
        text = _run(
            command,
            settings,
            root=getattr(args, "path", None),
            name=getattr(args, "name", None),
            budget=getattr(args, "budget", None),
            attrs=getattr(args, "attrs", False),
        )
    except CartoError as exc:
        print(f"carto: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - report, never traceback
        logger.debug("cartographer: hermes carto failed", exc_info=True)
        print(f"carto: failed: {exc}", file=sys.stderr)
        return 1
    print(text)
    return 0


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
    ctx.register_command(
        "carto",
        _slash,
        description="Code intelligence",
        args_hint="[index|map|find|refs|stats]",
    )
    ctx.register_cli_command(
        "carto",
        help="Cartographer code intelligence",
        setup_fn=_setup_cli,
        handler_fn=_cli,
    )
    _register_skills(ctx)
