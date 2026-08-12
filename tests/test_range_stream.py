"""Tests for the HTTP Range streaming helper used by direct-play video."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.services.range_stream import (
    _parse_range,
    build_range_response,
)
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


class ParseRangeTests(unittest.TestCase):
    def test_missing_header_returns_none(self):
        self.assertIsNone(_parse_range("", 1000))

    def test_empty_range_returns_none(self):
        self.assertIsNone(_parse_range("bytes=-", 1000))

    def test_malformed_header_returns_none(self):
        self.assertIsNone(_parse_range("seconds=0-10", 1000))

    def test_basic_range(self):
        self.assertEqual(_parse_range("bytes=0-499", 1000), (0, 499))

    def test_open_ended_range(self):
        self.assertEqual(_parse_range("bytes=500-", 1000), (500, 999))

    def test_suffix_range(self):
        self.assertEqual(_parse_range("bytes=-100", 1000), (900, 999))

    def test_end_clamped_to_eof(self):
        self.assertEqual(_parse_range("bytes=0-99999", 1000), (0, 999))

    def test_start_past_eof_is_416(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as cm:
            _parse_range("bytes=2000-3000", 1000)
        self.assertEqual(cm.exception.status_code, 416)

    def test_inverted_range_is_416(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as cm:
            _parse_range("bytes=500-100", 1000)
        self.assertEqual(cm.exception.status_code, 416)


def _build_app(path: Path) -> FastAPI:
    app = FastAPI()

    @app.get("/stream")
    async def stream(request: Request):
        return build_range_response(
            request,
            path,
            media_type="video/mp4",
            filename=path.name,
        )

    return app


class RangeResponseTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "sample.bin"
        # 10 KiB of deterministic bytes so we can assert on exact slices.
        self.payload = bytes(i % 256 for i in range(10 * 1024))
        self.path.write_bytes(self.payload)
        self.client = TestClient(_build_app(self.path))

    def tearDown(self):
        self.client.close()
        self.tempdir.cleanup()

    def test_full_response_when_no_range_header(self):
        response = self.client.get("/stream")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["accept-ranges"], "bytes")
        self.assertEqual(response.headers["content-length"], str(len(self.payload)))
        self.assertEqual(response.content, self.payload)
        self.assertIn("etag", response.headers)
        self.assertIn("last-modified", response.headers)

    def test_partial_response_for_byte_range(self):
        response = self.client.get("/stream", headers={"Range": "bytes=100-199"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.headers["content-range"], f"bytes 100-199/{len(self.payload)}")
        self.assertEqual(response.headers["content-length"], "100")
        self.assertEqual(response.content, self.payload[100:200])

    def test_partial_response_open_ended(self):
        response = self.client.get("/stream", headers={"Range": "bytes=9000-"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(
            response.headers["content-range"],
            f"bytes 9000-{len(self.payload) - 1}/{len(self.payload)}",
        )
        self.assertEqual(response.content, self.payload[9000:])

    def test_partial_response_suffix(self):
        response = self.client.get("/stream", headers={"Range": "bytes=-256"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, self.payload[-256:])

    def test_range_past_eof_returns_416(self):
        response = self.client.get("/stream", headers={"Range": "bytes=99999-"})
        self.assertEqual(response.status_code, 416)
        self.assertEqual(response.headers.get("content-range"), f"bytes */{len(self.payload)}")

    def test_if_none_match_returns_304(self):
        first = self.client.get("/stream")
        etag = first.headers["etag"]
        second = self.client.get("/stream", headers={"If-None-Match": etag})
        self.assertEqual(second.status_code, 304)
        self.assertEqual(second.content, b"")
        self.assertEqual(second.headers["etag"], etag)

    def test_malformed_range_falls_back_to_full_response(self):
        response = self.client.get("/stream", headers={"Range": "seconds=0-10"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.payload)

    def test_etag_is_stable_across_requests(self):
        first = self.client.get("/stream").headers["etag"]
        second = self.client.get("/stream").headers["etag"]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
