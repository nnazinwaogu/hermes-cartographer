"""code_map handler envelope, indexing integration and the never-raise contract."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _util import FIXTURES, load_submodule, load_plugin

tools = load_plugin().tools
indexer = load_submodule("carto.indexer")


class CodeMapTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        db = self.root / "index.db"
        patcher = mock.patch.object(indexer, "db_path_for", return_value=db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_empty_index_envelope(self):
        workspace = Path(self._tmp.name) / "empty"
        workspace.mkdir()
        payload = json.loads(tools.code_map({"path": workspace}))
        self.assertEqual(set(payload), {"root", "text", "files", "symbols", "truncated"})
        self.assertEqual(Path(payload["root"]), workspace.resolve())
        self.assertIn("no symbols indexed", payload["text"])
        self.assertIn("hermes carto index", payload["text"])
        self.assertEqual((payload["files"], payload["symbols"], payload["truncated"]), (0, 0, False))

    def test_fixture_map_returns_symbols(self):
        payload = json.loads(tools.code_map({"path": FIXTURES / "project_a"}))
        self.assertIn("class Engine", payload["text"])
        self.assertIn("def run(", payload["text"])
        self.assertGreater(payload["symbols"], 0)
        self.assertGreater(payload["files"], 0)
        self.assertFalse(payload["truncated"])

    def test_nonexistent_path_is_error_envelope(self):
        payload = json.loads(tools.code_map({"path": self.root / "missing"}))
        self.assertIn("error", payload)
        self.assertIn("hint", payload)
        self.assertIn("not a directory", payload["error"])

    def test_malformed_args_is_error_envelope(self):
        payload = json.loads(tools.code_map(None))
        self.assertIn("error", payload)
        self.assertIn("hint", payload)

    def test_unparsable_budget_is_error_envelope(self):
        payload = json.loads(tools.code_map({"path": FIXTURES / "project_a", "budget": "lots"}))
        self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
