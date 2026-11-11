"""Repo-map rendering: indentation, budget truncation and the empty-index text."""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from _util import FIXTURES, load_submodule

indexer = load_submodule("carto.indexer")
maps = load_submodule("carto.maps")
settings_module = load_submodule("carto.settings")
store_module = load_submodule("carto.store")

Settings = settings_module.Settings
FOOTER = re.compile(
    r"^… \+(?P<symbols>\d+) symbols in (?P<files>\d+) files not shown\. "
    r"Narrow the path or raise map_budget\.$"
)


class MapTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "repo"
        shutil.copytree(FIXTURES / "project_a", self.root)
        self.db = Path(self._tmp.name) / "index.db"
        indexer.sync(self.root, Settings(), db_path=self.db)
        self.store = store_module.Store(self.db, self.root)
        self.addCleanup(self.store.close)

    def test_indentation(self):
        text, info = maps.render_map(self.store, self.root, 10000)
        lines = text.splitlines()
        self.assertIn("  class Engine", lines)
        self.assertIn("    def run(self, *units, retries: int=1, **options)", lines)
        self.assertIn("  def build(name: str, engine: Engine=None)", lines)
        self.assertFalse(info["truncated"])

    def test_file_header_names_line_count(self):
        text, _info = maps.render_map(self.store, self.root, 10000)
        self.assertIn("core.py  (19)", text.splitlines())

    def test_budget_truncation(self):
        budget = 100
        text, info = maps.render_map(self.store, self.root, budget)

        self.assertTrue(info["truncated"])
        body, _, footer = text.rstrip("\n").rpartition("\n")
        self.assertLessEqual(len(body) + 1, budget)
        match = FOOTER.match(footer)
        self.assertIsNotNone(match, footer)
        total_symbols = len(self.store.outline_rows())
        self.assertEqual(int(match["symbols"]), total_symbols - info["symbols"])
        self.assertEqual(int(match["files"]), len({r["path"] for r in self.store.outline_rows()}) - info["files"])

    def test_clamp_budget(self):
        self.assertEqual(maps.clamp_budget(60, 6000), 500)
        self.assertEqual(maps.clamp_budget(999999, 6000), 20000)
        self.assertEqual(maps.clamp_budget(None, 6000), 6000)
        self.assertEqual(maps.clamp_budget("lots", 6000), 6000)

    def test_empty_index_text(self):
        empty_db = Path(self._tmp.name) / "empty.db"
        store = store_module.Store(empty_db, self.root)
        self.addCleanup(store.close)
        store.sync_schema()
        text, info = maps.render_map(store, self.root, 1000)
        self.assertIn("no symbols indexed", text)
        self.assertIn("hermes carto index", text)
        self.assertEqual(info, {"files": 0, "symbols": 0, "truncated": False})


if __name__ == "__main__":
    unittest.main()
