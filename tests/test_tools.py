"""code_map handler envelope and the never-raise contract."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from _util import load_plugin

tools = load_plugin().tools


class CodeMapTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_empty_index_envelope(self):
        payload = json.loads(tools.code_map({"path": self.root}))
        self.assertEqual(set(payload), {"root", "text", "files", "symbols", "truncated"})
        self.assertEqual(Path(payload["root"]), self.root.resolve())
        self.assertIn("no symbols indexed", payload["text"])
        self.assertIn("hermes carto index", payload["text"])
        self.assertEqual((payload["files"], payload["symbols"], payload["truncated"]), (0, 0, False))

    def test_nonexistent_path_is_error_envelope(self):
        payload = json.loads(tools.code_map({"path": self.root / "missing"}))
        self.assertIn("error", payload)
        self.assertIn("hint", payload)
        self.assertIn("not a directory", payload["error"])

    def test_malformed_args_is_error_envelope(self):
        payload = json.loads(tools.code_map(None))
        self.assertIn("error", payload)
        self.assertIn("hint", payload)


if __name__ == "__main__":
    unittest.main()
