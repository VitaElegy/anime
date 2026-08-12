"""Tests for the transcode progress tracking + semaphore throttle (P1-#10)."""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
import unittest
from pathlib import Path

from app.services import database as db
from app.services import media_transcode


class HlsProgressTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tempdir.name) / "transcode-test.db"
        db.init_db()

        asset = {
            "media_id": "test-media-1",
            "title": "Sample",
            "relative_path": "sample.mp4",
            "source_path": str(Path(self.tempdir.name) / "sample.mp4"),
            "size": 1024,
            "modified_at": 1700000000,
            "container": "mp4",
            "duration": 120.0,
            "video_codecs": ["h264"],
            "audio_codecs": ["aac"],
            "subtitle_codecs": [],
            "subtitles": [],
            "probe_status": "ready",
            "probe_error": "",
            "direct_play_supported": True,
            "recommended_mode": "direct_play",
            "hls_status": "missing",
            "hls_playlist": "",
            "hls_updated_at": 0,
            "last_error": "",
        }
        db.upsert_media_asset(asset)

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        self.tempdir.cleanup()

    def test_progress_is_persisted_and_returned(self):
        result = db.update_media_hls_status(
            "test-media-1",
            status="preparing",
            playlist="/media/hls/test-media-1/index.m3u8",
            last_error="",
            progress=42,
        )
        self.assertIsNotNone(result)
        assert result is not None  # narrow type for mypy
        self.assertEqual(result["hls_status"], "preparing")
        self.assertEqual(result["hls_progress"], 42)

    def test_ready_status_clamps_progress_to_100(self):
        result = db.update_media_hls_status(
            "test-media-1",
            status="ready",
            playlist="/media/hls/test-media-1/index.m3u8",
            last_error="",
        )
        assert result is not None
        self.assertEqual(result["hls_progress"], 100)

    def test_queued_status_resets_progress(self):
        db.update_media_hls_status("test-media-1", status="preparing", progress=55)
        result = db.update_media_hls_status("test-media-1", status="queued")
        assert result is not None
        self.assertEqual(result["hls_progress"], 0)

    def test_progress_clamped_to_0_100(self):
        high = db.update_media_hls_status("test-media-1", status="preparing", progress=999)
        assert high is not None
        self.assertEqual(high["hls_progress"], 100)
        low = db.update_media_hls_status("test-media-1", status="preparing", progress=-10)
        assert low is not None
        self.assertEqual(low["hls_progress"], 0)


class SemaphoreThrottleTests(unittest.IsolatedAsyncioTestCase):
    async def test_semaphore_reuses_across_calls(self):
        """Two successive calls should grab the same semaphore object.

        We don't run a real transcode here — this just verifies the lazy
        singleton does not churn on every call, which would silently uncap
        concurrency.
        """
        # Reset to force rebinding to this loop.
        media_transcode._transcode_semaphore = None
        sem_a = media_transcode._get_semaphore()
        sem_b = media_transcode._get_semaphore()
        self.assertIs(sem_a, sem_b)
        # Must still be willing to admit up to the configured cap.
        self.assertGreaterEqual(
            sem_a._value,  # type: ignore[attr-defined]
            media_transcode._MAX_CONCURRENT_TRANSCODES - 1,
        )

    async def test_third_transcode_waits_behind_two(self):
        """Hold two semaphore slots and confirm the third must wait."""
        media_transcode._transcode_semaphore = None
        sem = media_transcode._get_semaphore()
        await sem.acquire()
        await sem.acquire()
        try:
            third = asyncio.create_task(sem.acquire())
            try:
                await asyncio.wait_for(asyncio.shield(third), timeout=0.1)
            except TimeoutError:
                pass
            else:
                self.fail("Semaphore admitted a third holder past the cap")
            third.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await third
        finally:
            sem.release()
            sem.release()


if __name__ == "__main__":
    unittest.main()
