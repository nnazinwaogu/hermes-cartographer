"""Definition lookup: exact/prefix/fuzzy modes, kind filter, ordering and the tool envelope."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _util import FIXTURES, load_plugin, load_submodule

indexer = load_submodule("carto.indexer")
query = load_submodule("carto.query")
settings_module = load_submodule("carto.settings")
store_module = load_submodule("carto.store")

tools = load_plugin().tools
Settings = settings_module.Settings


class QueryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "repo"
        shutil.copytree(FIXTURES / "project_a", self.root)
        self.db = Path(self._tmp.name) / "index.db"
        indexer.sync(self.root, Settings(), db_path=self.db)
        self.store = store_module.Store(self.db, self.root)
        self.addCleanup(self.store.close)

    def qualnames(self, name, **kwargs):
        return [row["qualname"] for row in query.find_definitions(self.store, name, **kwargs)]

    def test_find_exact_prefix_fuzzy(self):
        self.assertEqual(self.qualnames("Engine"), ["Engine"])
        self.assertEqual(self.qualnames("engine"), ["Engine"])
        self.assertEqual(self.qualnames("run", mode="prefix"), ["Engine.run", "run_once"])
        self.assertEqual(self.qualnames("ngine", mode="fuzzy"), ["Engine", "make_engine"])

    def test_kind_filter(self):
        self.assertEqual(self.qualnames("Engine", kind="class"), ["Engine"])
        self.assertEqual(self.qualnames("Engine", kind="function"), [])
        self.assertEqual(self.qualnames("run", mode="prefix", kind="method"), ["Engine.run"])

    def test_miss_is_empty_not_an_error(self):
        self.assertEqual(self.qualnames("does_not_exist"), [])

    def test_limit(self):
        self.assertEqual(len(self.qualnames("run", mode="prefix", limit=1)), 1)

    def test_like_metacharacters_are_literal(self):
        self.assertEqual(self.qualnames("_work"), ["Engine._work"])
        self.assertEqual(self.qualnames("_work", mode="fuzzy"), ["Engine._work"])

    def test_definition_shape(self):
        row = query.find_definitions(self.store, "Engine")[0]
        self.assertEqual(set(row), {"path", "line", "kind", "qualname", "signature", "parent"})
        self.assertEqual(row, {
            "path": "core.py",
            "line": 6,
            "kind": "class",
            "qualname": "Engine",
            "signature": "",
            "parent": "",
        })

    def test_unknown_mode_refused(self):
        with self.assertRaises(load_submodule("carto.errors").CartoError):
            query.find_definitions(self.store, "Engine", mode="regex")

    def test_refs_attribute_excluded_by_default(self):
        refs, _meta = query.find_references(self.store, "run")
        self.assertEqual(refs, [])
        refs, _meta = query.find_references(self.store, "run", include_attributes=True)
        self.assertEqual(
            [(r["path"], r["line"], r["column"], r["kind"]) for r in refs],
            [("usecore.py", 8, 18, "attr")],
        )

    def test_refs_limit_truncates(self):
        refs, meta = query.find_references(self.store, "self", limit=2)
        self.assertEqual(len(refs), 2)
        self.assertTrue(meta["truncated"])

    def test_refs_undefined_name_findable(self):
        refs, meta = query.find_references(self.store, "json")
        self.assertEqual(
            [(r["path"], r["line"], r["column"]) for r in refs], [("external.py", 7, 11)]
        )
        self.assertEqual(meta["scanned_files"], 0)


class GenericReferenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = FIXTURES / "project_js"
        self.db = Path(self._tmp.name) / "index.db"
        indexer.sync(self.root, Settings(), db_path=self.db)
        self.store = store_module.Store(self.db, self.root)
        self.addCleanup(self.store.close)

    def test_refs_generic_scan(self):
        refs, meta = query.find_references(self.store, "startServer")
        self.assertGreater(meta["scanned_files"], 0)
        self.assertEqual(
            refs,
            [{
                "path": "use.js",
                "line": 6,
                "column": 9,
                "kind": "name",
                "snippet": "return startServer(port);",
            }],
        )


class SymbolFindToolTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        db = Path(self._tmp.name) / "index.db"
        patcher = mock.patch.object(indexer, "db_path_for", return_value=db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, **args):
        return json.loads(tools.symbol_find({"path": FIXTURES / "project_a", **args}))

    def test_envelope(self):
        payload = self.call(name="Engine")
        self.assertEqual(set(payload), {"query", "definitions", "count"})
        self.assertEqual(payload["query"], "Engine")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["definitions"][0]["path"], "core.py")

    def test_miss_returns_count_zero(self):
        payload = self.call(name="nope", mode="fuzzy")
        self.assertEqual(payload, {"query": "nope", "definitions": [], "count": 0})

    def test_missing_name_is_error_envelope(self):
        payload = json.loads(tools.symbol_find({"path": FIXTURES / "project_a"}))
        self.assertIn("error", payload)
        self.assertIn("hint", payload)


class SymbolRefsToolTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        db = Path(self._tmp.name) / "index.db"
        patcher = mock.patch.object(indexer, "db_path_for", return_value=db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_envelope(self):
        payload = json.loads(
            tools.symbol_refs({"path": FIXTURES / "project_a", "name": "json"})
        )
        self.assertEqual(
            set(payload), {"name", "refs", "count", "truncated", "scanned_files"}
        )
        self.assertEqual(payload["name"], "json")
        self.assertGreaterEqual(payload["count"], 1)
        self.assertFalse(payload["truncated"])

    def test_missing_name_is_error_envelope(self):
        payload = json.loads(tools.symbol_refs({"path": FIXTURES / "project_a"}))
        self.assertIn("error", payload)
        self.assertIn("hint", payload)

    def test_string_false_flag_excludes_attributes(self):
        path = {"path": FIXTURES / "project_a", "name": "run"}
        without = json.loads(tools.symbol_refs({**path, "include_attributes": "false"}))
        with_attrs = json.loads(tools.symbol_refs({**path, "include_attributes": "true"}))
        self.assertEqual(without["count"], 0)
        self.assertEqual(with_attrs["count"], 1)


if __name__ == "__main__":
    unittest.main()
