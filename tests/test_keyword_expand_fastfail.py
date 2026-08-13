"""Regression tests for channel keyword-expansion fast-fail (P0-2).

Channel keyword expansion used to discard instant offline title-map
alternatives when Bangumi was slow: a 2s outer timeout cancelled the whole
expansion, including the offline hits. Now only the Bangumi layer is bounded
(2s inside keyword_expand.py), so offline hits always survive.

All external calls are mocked — these tests never touch the real internet.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.services import database as db
from app.services import response_cache
from app.services.channels.registry import _expand_keywords


class _TempDBCacheTestCase(unittest.IsolatedAsyncioTestCase):
    """Hermetic cache tests: temp SQLite so no state leaks from real runs."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tempdir.name) / "kw-expand.db"
        db.init_db()
        response_cache.clear_l1_for_tests()
        self.addCleanup(self._restore)

    def _restore(self):
        db.DB_PATH = self.original_db_path
        response_cache.clear_l1_for_tests()
        self.tempdir.cleanup()


class KeywordExpansionFastFailTests(_TempDBCacheTestCase):
    async def test_registry_keeps_offline_map_when_bangumi_is_slow(self):
        """P0-2 regression: a slow Bangumi must not discard offline title-map hits."""
        async def slow(*args, **kwargs):
            await asyncio.sleep(10)
            return []

        with mock.patch("app.services.keyword_expand.bangumi.search", new=slow):
            alts = await asyncio.wait_for(_expand_keywords("孤独摇滚"), timeout=5)
        self.assertIn("孤独摇滚", alts)
        self.assertIn("BOCCHI THE ROCK!", alts)
        self.assertIn("Bocchi", alts)

    async def test_expand_keywords_returns_offline_map_within_budget(self):
        from app.services.keyword_expand import expand_keywords

        async def slow(*args, **kwargs):
            await asyncio.sleep(10)
            return []

        with mock.patch("app.services.keyword_expand.bangumi.search", new=slow):
            alts = await asyncio.wait_for(expand_keywords("葬送的芙莉莲"), timeout=5)
        self.assertIn("葬送的芙莉莲", alts)
        self.assertIn("Frieren", alts)
