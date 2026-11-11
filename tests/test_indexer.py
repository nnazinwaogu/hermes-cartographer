"""Incremental indexing: unchanged-file fast path, removals, counts, broken files."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _util import FIXTURES, load_submodule

indexer = load_submodule("carto.indexer")
settings_module = load_submodule("carto.settings")
store_module = load_submodule("carto.store")

Settings = settings_module.Settings


class IndexerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "repo"
        shutil.copytree(FIXTURES / "project_a", self.root)
        self.db = Path(self._tmp.name) / "index.db"

    def run_sync(self, **kwargs):
        return indexer.sync(self.root, Settings(), db_path=self.db, **kwargs)

    def open_store(self):
        store = store_module.Store(self.db, self.root)
        self.addCleanup(store.close)
        return store

    def test_first_sync_indexes_every_file(self):
        report = self.run_sync()
        self.assertEqual(report.scanned, 6)
        self.assertEqual(report.indexed, 6)
        self.assertEqual(report.removed, 0)
        self.assertFalse(report.truncated)
        self.assertGreater(report.symbols, 0)

    def test_incremental_skips_unchanged(self):
        first = self.run_sync()
        self.assertGreater(first.indexed, 0)

        with mock.patch.object(indexer, "_read_bytes", wraps=indexer._read_bytes) as reader:
            second = self.run_sync()

        self.assertEqual(second.indexed, 0, "an unchanged tree must not re-index files")
        self.assertEqual(second.scanned, first.scanned)
        self.assertEqual(reader.call_count, 0, "unchanged files must not be read")

    def test_removed_file_drops_rows(self):
        self.run_sync()
        (self.root / "core.py").unlink()

        report = self.run_sync()

        self.assertEqual(report.removed, 1)
        store = self.open_store()
        self.assertEqual(store.symbols_for_path("core.py"), [])
        self.assertFalse(store.has_symbol("Engine"))

    def test_report_counts_match_store(self):
        report = self.run_sync()
        store = self.open_store()
        self.assertEqual(report.symbols, store.counts()["symbols"])
        self.assertEqual(report.refs, store.counts()["refs"])

    def test_broken_file_does_not_abort(self):
        report = self.run_sync()
        store = self.open_store()
        self.assertEqual(store.symbols_for_path("broken.py"), [])
        self.assertGreater(report.symbols, 0)

    def test_time_budget_truncates_without_pruning(self):
        first = self.run_sync()
        report = indexer.sync(self.root, Settings(), db_path=self.db, time_budget_ms=1)
        self.assertTrue(report.truncated)
        self.assertEqual(report.removed, 0)
        # Nothing walked, nothing pruned: the previous index is intact.
        store = self.open_store()
        self.assertEqual(store.counts()["symbols"], first.symbols)


if __name__ == "__main__":
    unittest.main()
