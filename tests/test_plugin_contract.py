"""Plugin contract: the manifest declares exactly what register() registers."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from _util import REPO, load_manifest, load_plugin

CONFIG_TYPES = {
    "str", "string", "int", "integer", "float", "number", "bool", "boolean",
    "list", "array", "dict", "object", "secret",
}


class StubContext:
    """Mirrors the validator's recording stub: every registration is recorded, nothing executes."""

    plugin_config = {}
    profile_name = "default"
    plugin_id = "hermes_cartographer_test"

    def __init__(self):
        self.tools: list[str] = []
        self.hooks: list[str] = []
        self.middleware: list[str] = []
        self.commands: list[str] = []
        self.skills: list[tuple] = []
        self.config: dict = {}

    def register_tool(self, name, *args, **kwargs):
        self.tools.append(str(name))

    def register_hook(self, hook_name, callback, *, hold_stream=False):
        self.hooks.append(str(hook_name))

    def register_middleware(self, kind, callback):
        self.middleware.append(str(kind))

    def register_command(self, name, *args, **kwargs):
        self.commands.append(str(name))

    def register_cli_command(self, name, *args, **kwargs):
        self.commands.append(str(name))

    def register_skill(self, name, path, *args, **kwargs):
        self.skills.append((str(name), path))

    def get_config(self, key, default=None):
        return self.config.get(key, default)


class ManifestContractTests(unittest.TestCase):
    def test_manifest_lists_match(self):
        manifest = load_manifest()
        ctx = StubContext()
        load_plugin().register(ctx)

        self.assertEqual(sorted(manifest.get("provides_tools") or []), sorted(ctx.tools))
        self.assertEqual(sorted(manifest.get("provides_hooks") or []), sorted(ctx.hooks))

    def test_manifest_config_schema_is_mapping(self):
        schema = load_manifest().get("config_schema") or {}
        self.assertIsInstance(schema, dict)
        for key, spec in schema.items():
            self.assertIsInstance(spec, dict, f"config_schema.{key} must be a mapping")
            typ = spec.get("type")
            if typ is not None:
                self.assertIn(str(typ).lower(), CONFIG_TYPES, f"config_schema.{key}.type")

    def test_register_is_pure(self):
        plugin = load_plugin()
        previous = os.environ.get("HERMES_HOME")
        with tempfile.TemporaryDirectory() as home:
            os.environ["HERMES_HOME"] = home
            try:
                before = sorted(str(p.relative_to(home)) for p in Path(home).rglob("*"))
                plugin.register(StubContext())
                after = sorted(str(p.relative_to(home)) for p in Path(home).rglob("*"))
            finally:
                if previous is None:
                    os.environ.pop("HERMES_HOME", None)
                else:
                    os.environ["HERMES_HOME"] = previous
        self.assertEqual(before, after, "register() must not write under HERMES_HOME")


if __name__ == "__main__":
    unittest.main()
