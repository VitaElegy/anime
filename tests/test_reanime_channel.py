"""Tests for the ReAnime backup channel (docs/RESOURCE_BACKUP_PLAN.md §2.9).

External calls are mocked with real ReAnime /api/v1/search JSON shapes
(verified 2026-08-13 via Clash 7892); these tests never touch the internet.
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.services.channels.base import ChannelError
from app.services.channels.reanime import ReAnimeChannel

# Real ReAnime /api/v1/search?q=Frieren shape (trimmed).
REANIME_SEARCH = {
    "limit": 20,
    "offset": 0,
    "processing_ms": 0,
    "query": "Frieren",
    "results": [
        {
            "anime_id": "frieren-beyond-journey-s-end-yw2a3j",
            "anilist_id": 154587,
            "title": {
                "english": "Frieren: Beyond Journey's End",
                "native": "葬送のフリーレン",
                "romaji": "Sousou no Frieren",
            },
            "cover_image": {
                "color": "#bbf1a1",
                "extra_large": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/bx154587-qQTzQnEJJ3oB.jpg",
                "large": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx154587-qQTzQnEJJ3oB.jpg",
                "medium": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/small/bx154587-qQTzQnEJJ3oB.jpg",
            },
            "format": "TV",
            "status": "Finished",
            "genres": ["Adventure", "Drama", "Fantasy"],
            "season": "FALL",
            "season_year": 2023,
            "episodes": 28,
            "duration": "24m",
            "subbed": 28,
            "dubbed": 28,
            "average_score": 91,
            "popularity": 413422,
            "rating": "PG-13 - Teens 13 or older",
            "can_watch": False,
            "can_request": False,
        },
        {
            "anime_id": "frieren-beyond-journey-s-end-season-2-5pwd4d",
            "anilist_id": 182255,
            "title": {
                "english": "Frieren: Beyond Journey's End Season 2",
                "native": "葬送のフリーレン 第2期",
                "romaji": "Sousou no Frieren 2nd Season",
            },
            "cover_image": {
                "color": "#5dc9f1",
                "extra_large": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/bx182255-butzrqd4I0aC.jpg",
                "large": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx182255-butzrqd4I0aC.jpg",
                "medium": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/small/bx182255-butzrqd4I0aC.jpg",
            },
            "format": "TV",
            "status": "Finished",
            "season": "WINTER",
            "season_year": 2026,
            "episodes": 10,
            "duration": "24m",
            "subbed": 10,
            "dubbed": 10,
            "average_score": 88,
            "popularity": 177269,
            "rating": "PG-13 - Teens 13 or older",
            "can_watch": False,
            "can_request": False,
        },
    ],
}


class _FakeResponse:
    """Minimal httpx.Response stand-in (same shape as test_kitsu_channel)."""

    def __init__(self, json_data=None, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class ReAnimeChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_parses_real_fixture(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(json_data=REANIME_SEARCH)
        ) as req:
            hits = await ReAnimeChannel().search("Frieren")
        self.assertEqual(len(hits), 2)
        first = hits[0]
        self.assertEqual(first.channel, "reanime")
        self.assertEqual(first.title, "Frieren: Beyond Journey's End")
        self.assertEqual(first.title_original, "Sousou no Frieren")
        self.assertEqual(
            first.cover_url,
            "https://s4.anilist.co/file/anilistcdn/media/anime/cover/small/bx154587-qQTzQnEJJ3oB.jpg",
        )
        self.assertEqual(first.detail_ref, "frieren-beyond-journey-s-end-yw2a3j")
        self.assertEqual(first.year, "2023")
        self.assertEqual(first.extra["episode_count"], 28)
        self.assertEqual(first.extra["average_score"], 91)
        self.assertFalse(first.extra["can_watch"])
        # second hit: year from season_year
        self.assertEqual(hits[1].year, "2026")
        # query + pagination passed through
        _, kwargs = req.call_args
        self.assertEqual(kwargs["params"]["q"], "Frieren")
        self.assertEqual(kwargs["params"]["offset"], 0)
        self.assertEqual(kwargs["params"]["limit"], 20)

    async def test_search_empty_results_returns_empty(self):
        with mock.patch(
            "app.services.channels.http.request",
            return_value=_FakeResponse(json_data={"results": []}),
        ):
            hits = await ReAnimeChannel().search("不存在")
        self.assertEqual(hits, [])

    async def test_search_invalid_payload_raises_channel_error(self):
        with mock.patch(
            "app.services.channels.http.request",
            return_value=_FakeResponse(json_data={"foo": 1}),
        ):
            with self.assertRaises(ChannelError) as ctx:
                await ReAnimeChannel().search("x")
        self.assertEqual(ctx.exception.channel, "reanime")
        self.assertEqual(ctx.exception.stage, "search")
        self.assertFalse(ctx.exception.retryable)

    def test_external_url_points_to_watch_page(self):
        self.assertEqual(
            ReAnimeChannel().external_url("frieren-beyond-journey-s-end-yw2a3j"),
            "https://reanime.to/watch/frieren-beyond-journey-s-end-yw2a3j",
        )

    def test_channel_metadata(self):
        info = ReAnimeChannel().info(healthy=True)
        self.assertEqual(info.id, "reanime")
        self.assertTrue(info.external)
        self.assertFalse(info.supports_streams)
        self.assertFalse(info.supports_detail)
        self.assertEqual(info.priority, 70)
        self.assertEqual(info.language, "en")


class ReAnimeRegistryTests(unittest.TestCase):
    def test_registry_includes_reanime_backup_source(self):
        from app.services.channels.registry import registry

        infos = {c.id: c for c in registry.list_channels()}
        self.assertIn("reanime", infos)
        self.assertTrue(infos["reanime"].external)
        self.assertFalse(infos["reanime"].supports_streams)
        self.assertEqual(infos["reanime"].priority, 70)
