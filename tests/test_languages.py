"""Language detection and Python/JS scanning."""

from __future__ import annotations

import unittest

from _util import FIXTURES, load_submodule

languages = load_submodule("carto.languages")


def fixture(relative: str) -> str:
    return (FIXTURES / relative).read_text(encoding="utf-8")


class DetectLangTests(unittest.TestCase):
    def test_extensions(self):
        table = {
            ".py": "python",
            ".pyi": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".mjs": "javascript",
            ".cjs": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".kt": "java",
            ".kts": "java",
            ".c": "c",
            ".h": "c",
            ".cc": "c",
            ".cpp": "c",
            ".hpp": "c",
            ".cs": "c",
            ".rb": "other",
            ".md": "other",
        }
        for suffix, expected in table.items():
            self.assertEqual(languages.detect_lang("module" + suffix), expected, suffix)


class PythonScanTests(unittest.TestCase):
    def test_python_symbols(self):
        scan = languages.scan_python("core.py", fixture("project_a/core.py"))
        found = {(s.name, s.kind, s.lineno, s.qualname, s.parent) for s in scan.symbols}
        self.assertEqual(
            found,
            {
                ("DEFAULT_LIMIT", "constant", 3, "DEFAULT_LIMIT", ""),
                ("Engine", "class", 6, "Engine", ""),
                ("__init__", "method", 11, "Engine.__init__", "Engine"),
                ("run", "method", 15, "Engine.run", "Engine"),
                ("_work", "method", 18, "Engine._work", "Engine"),
            },
        )
        self.assertEqual(scan.lines, 19)

    def test_python_nested_function_qualname(self):
        scan = languages.scan_python("helpers.py", fixture("project_a/helpers.py"))
        label = [s for s in scan.symbols if s.name == "label"][0]
        self.assertEqual((label.qualname, label.parent, label.kind), ("build.label", "build", "method"))

    def test_python_signature(self):
        scan = languages.scan_python("core.py", fixture("project_a/core.py"))
        signatures = {s.name: s.signature for s in scan.symbols}
        self.assertEqual(signatures["run"], "(self, *units, retries: int=1, **options)")
        self.assertEqual(
            signatures["__init__"], "(self, name: str, limit: int=DEFAULT_LIMIT)"
        )
        self.assertEqual(signatures["Engine"], "")

    def test_broken_file_does_not_raise(self):
        scan = languages.scan_python("broken.py", fixture("project_a/broken.py"))
        self.assertEqual(scan.symbols, [])
        self.assertEqual(scan.refs, [])
        self.assertEqual(scan.lines, 4)

    def test_python_refs(self):
        scan = languages.scan_python("usecore.py", fixture("project_a/usecore.py"))
        run = [(r.lineno, r.col, r.kind) for r in scan.refs if r.name == "run"]
        self.assertEqual(run, [(8, 18, "attr")])
        engine = [(r.lineno, r.col, r.kind) for r in scan.refs if r.name == "engine"]
        self.assertEqual(engine, [(8, 11, "name")])

    def test_python_refs_skip_builtins_and_dedupe(self):
        scan = languages.scan_python("core.py", fixture("project_a/core.py"))
        names = [r.name for r in scan.refs]
        self.assertNotIn("str", names)
        self.assertNotIn("int", names)
        keys = {(r.name, r.lineno, r.col, r.kind) for r in scan.refs}
        self.assertEqual(len(keys), len(scan.refs))


class GenericScanTests(unittest.TestCase):
    def test_generic_js(self):
        scan = languages.scan_generic("app.js", fixture("project_js/app.js"), "javascript")
        found = {(s.name, s.kind, s.lineno) for s in scan.symbols}
        self.assertEqual(
            found,
            {
                ("startServer", "function", 1),
                ("Router", "class", 5),
                ("buildApp", "constant", 11),
            },
        )

    def test_generic_typescript(self):
        scan = languages.scan_generic("types.ts", fixture("project_js/types.ts"), "typescript")
        found = {(s.name, s.kind, s.lineno) for s in scan.symbols}
        self.assertEqual(found, {("Options", "type", 1), ("Handler", "type", 5)})

    def test_generic_unknown_language_is_empty(self):
        scan = languages.scan_generic("notes.txt", "function nope() {}", "other")
        self.assertEqual(scan.symbols, [])


if __name__ == "__main__":
    unittest.main()
