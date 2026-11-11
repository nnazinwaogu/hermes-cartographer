"""Shared test helpers: plugin loading and a parser for our flat plugin.yaml subset."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN_MODULE_NAME = "hermes_cartographer_under_test"


def load_plugin():
    """Import the plugin package exactly the way the Hermes loader/probe does."""
    if PLUGIN_MODULE_NAME in sys.modules:
        return sys.modules[PLUGIN_MODULE_NAME]
    spec = importlib.util.spec_from_file_location(
        PLUGIN_MODULE_NAME,
        REPO / "__init__.py",
        submodule_search_locations=[str(REPO)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PLUGIN_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def load_submodule(name: str):
    """Import ``<plugin>.<name>``, e.g. ``carto.languages``."""
    load_plugin()
    return importlib.import_module(f"{PLUGIN_MODULE_NAME}.{name}")


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _scalar(text: str):
    """Parse the scalar forms our manifest uses."""
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return json.loads(text)
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1]
    if text == "[]":
        return []
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [] if not inner else [_scalar(part.strip()) for part in inner.split(",")]
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


def load_manifest(path: Path = REPO / "plugin.yaml") -> dict:
    """Parse block mappings, block lists, flow lists and scalars. Rejects anything else."""
    lines = [
        (lineno, raw)
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if raw.strip() and not raw.lstrip().startswith("#")
    ]
    root: dict = {}
    stack: list[tuple[int, object]] = [(-1, root)]

    for index, (lineno, raw) in enumerate(lines):
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        container = stack[-1][1]

        if line.startswith("- "):
            if not isinstance(container, list):
                raise AssertionError(f"plugin.yaml:{lineno}: list item outside a list")
            container.append(_scalar(line[2:].strip()))
            continue

        key, sep, rest = line.partition(":")
        if not sep or not key.strip():
            raise AssertionError(f"plugin.yaml:{lineno}: expected 'key: value'")
        key, rest = key.strip(), rest.strip()
        if not isinstance(container, dict):
            raise AssertionError(f"plugin.yaml:{lineno}: mapping key inside a list")

        if rest:
            container[key] = _scalar(rest)
            continue

        following = lines[index + 1] if index + 1 < len(lines) else None
        if following is not None:
            next_raw = following[1]
            next_indent = len(next_raw) - len(next_raw.lstrip(" "))
            child: object = [] if next_indent > indent and next_raw.strip().startswith("- ") else {}
        else:
            child = {}
        container[key] = child
        stack.append((indent, child))

    return root
