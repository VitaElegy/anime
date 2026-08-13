"""Tests for the Kitsu backup channel (docs/RESOURCE_BACKUP_PLAN.md §2.1).

External calls are mocked with real Kitsu JSON shapes (verified 2026-08-13);
these tests never touch the real internet.
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.services.channels.base import ChannelError
from app.services.channels.kitsu import KitsuChannel

# Real Kitsu /api/edge/anime?filter[text]=Frieren shape (trimmed).
KITSU_SEARCH = {
    "data": [
        {
            "id": "46474",
            "type": "anime",
            "attributes": {
                "canonicalTitle": "Sousou no Frieren",
                "titles": {
                    "en": "Frieren: Beyond Journey's End",
                    "en_jp": "Sousou no Frieren",
                    "zh_cn": "葬送的芙莉蓮",
                    "ja_jp": "葬送のフリーレン",
                },
                "synopsis": "After the party of heroes defeated the Demon King, they restored peace...",
                "posterImage": {
                    "small": "https://media.kitsu.app/anime/46474/poster_image/small-x.jpeg",
                    "original": "https://media.kitsu.app/anime/46474/poster_image/original-y.png",
                },
                "episodeCount": 28,
                "averageRating": "88.8",
                "status": "finished",
                "subtype": "TV",
                "startDate": "2023-09-29",
            },
        },
        {
            "id": "49240",
            "type": "anime",
            "attributes": {
                "canonicalTitle": "Sousou no Frieren 2nd Season",
                "titles": {"en_jp": "Sousou no Frieren 2nd Season"},
                "posterImage": {"small": "https://media.kitsu.app/anime/49240/poster_image/small-y.jpeg"},
                "episodeCount": 10,
                "averageRating": "88.42",
                "status": "finished",
                "startDate": "2026-01-16",
            },
        },
    ]
}


class _FakeResponse:
    """Minimal httpx.Response stand-in (same shape as test_watch_channels)."""

    def __init__(self, json_data=None, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class KitsuChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_parses_zh_cn_fixture(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(json_data=KITSU_SEARCH)
        ) as req:
            hits = await KitsuChannel().search("Frieren")
        self.assertEqual(len(hits), 2)
        first = hits[0]
        self.assertEqual(first.channel, "kitsu")
        self.assertEqual(first.title, "葬送的芙莉蓮")  # zh_cn preferred
        self.assertEqual(first.title_original, "Sousou no Frieren")
        self.assertEqual(first.cover_url, "https://media.kitsu.app/anime/46474/poster_image/small-x.jpeg")
        self.assertEqual(first.detail_ref, "46474")
        self.assertEqual(first.year, "2023")
        self.assertTrue(first.description.startswith("After the party"))
        self.assertEqual(first.extra["episode_count"], 28)
        self.assertEqual(first.extra["average_rating"], "88.8")
        # second hit has no zh_cn → falls back to canonical
        self.assertEqual(hits[1].title, "Sousou no Frieren 2nd Season")
        # offset pagination passed through
        _, kwargs = req.call_args
        self.assertEqual(kwargs["params"]["filter[text]"], "Frieren")
        self.assertEqual(kwargs["params"]["page[offset]"], 0)

    async def test_search_empty_data_returns_empty(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(json_data={"data": []})
        ):
            hits = await KitsuChannel().search("不存在")
        self.assertEqual(hits, [])

    async def test_search_invalid_payload_raises_channel_error(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(json_data={"foo": 1})
        ):
            with self.assertRaises(ChannelError) as ctx:
                await KitsuChannel().search("x")
        self.assertEqual(ctx.exception.channel, "kitsu")
        self.assertEqual(ctx.exception.stage, "search")
        self.assertFalse(ctx.exception.retryable)

    def test_external_url_points_to_official_page(self):
        self.assertEqual(KitsuChannel().external_url("46474"), "https://kitsu.io/anime/46474")

    def test_channel_metadata(self):
        info = KitsuChannel().info(healthy=True)
        self.assertEqual(info.id, "kitsu")
        self.assertTrue(info.external)
        self.assertFalse(info.supports_streams)
        self.assertEqual(info.priority, 60)
        self.assertEqual(info.language, "zh-en")


class KitsuRegistryTests(unittest.TestCase):
    def test_registry_includes_kitsu_backup_source(self):
        from app.services.channels.registry import registry

        infos = {c.id: c for c in registry.list_channels()}
        self.assertIn("kitsu", infos)
        self.assertTrue(infos["kitsu"].external)
        self.assertFalse(infos["kitsu"].supports_streams)
        self.assertEqual(infos["kitsu"].priority, 60)
