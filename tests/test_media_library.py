"""Tests for the incremental media-library scan behaviour (P1-#9)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.services import database as db
from app.services import media_library


class IncrementalScanTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

        self.original_db_path = db.DB_PATH
        db.DB_PATH = self.root / "library-test.db"
        db.init_db()

        self.original_download_dir = media_library.settings.DOWNLOAD_DIR
        media_library.settings.DOWNLOAD_DIR = self.root / "downloads"
        media_library.settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        media_library.settings.DOWNLOAD_DIR = self.original_download_dir
        self.tempdir.cleanup()

    def _write_sample(self, name: str, payload: bytes = b"x" * 1024) -> Path:
        path = media_library.settings.DOWNLOAD_DIR / name
        path.write_bytes(payload)
        return path

    def test_unchanged_file_skips_ffprobe_on_rescan(self):
        self._write_sample("episode-01.mp4")

        # First scan actually probes the file.
        with mock.patch.object(
            media_library,
            "_probe_media",
            return_value=(
                {"streams": [{"codec_type": "video", "codec_name": "h264"}], "format": {}},
                "ready",
                "",
            ),
        ) as probe_mock:
            media_library.scan_library()
        self.assertEqual(probe_mock.call_count, 1)

        # A second scan with the same file on disk must not call ffprobe again.
        with mock.patch.object(media_library, "_probe_media") as probe_mock:
            media_library.scan_library()
        self.assertEqual(probe_mock.call_count, 0)

    def test_modified_file_is_re_probed(self):
        path = self._write_sample("episode-02.mp4")

        with mock.patch.object(
            media_library,
            "_probe_media",
            return_value=(
                {"streams": [{"codec_type": "video", "codec_name": "h264"}], "format": {}},
                "ready",
                "",
            ),
        ):
            media_library.scan_library()

        # Simulate an edit: different size + newer mtime.
        path.write_bytes(b"y" * 4096)

        with mock.patch.object(
            media_library,
            "_probe_media",
            return_value=(
                {"streams": [{"codec_type": "video", "codec_name": "h264"}], "format": {}},
                "ready",
                "",
            ),
        ) as probe_mock:
            media_library.scan_library()
        self.assertEqual(probe_mock.call_count, 1)

    def test_deleted_file_is_pruned(self):
        path_a = self._write_sample("episode-03.mp4")
        self._write_sample("episode-04.mp4")
        with mock.patch.object(
            media_library,
            "_probe_media",
            return_value=(
                {"streams": [{"codec_type": "video", "codec_name": "h264"}], "format": {}},
                "ready",
                "",
            ),
        ):
            media_library.scan_library()
        self.assertEqual(len(db.list_media_assets()), 2)

        path_a.unlink()
        with mock.patch.object(media_library, "_probe_media"):
            media_library.scan_library()
        remaining = {row["relative_path"] for row in db.list_media_assets()}
        self.assertEqual(remaining, {"episode-04.mp4"})

    def test_empty_directory_does_not_wipe_existing_entries(self):
        video_path = self._write_sample("episode-05.mp4")
        with mock.patch.object(
            media_library,
            "_probe_media",
            return_value=(
                {"streams": [{"codec_type": "video", "codec_name": "h264"}], "format": {}},
                "ready",
                "",
            ),
        ):
            media_library.scan_library()
        self.assertEqual(len(db.list_media_assets()), 1)

        # Simulate the catalogued file going away while the directory itself
        # contains only non-video flotsam (e.g. a stale .nfo). The scan must
        # see zero video files but still preserve the DB row rather than
        # nuking the catalogue on what is most likely a transient glitch.
        video_path.unlink()
        (media_library.settings.DOWNLOAD_DIR / "cruft.nfo").write_text("not a video")

        assets = media_library.scan_library()
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["relative_path"], "episode-05.mp4")


if __name__ == "__main__":
    unittest.main()
