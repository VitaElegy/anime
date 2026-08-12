"""Tests for the runtime-safety guard on the Settings object."""

from __future__ import annotations

import unittest

from app.config import Settings


class ProductionGuardTests(unittest.TestCase):
    def test_development_allows_default_password(self):
        # Should not raise — factory defaults are fine while iterating locally.
        Settings(ENV="development", QB_PASSWORD="adminadmin").assert_runtime_safety()

    def test_production_rejects_factory_default_password(self):
        with self.assertRaises(RuntimeError) as cm:
            Settings(ENV="production", QB_PASSWORD="adminadmin").assert_runtime_safety()
        self.assertIn("adminadmin", str(cm.exception))

    def test_production_accepts_real_password(self):
        Settings(ENV="production", QB_PASSWORD="hunter2-but-longer").assert_runtime_safety()

    def test_prod_alias_is_honoured(self):
        with self.assertRaises(RuntimeError):
            Settings(ENV="prod", QB_PASSWORD="adminadmin").assert_runtime_safety()

    def test_case_insensitive_env(self):
        with self.assertRaises(RuntimeError):
            Settings(ENV="PRODUCTION", QB_PASSWORD="adminadmin").assert_runtime_safety()


if __name__ == "__main__":
    unittest.main()
