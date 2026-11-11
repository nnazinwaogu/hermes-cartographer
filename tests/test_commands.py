"""`/carto` and `hermes carto`: same computation, text output, real exit codes."""

from __future__ import annotations

import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _util import FIXTURES, load_plugin, load_submodule

indexer = load_submodule("carto.indexer")
settings_module = load_submodule("carto.settings")
plugin = load_plugin()
Settings = settings_module.Settings
ROOT = FIXTURES / "project_a"


class CommandTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        db = Path(self._tmp.name) / "index.db"
        patcher = mock.patch.object(indexer, "db_path_for", return_value=db)
        patcher.start()
        self.addCleanup(patcher.stop)
        settings_patcher = mock.patch.object(plugin, "_SETTINGS", Settings(roots=(ROOT,)))
        settings_patcher.start()
        self.addCleanup(settings_patcher.stop)

    def run_cli(self, *argv):
        parser = argparse.ArgumentParser(prog="hermes")
        command = parser.add_subparsers(dest="command")
        carto = command.add_parser("carto")
        plugin._setup_cli(carto)
        carto.set_defaults(func=plugin._cli)
        args = parser.parse_args(["carto", *argv])
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = args.func(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_cli_index_map_find_refs_stats(self):
        code, out, _err = self.run_cli("index", str(ROOT))
        self.assertEqual(code, 0)
        self.assertIn("indexed 7 files", out)
        self.assertIn("symbols", out)

        code, out, _err = self.run_cli("map", str(ROOT))
        self.assertEqual(code, 0)
        self.assertIn("class Engine", out)

        code, out, _err = self.run_cli("find", "Engine", str(ROOT))
        self.assertEqual(code, 0)
        self.assertIn("core.py:6", out)
        self.assertIn("class Engine", out)

        code, out, _err = self.run_cli("refs", "json", str(ROOT))
        self.assertEqual(code, 0)
        self.assertIn("external.py:7", out)

        code, out, _err = self.run_cli("stats", str(ROOT))
        self.assertEqual(code, 0)
        self.assertIn("files: 7", out)
        self.assertIn("python", out)

    def test_cli_bad_path_exits_nonzero(self):
        code, out, err = self.run_cli("index", str(Path(self._tmp.name) / "missing"))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("not a directory", err)

    def test_cli_without_subcommand_prints_help(self):
        code, out, _err = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("carto index", out)

    def test_cli_budget_is_clamped(self):
        code, out, _err = self.run_cli("map", str(ROOT), "--budget", "60")
        self.assertEqual(code, 0)
        self.assertIn("class Engine", out)

    def test_slash_subcommands(self):
        self.assertIn("indexed 7 files", plugin._slash(f"index {ROOT}"))
        self.assertIn("class Engine", plugin._slash(f"map {ROOT}"))
        self.assertIn("core.py:6", plugin._slash("find Engine"))
        self.assertIn("external.py:7", plugin._slash("refs json"))
        self.assertIn("files: 7", plugin._slash(f"stats {ROOT}"))

    def test_slash_help_and_errors(self):
        self.assertIn("carto index", plugin._slash("help"))
        self.assertIn("unknown subcommand", plugin._slash("bogus"))
        self.assertIn("usage: carto find <name>", plugin._slash("find"))
        self.assertIn("not a directory", plugin._slash("index /definitely/not/here"))

    def test_slash_never_raises(self):
        self.assertIsInstance(plugin._slash(None), str)
        self.assertIsInstance(plugin._slash('find "unterminated'), str)


if __name__ == "__main__":
    unittest.main()
