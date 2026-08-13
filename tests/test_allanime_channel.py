"""Tests for the AllAnime backup channel (docs/RESOURCE_BACKUP_PLAN.md §2.4).

External calls are mocked with a real api.mkissa.net GraphQL response shape
(verified 2026-08-13 via Clash proxy); these tests never touch the internet.
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.services.channels.allanime import API_ENDPOINT, ORIGIN, AllAnimeChannel
from app.services.channels.base import ChannelError
from app.services.channels.kitsu import KitsuChannel
from app.services.channels.registry import ChannelRegistry
from app.services.channels.shikimori import ShikimoriChannel

# Real GraphQL shows(search:"Frieren") shape — raw edge order as returned by the
# API (main series LAST); the provider must sort by episode count descending.
ALLANIME_SEARCH = {
    "data": {
        "shows": {
            "edges": [
                {
                    "_id": "ddcCSGNtxd4uLzoxK",
                    "name": "Sousou no Frieren: ●● no Mahou Part 3",
                    "englishName": None,
                    "availableEpisodes": {"sub": 6, "dub": 0, "raw": 0},
                    "__typename": "Show",
                },
                {
                    "_id": "qpeexkeTa7DzLjRnp",
                    "name": "Sousou no Frieren 2nd Season",
                    "englishName": "Frieren: Beyond Journey's End Season 2",
                    "availableEpisodes": {"sub": 10, "dub": 10, "raw": 0},
                    "__typename": "Show",
                },
                {
                    "_id": "mKdCCBKYRZ6ygF2co",
                    "name": "Sousou no Frieren: ●● no Mahou Part 2",
                    "englishName": None,
                    "availableEpisodes": {"sub": 6, "dub": 0, "raw": 0},
                    "__typename": "Show",
                },
                {
                    "_id": "sG52nbcFo3PfLg6PD",
                    "name": "Sousou no Frieren: ●● no Mahou",
                    "englishName": "Frieren: Beyond Journey's End Mini Anime",
                    "availableEpisodes": {"sub": 12, "dub": 0, "raw": 0},
                    "__typename": "Show",
                },
                {
                    "_id": "ReHMC7TQnch3C6z8j",
                    "name": "Sousou no Frieren",
                    "englishName": "Frieren: Beyond Journey’s End",
                    "availableEpisodes": {"sub": 28, "dub": 28, "raw": 0},
                    "__typename": "Show",
                },
            ]
        }
    }
}


class _FakeResponse:
    def __init__(self, json_data=None, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class AllAnimeChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_parses_and_sorts_fixture(self):
        with mock.patch(
            "app.services.channels.http.request",
            return_value=_FakeResponse(json_data=ALLANIME_SEARCH),
        ):
            hits = await AllAnimeChannel().search("Frieren")
        self.assertEqual(len(hits), 5)
        # Main series (28 sub + 28 dub) must rank first despite being last in the wire order.
        first = hits[0]
        self.assertEqual(first.channel, "allanime")
        self.assertEqual(first.title, "Frieren: Beyond Journey’s End")
        self.assertEqual(first.title_original, "Sousou no Frieren")
        self.assertEqual(first.detail_ref, "ReHMC7TQnch3C6z8j")
        self.assertEqual(first.extra["sub_episodes"], 28)
        self.assertEqual(first.extra["dub_episodes"], 28)
        self.assertEqual(first.extra["total_episodes"], 56)
        # Second: 2nd season (10+10) before mini anime (12) and specials (6).
        self.assertEqual(hits[1].detail_ref, "qpeexkeTa7DzLjRnp")
        self.assertEqual(hits[2].detail_ref, "sG52nbcFo3PfLg6PD")
        # Fallback title when englishName is null.
        self.assertEqual(hits[3].title, "Sousou no Frieren: ●● no Mahou Part 3")
        self.assertEqual(hits[3].title_original, "")

    async def test_search_sends_graphql_json_with_origin_headers(self):
        with mock.patch(
            "app.services.channels.http.request",
            return_value=_FakeResponse(json_data=ALLANIME_SEARCH),
        ) as req:
            await AllAnimeChannel().search("Frieren")
        args, kwargs = req.call_args
        self.assertEqual(args[2], "POST")
        self.assertEqual(args[3], API_ENDPOINT)
        self.assertEqual(kwargs["headers"]["Referer"], ORIGIN)
        self.assertEqual(kwargs["headers"]["Origin"], ORIGIN)
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        body = kwargs["json_body"]
        self.assertIn("shows", body["query"])
        self.assertEqual(body["variables"]["search"]["query"], "Frieren")
        self.assertEqual(body["variables"]["limit"], 10)
        self.assertEqual(body["variables"]["page"], 1)

    async def test_search_empty_edges_returns_empty(self):
        with mock.patch(
            "app.services.channels.http.request",
            return_value=_FakeResponse(json_data={"data": {"shows": {"edges": []}}}),
        ):
            hits = await AllAnimeChannel().search("葬送的芙莉莲")
        self.assertEqual(hits, [])

    async def test_search_skips_edges_without_id_or_name(self):
        noisy = {
            "data": {
                "shows": {
                    "edges": [
                        {"_id": "", "name": "No ID", "availableEpisodes": {}},
                        {"_id": "x1", "name": "", "englishName": None, "availableEpisodes": {}},
                        {"_id": "x2", "name": "Keep", "englishName": "Kept", "availableEpisodes": {"sub": "3"}},
                        "not-a-dict",
                    ]
                }
            }
        }
        with mock.patch("app.services.channels.http.request", return_value=_FakeResponse(json_data=noisy)):
            hits = await AllAnimeChannel().search("kw")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].detail_ref, "x2")
        # string episode counts coerced to int
        self.assertEqual(hits[0].extra["sub_episodes"], 3)

    async def test_search_unexpected_payload_raises(self):
        for bad in ({"data": None}, {"data": {"shows": None}}, [], "nope"):
            with mock.patch("app.services.channels.http.request", return_value=_FakeResponse(json_data=bad)):
                with self.assertRaises(ChannelError) as ctx:
                    await AllAnimeChannel().search("Frieren")
            self.assertEqual(ctx.exception.channel, "allanime")
            self.assertFalse(ctx.exception.retryable)

    async def test_external_url(self):
        self.assertEqual(
            AllAnimeChannel().external_url("ReHMC7TQnch3C6z8j"),
            f"{ORIGIN}/anime/ReHMC7TQnch3C6z8j",
        )

    async def test_channel_registered_with_priority_62(self):
        reg = ChannelRegistry()
        reg.register_all([AllAnimeChannel(), KitsuChannel(), ShikimoriChannel()])
        infos = {c.id: c for c in reg.list_channels()}
        self.assertIn("allanime", infos)
        info = infos["allanime"]
        self.assertEqual(info.priority, 62)
        self.assertTrue(info.external)
        self.assertFalse(info.supports_detail)
        self.assertFalse(info.supports_streams)


if __name__ == "__main__":
    unittest.main()
