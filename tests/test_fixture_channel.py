"""FixtureChannel unit tests — deterministic E2E test double (docs/E2E_TESTING.md §2).

Covers the ChannelProvider contract (search / get_detail / get_streams) and the
fixture-only stream-proxy host allowance. No external network is touched.
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.config import settings
from app.routers import watch as watch_router
from app.services.channels.fixture import FixtureChannel


class FixtureChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_hits_chinese_title(self):
        hits = await FixtureChannel().search("葬送的芙莉莲")
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit.channel, "fixture")
        self.assertIn("芙莉莲", hit.title)
        self.assertEqual(hit.detail_ref, "fixture:frieren")

    async def test_search_hits_romaji(self):
        hits = await FixtureChannel().search("frieren")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].detail_ref, "fixture:frieren")

    async def test_search_miss_returns_empty(self):
        self.assertEqual(await FixtureChannel().search("naruto"), [])

    async def test_get_detail_returns_episode_groups(self):
        detail = await FixtureChannel().get_detail("fixture:frieren")
        self.assertEqual(detail.channel, "fixture")
        self.assertEqual(len(detail.groups), 1)
        eps = detail.groups[0].episodes
        self.assertEqual(len(eps), 3)
        self.assertEqual([ep.title for ep in eps], ["第 1 集", "第 2 集", "第 3 集"])
        self.assertTrue(all(ep.episode_ref.startswith("fixture:ep:") for ep in eps))

    async def test_get_streams_points_at_fixture_webm(self):
        streams = await FixtureChannel().get_streams("fixture:ep:1")
        self.assertEqual(len(streams), 1)
        stream = streams[0]
        self.assertEqual(stream.type, "web")
        self.assertEqual(stream.url, f"{settings.E2E_STREAM_BASE}/fixture.webm")

    async def test_registry_aggregates_fixture_only_in_fixture_mode(self):
        # The process-wide registry reflects the env at import; here we verify
        # the fixture provider plays nicely with a fresh registry (search hit).
        from app.services.channels.registry import ChannelRegistry

        reg = ChannelRegistry()
        reg.register_all([FixtureChannel()])
        hits = await reg.search("葬送的芙莉莲")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].channel, "fixture")


class StreamProxyHostAllowlistTests(unittest.TestCase):
    @mock.patch.object(settings, "E2E_FIXTURE", False)
    def test_production_blocks_localhost(self):
        self.assertTrue(watch_router._host_allowed("https://animeheaven.me/video.mp4"))
        self.assertFalse(watch_router._host_allowed("https://evil.example.com/x.mp4"))
        self.assertFalse(watch_router._host_allowed("http://127.0.0.1:8901/fixture.webm"))
        self.assertFalse(watch_router._host_allowed("file:///etc/passwd"))

    @mock.patch.object(settings, "E2E_FIXTURE", True)
    def test_fixture_mode_allows_local_fixture_only(self):
        self.assertTrue(watch_router._host_allowed("http://127.0.0.1:8901/fixture.webm"))
        self.assertTrue(watch_router._host_allowed("http://localhost:8901/fixture.webm"))
        self.assertFalse(watch_router._host_allowed("https://evil.example.com/x.mp4"))
