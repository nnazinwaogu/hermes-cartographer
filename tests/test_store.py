"""Store schema, replacement semantics and per-path reference pruning."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from _util import load_submodule

languages = load_submodule("carto.languages")
store_module = load_submodule("carto.store")


def symbol(path: str, name: str, lineno: int = 1) -> object:
    return languages.Symbol(
        path=path, name=name, qualname=name, kind="function", lineno=lineno, end_lineno=lineno
    )


def ref(path: str, name: str, lineno: int = 1, col: int = 0, kind: str = "name") -> object:
    return languages.Ref(path=path, name=name, lineno=lineno, col=col, kind=kind, snippet=name)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = store_module.Store(self.root / "index.db", self.root)
        self.addCleanup(self.store.close)
        self.store.sync_schema()

    def test_replace_drops_previous_rows(self):
        self.store.replace_file(
            "a.py", "python", 10, 1, "d1", 2, [symbol("a.py", "old")], [ref("a.py", "old")]
        )
        self.store.replace_file(
            "keep.py", "python", 10, 1, "d2", 2, [], [ref("keep.py", "dumps", 3, 8, "attr")]
        )

        self.store.replace_file(
            "a.py", "python", 11, 2, "d3", 2, [symbol("a.py", "new")], [ref("a.py", "new")]
        )

        self.assertEqual([row["name"] for row in self.store.symbols_for_path("a.py")], ["new"])
        self.assertEqual(self.store.references("old"), [])
        self.assertEqual([row["name"] for row in self.store.references("new")], ["new"])
        # A reference to a name that is defined nowhere in the repo survives: pruning is per path.
        self.assertEqual([row["name"] for row in self.store.references("dumps")], ["dumps"])

    def test_counts_and_meta(self):
        self.store.replace_file("a.py", "python", 10, 1, "d", 2, [symbol("a.py", "one")], [ref("a.py", "one")])
        self.assertEqual(self.store.counts(), {"files": 1, "symbols": 1, "refs": 1})
        self.store.meta_set("root", "/tmp/x")
        self.assertEqual(self.store.meta_get("root"), "/tmp/x")
        self.assertIsNone(self.store.meta_get("missing"))

    def test_outline_orders_and_filters(self):
        self.store.replace_file(
            "pkg/b.py", "python", 5, 1, "d", 5, [symbol("pkg/b.py", "beta", 2)], []
        )
        self.store.replace_file(
            "pkg/a.py", "python", 5, 1, "d", 5, [symbol("pkg/a.py", "alpha", 1)], []
        )
        self.assertEqual([row["name"] for row in self.store.outline_rows()], ["alpha", "beta"])
        self.assertEqual([row["name"] for row in self.store.outline_rows("pkg/a.py")], ["alpha"])
        self.assertEqual([row["name"] for row in self.store.outline_rows("pkg")], ["alpha", "beta"])


if __name__ == "__main__":
    unittest.main()
