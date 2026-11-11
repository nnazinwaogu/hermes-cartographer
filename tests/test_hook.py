"""pre_llm_call injection: modes, budget, fresh-root hint, never-raise, timing."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from _util import FIXTURES, load_plugin, load_submodule

indexer = load_submodule("carto.indexer")
paths = load_submodule("carto.paths")
settings_module = load_submodule("carto.settings")

plugin = load_plugin()
Settings = settings_module.Settings

ROOT = FIXTURES / "project_a"


class StubContext:
    def __init__(self):
        self.tools: list[str] = []
        self.hooks: list[str] = []
        self.skills: list[tuple] = []
        self.commands: list[str] = []

    def register_tool(self, name, *args, **kwargs):
        self.tools.append(str(name))

    def register_hook(self, hook_name, callback, *, hold_stream=False):
        self.hooks.append(str(hook_name))

    def register_skill(self, name, path, *args, **kwargs):
        self.skills.append((str(name), Path(path)))

    def register_command(self, name, *args, **kwargs):
        self.commands.append(str(name))

    def register_cli_command(self, name, *args, **kwargs):
        self.commands.append(str(name))

    def get_config(self, key, default=None):
        return default


class HookTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        db = Path(self._tmp.name) / "index.db"
        patcher = mock.patch.object(indexer, "db_path_for", return_value=db)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db = db

    def hook(self, settings, is_first_turn=True):
        with mock.patch.object(plugin, "_SETTINGS", settings):
            return plugin._inject_map(None, "hi", [], is_first_turn)

    def settings(self, **kwargs):
        return Settings(roots=(ROOT,), **kwargs)

    def test_inject_modes_and_budget(self):
        self.assertIsNotNone(self.hook(self.settings(inject="first"), is_first_turn=True))
        self.assertIsNone(self.hook(self.settings(inject="first"), is_first_turn=False))
        self.assertIsNotNone(self.hook(self.settings(inject="always"), is_first_turn=False))
        self.assertIsNone(self.hook(self.settings(inject="off"), is_first_turn=True))
        context = self.hook(self.settings(map_budget=600))
        self.assertLessEqual(len(context["context"]), 600)

    def test_inject_first_only_on_first_turn(self):
        context = self.hook(self.settings(inject="first"), is_first_turn=True)
        self.assertIn("[cartographer]", context["context"])
        self.assertIn("class Engine", context["context"])
        self.assertIsNone(self.hook(self.settings(inject="first"), is_first_turn=False))

    def test_inject_always_every_turn(self):
        for first in (True, False):
            context = self.hook(self.settings(inject="always"), is_first_turn=first)
            self.assertIsNotNone(context)

    def test_inject_off_never(self):
        self.assertIsNone(self.hook(self.settings(inject="off"), is_first_turn=True))

    def test_payload_stays_inside_budget(self):
        context = self.hook(self.settings(map_budget=600))
        self.assertLessEqual(len(context["context"]), 600)

    def test_payload_stays_inside_tiny_budget(self):
        context = self.hook(self.settings(map_budget=200))
        self.assertLessEqual(len(context["context"]), 200)

    def test_fresh_root_budget_gives_hint(self):
        with mock.patch.object(indexer, "sync", return_value=None):
            context = self.hook(self.settings())
        self.assertIn("No index for", context["context"])
        self.assertIn("hermes carto index", context["context"])

    def test_never_raises(self):
        with mock.patch.object(indexer, "open_store", side_effect=RuntimeError("db gone")):
            self.assertIsNone(self.hook(self.settings()))

    def test_steady_state_is_fast(self):
        self.hook(self.settings())
        started = time.monotonic()
        context = self.hook(self.settings())
        elapsed = time.monotonic() - started
        self.assertIsNotNone(context)
        self.assertLess(elapsed, 2.0)


class DetectRootTests(unittest.TestCase):
    def test_finds_nearest_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            nested = root / "src" / "pkg"
            nested.mkdir(parents=True)
            self.assertEqual(paths.detect_root(nested), root.resolve())

    def test_returns_start_without_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = Path(tmp)
            self.assertEqual(paths.detect_root(start), start.resolve())


class SkillTests(unittest.TestCase):
    def test_skill_registered_and_small(self):
        ctx = StubContext()
        plugin.register(ctx)
        self.assertIn("pre_llm_call", ctx.hooks)
        names = dict(ctx.skills)
        self.assertIn("cartographer", names)
        skill = names["cartographer"]
        self.assertTrue(skill.is_file(), "register_skill needs a Path to an existing SKILL.md")
        text = skill.read_text(encoding="utf-8")
        self.assertLess(len(text.splitlines()), 60)
        self.assertIn("name: cartographer", text)
        self.assertIn("dry_run=false", text)


if __name__ == "__main__":
    unittest.main()
