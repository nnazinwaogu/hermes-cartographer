"""Settings.from_config coercion and validation."""

from __future__ import annotations

import unittest
from pathlib import Path

from _util import load_plugin

Settings = load_plugin().Settings


def config(**values):
    def get_config(key, default=None):
        return values.get(key, default)

    return get_config


class SettingsTests(unittest.TestCase):
    def test_defaults(self):
        settings = Settings.from_config(lambda key, default=None: default)
        self.assertEqual(settings, Settings())

    def test_invalid_inject_falls_back(self):
        self.assertEqual(Settings.from_config(config(inject="sometimes")).inject, "first")

    def test_inject_is_case_insensitive(self):
        self.assertEqual(Settings.from_config(config(inject="ALWAYS")).inject, "always")

    def test_budgets_clamp(self):
        settings = Settings.from_config(config(map_budget=25, default_map_budget=999999))
        self.assertEqual(settings.map_budget, 200)
        self.assertEqual(settings.default_map_budget, 20000)

    def test_negative_budget_falls_back_to_default(self):
        self.assertEqual(Settings.from_config(config(map_budget=-5)).map_budget, 4000)

    def test_hook_index_budget_clamps(self):
        self.assertEqual(Settings.from_config(config(hook_index_ms=10)).hook_index_ms, 100)
        self.assertEqual(Settings.from_config(config(hook_index_ms=90000)).hook_index_ms, 5000)

    def test_roots_and_excludes_are_coerced(self):
        settings = Settings.from_config(
            config(roots=["~/project", ""], excludes="vendor")
        )
        self.assertEqual(settings.roots, (Path("~/project").expanduser(),))
        self.assertEqual(settings.excludes, ("vendor",))

    def test_broken_config_accessor_yields_defaults(self):
        def get_config(key, default=None):
            raise RuntimeError("config backend down")

        self.assertEqual(Settings.from_config(get_config), Settings())


if __name__ == "__main__":
    unittest.main()
