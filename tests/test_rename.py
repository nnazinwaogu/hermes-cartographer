"""Rename planning, refusals, warnings, byte-offset splicing and apply."""

from __future__ import annotations

import ast
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _util import FIXTURES, load_plugin, load_submodule

errors = load_submodule("carto.errors")
indexer = load_submodule("carto.indexer")
query = load_submodule("carto.query")
rename = load_submodule("carto.rename")
settings_module = load_submodule("carto.settings")
store_module = load_submodule("carto.store")

tools = load_plugin().tools
Settings = settings_module.Settings


class RenameTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "repo"
        shutil.copytree(FIXTURES / "project_a", self.root)
        self.db = Path(self._tmp.name) / "index.db"
        indexer.sync(self.root, Settings(), db_path=self.db)
        self.store = store_module.Store(self.db, self.root)
        self.addCleanup(self.store.close)

    def plan(self, old, new, **kwargs):
        return rename.plan_rename(self.root, self.store, Settings(), old, new, **kwargs)

    def test_dry_run_diff(self):
        before = (self.root / "helpers.py").read_bytes()

        plan = self.plan("describe", "summarize")

        self.assertEqual(plan.files, ["helpers.py"])
        self.assertEqual(plan.replacements, 1)
        changed = [
            line
            for line in plan.diff.splitlines()
            if line[:1] in "+-" and not line.startswith(("+++", "---"))
        ]
        self.assertEqual(changed, ["-def describe(engine):", "+def summarize(engine):"])
        self.assertEqual((self.root / "helpers.py").read_bytes(), before)

    def test_apply_then_reparse(self):
        plan = self.plan("describe", "summarize")
        written = rename.apply_rename(self.root, self.store, plan, Settings())

        self.assertEqual(written, 1)
        for path in self.root.glob("*.py"):
            if path.name != "broken.py":
                ast.parse(path.read_text(encoding="utf-8"))
        self.assertTrue(self.store.has_symbol("summarize"))
        self.assertFalse(self.store.has_symbol("describe"))
        refs, _meta = query.find_references(self.store, "describe")
        self.assertEqual(refs, [])

    def test_refuses_existing_symbol(self):
        with self.assertRaisesRegex(errors.CartoError, "already exists"):
            self.plan("describe", "build")

    def test_refuses_invalid_identifier(self):
        cases = {
            "same name": ("describe", "describe"),
            "not a Python identifier": ("describe", "not an id"),
            "keyword": ("describe", "class"),
            "builtin": ("describe", "print"),
            "supports Python only": ("no_such_symbol", "other"),
        }
        for expected, (old, new) in cases.items():
            with self.subTest(expected):
                with self.assertRaisesRegex(errors.CartoError, expected):
                    self.plan(old, new)

    def test_refuses_non_python_symbol(self):
        js_root = FIXTURES / "project_js"
        js_db = Path(self._tmp.name) / "js-index.db"
        indexer.sync(js_root, Settings(), db_path=js_db)
        store = store_module.Store(js_db, js_root)
        self.addCleanup(store.close)
        with self.assertRaisesRegex(errors.CartoError, "supports Python only"):
            rename.plan_rename(js_root, store, Settings(), "startServer", "bootstrap")

    def test_warns_on_import_alias(self):
        before = (self.root / "aliases.py").read_text(encoding="utf-8")

        plan = self.plan("build", "assemble")

        self.assertTrue(
            any("import alias 'build'" in warning for warning in plan.warnings),
            plan.warnings,
        )
        self.assertEqual(plan.files, ["helpers.py"])
        self.assertEqual((self.root / "aliases.py").read_text(encoding="utf-8"), before)

    def test_method_attributes_forced(self):
        plan = self.plan("run", "execute")

        self.assertTrue(plan.forced_attributes)
        self.assertEqual(plan.files, ["core.py", "usecore.py"])
        self.assertEqual(plan.replacements, 2)

        rename.apply_rename(self.root, self.store, plan, Settings())

        for path in self.root.glob("*.py"):
            if path.name != "broken.py":
                ast.parse(path.read_text(encoding="utf-8"))
        self.assertIn("engine.execute(1)", (self.root / "usecore.py").read_text(encoding="utf-8"))
        self.assertTrue(self.store.has_symbol("execute"))
        self.assertEqual(self.store.references("run", limit=None), [])

    def test_non_ascii_byte_offsets(self):
        target = self.root / "unicode_case.py"
        target.write_text(
            'def target():\n    return "\u00e9" + target()\n', encoding="utf-8"
        )
        indexer.sync(self.root, Settings(), db_path=self.db)

        plan = self.plan("target", "renamed")
        rename.apply_rename(self.root, self.store, plan, Settings())

        text = target.read_text(encoding="utf-8")
        self.assertIn('return "\u00e9" + renamed()', text)
        ast.parse(text)


class RenameToolTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "repo"
        shutil.copytree(FIXTURES / "project_a", self.root)
        db = Path(self._tmp.name) / "index.db"
        patcher = mock.patch.object(indexer, "db_path_for", return_value=db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, **args):
        return json.loads(tools.symbol_rename({"path": self.root, **args}))

    def test_dry_run_is_default(self):
        before = (self.root / "helpers.py").read_bytes()

        payload = self.call(old="describe", new="summarize")

        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["applied"])
        self.assertEqual(payload["files_changed"], 1)
        self.assertEqual(payload["replacements"], 1)
        self.assertIn("+def summarize(engine):", payload["diff"])
        self.assertIn("forced_attributes", payload)
        self.assertEqual((self.root / "helpers.py").read_bytes(), before)

    def test_apply_writes(self):
        payload = self.call(old="describe", new="summarize", dry_run=False)

        self.assertTrue(payload["applied"])
        self.assertFalse(payload["dry_run"])
        self.assertIn("def summarize", (self.root / "helpers.py").read_text(encoding="utf-8"))

    def test_refusal_is_error_envelope(self):
        payload = self.call(old="describe", new="class")
        self.assertIn("error", payload)
        self.assertIn("hint", payload)


if __name__ == "__main__":
    unittest.main()
