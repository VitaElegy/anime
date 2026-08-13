"""Regression tests for Bangumi search fast-fail (P0-1).

When Bangumi is unreachable, every first search used to stall ~60s
(v0 30s + legacy 30s serial). Now: 3s hard cap + negative cache + circuit
breaker → returns [] quickly and never re-hits a dead endpoint.

All external calls are mocked — these tests never touch the real internet.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.services import bangumi, response_cache
from app.services import database as db


def _reset_bangumi_state():
    bangumi._search_failures = 0
    bangumi._search_cooldown_until = 0.0
    bangumi._negative_search_cache.clear()


class _TempDBCacheTestCase(unittest.IsolatedAsyncioTestCase):
    """Hermetic cache tests: temp SQLite so no state leaks from real runs."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tempdir.name) / "fastfail.db"
        db.init_db()
        response_cache.clear_l1_for_tests()
        _reset_bangumi_state()
        self.addCleanup(self._restore)

    def _restore(self):
        db.DB_PATH = self.original_db_path
        response_cache.clear_l1_for_tests()
        _reset_bangumi_state()
        self.tempdir.cleanup()


class BangumiFastFailTests(_TempDBCacheTestCase):
    async def test_hanging_upstream_fails_fast(self):
        """A hanging Bangumi must not stall search for 60s — returns [] quickly."""
        async def hang(*args, **kwargs):
            await asyncio.sleep(60)

        with mock.patch.object(bangumi, "_search_uncached", new=hang):
            result = await asyncio.wait_for(bangumi.search("测试"), timeout=6)
        self.assertEqual(result, [])

    async def test_negative_cache_short_circuits_second_call(self):
        """After a failure, a repeated identical keyword does not re-hit upstream."""
        calls = []

        async def fail(*args, **kwargs):
            calls.append(1)
            raise RuntimeError("bangumi down")

        with mock.patch.object(bangumi, "_search_uncached", new=fail):
            self.assertEqual(await bangumi.search("葬送的芙莉莲"), [])
        response_cache.clear_l1_for_tests()  # do not rely on the HTTP cache
        with mock.patch.object(bangumi, "_search_uncached", new=fail):
            self.assertEqual(await bangumi.search("葬送的芙莉莲"), [])
        self.assertEqual(len(calls), 1)

    async def test_circuit_breaker_skips_network_after_threshold(self):
        calls = []

        async def fail(*args, **kwargs):
            calls.append(1)
            raise RuntimeError("bangumi down")

        # Use a different keyword per iteration: the negative cache is keyed by
        # keyword while the circuit breaker is global, so only the breaker can
        # short-circuit a brand-new keyword.
        keywords = ["进击的巨人", "鬼灭之刃", "咒术回战"]
        with mock.patch.object(bangumi, "_search_uncached", new=fail):
            for kw in keywords:
                self.assertEqual(await bangumi.search(kw), [])
        # Circuit is now open: a fresh keyword skips the network entirely.
        with mock.patch.object(bangumi, "_search_uncached", new=fail):
            self.assertEqual(await bangumi.search("海贼王"), [])
        self.assertEqual(len(calls), bangumi.SEARCH_FAILURE_THRESHOLD)

    async def test_success_resets_failure_counter(self):
        async def fail(*args, **kwargs):
            raise RuntimeError("bangumi down")

        with mock.patch.object(bangumi, "_search_uncached", new=fail):
            for _ in range(bangumi.SEARCH_FAILURE_THRESHOLD - 1):
                self.assertEqual(await bangumi.search("鬼灭之刃"), [])

        async def ok(*args, **kwargs):
            return []

        with mock.patch.object(bangumi, "_search_uncached", new=ok):
            self.assertEqual(await bangumi.search("鬼灭之刃"), [])

        # After a success, one more failure must NOT open the circuit yet.
        with mock.patch.object(bangumi, "_search_uncached", new=fail):
            self.assertEqual(await bangumi.search("鬼灭之刃"), [])
        self.assertLess(bangumi._search_failures, bangumi.SEARCH_FAILURE_THRESHOLD)
