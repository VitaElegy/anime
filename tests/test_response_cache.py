"""Tests for the L1/L2 response cache behaviour (P2-#13)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.services import database as db
from app.services import response_cache


class ResponseCacheL1Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tempdir.name) / "cache-test.db"
        db.init_db()
        response_cache.clear_l1_for_tests()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        response_cache.clear_l1_for_tests()
        self.tempdir.cleanup()

    async def test_fresh_entry_is_served_from_l1_after_first_hit(self):
        producer_calls = 0

        async def producer():
            nonlocal producer_calls
            producer_calls += 1
            return {"ts": producer_calls}

        key = response_cache.make_cache_key("test.endpoint", q="x")

        # First call: producer runs, both L1 and SQLite get populated.
        first = await response_cache.get_or_set_json(
            cache_key=key,
            cache_group="test",
            ttl_seconds=60,
            producer=producer,
        )
        self.assertEqual(first, {"ts": 1})

        # Second call: L1 must answer without touching SQLite.
        with mock.patch.object(
            db, "get_response_cache", side_effect=AssertionError("should not hit SQLite")
        ) as sqlite_mock:
            second = await response_cache.get_or_set_json(
                cache_key=key,
                cache_group="test",
                ttl_seconds=60,
                producer=producer,
            )
        self.assertEqual(second, {"ts": 1})
        self.assertEqual(sqlite_mock.call_count, 0)
        self.assertEqual(producer_calls, 1)

    async def test_force_refresh_bypasses_l1(self):
        calls = 0

        async def producer():
            nonlocal calls
            calls += 1
            return {"n": calls}

        key = response_cache.make_cache_key("test.force", q="y")
        await response_cache.get_or_set_json(
            cache_key=key,
            cache_group="test",
            ttl_seconds=60,
            producer=producer,
        )
        refreshed = await response_cache.get_or_set_json(
            cache_key=key,
            cache_group="test",
            ttl_seconds=60,
            producer=producer,
            force_refresh=True,
        )
        self.assertEqual(refreshed, {"n": 2})
        self.assertEqual(calls, 2)

    async def test_stale_entry_does_not_come_from_l1(self):
        """L1 must self-evict once its expiry passes."""

        async def producer():
            return {"v": 1}

        key = response_cache.make_cache_key("test.stale", q="z")
        # TTL=0 means the entry is already expired the moment it's written.
        await response_cache.get_or_set_json(
            cache_key=key,
            cache_group="test",
            ttl_seconds=0,
            producer=producer,
        )
        # L1 should now treat the key as a miss.
        self.assertIsNone(response_cache._l1_get(key))

    async def test_invalidate_clears_both_layers(self):
        async def producer():
            return {"v": 42}

        key = response_cache.make_cache_key("test.inv", q="w")
        await response_cache.get_or_set_json(
            cache_key=key,
            cache_group="test",
            ttl_seconds=60,
            producer=producer,
        )
        self.assertIsNotNone(response_cache._l1_get(key))
        response_cache.invalidate(key)
        self.assertIsNone(response_cache._l1_get(key))
        self.assertIsNone(db.get_response_cache(key))


if __name__ == "__main__":
    unittest.main()
