"""Tests for the Shikimori backup channel (docs/RESOURCE_BACKUP_PLAN.md §2.3).

External calls are mocked with real Shikimori /api/animes JSON shapes
(verified 2026-08-13 via Clash proxy); these tests never touch the internet.
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.services.channels.base import ChannelError
from app.services.channels.shikimori import ORIGIN, ShikimoriChannel

# Real /api/animes?search=frieren shape (trimmed; image paths are relative).
SHIKIMORI_SEARCH = [
    {
        "id": 52991,
        "name": "Sousou no Frieren",
        "russian": "Провожающая в последний путь Фрирен",
        "image": {
            "original": "/system/animes/original/52991.jpg?1710731127",
            "preview": "/system/animes/preview/52991.jpg?1710731127",
        },
        "url": "/animes/52991-sousou-no-frieren",
        "kind": "tv",
        "score": "9.25",
        "status": "released",
        "episodes": 28,
        "episodes_aired": 27,
        "aired_on": "2023-09-29",
        "released_on": "2024-03-22",
    },
    {
        "id": 59978,
        "name": "Sousou no Frieren 2nd Season",
        "russian": "Провожающая в последний путь Фрирен 2",
        "image": {
            "original": "/assets/globals/missing_original.jpg",
            "preview": "/assets/globals/missing_preview.jpg",
        },
        "url": "/animes/59978-sousou-no-frieren-2nd-season",
        "kind": "tv",
        "score": "8.85",
        "status": "released",
        "episodes": 10,
        "episodes_aired": 10,
        "aired_on": "2026-01-16",
        "released_on": "2026-03-27",
    },
]


class _FakeResponse:
    def __init__(self, json_data=None, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class ShikimoriChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_parses_fixture(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(json_data=SHIKIMORI_SEARCH)
        ) as req:
            hits = await ShikimoriChannel().search("Frieren")
        self.assertEqual(len(hits), 2)
        first = hits[0]
        self.assertEqual(first.channel, "shikimori")
        self.assertEqual(first.title, "Sousou no Frieren")
        self.assertEqual(first.title_original, "Провожающая в последний путь Фрирен")
        self.assertEqual(first.cover_url, f"{ORIGIN}/system/animes/preview/52991.jpg?1710731127")
        self.assertEqual(first.detail_ref, "52991")
        self.assertEqual(first.year, "2023")
        self.assertEqual(first.extra["score"], "9.25")
        self.assertEqual(first.extra["status"], "released")
        self.assertEqual(first.extra["episodes"], 28)
        # pagination passed through
        _, kwargs = req.call_args
        self.assertEqual(kwargs["params"]["search"], "Frieren")
        self.assertEqual(kwargs["params"]["limit"], 6)
        self.assertEqual(kwargs["params"]["page"], 1)

    async def test_search_filters_unrelated_latin_hits(self):
        # Shikimori fuzzy search returns unrelated titles for a latin keyword;
        # the provider must drop hits sharing no significant query token.
        noisy = SHIKIMORI_SEARCH + [
            {
                "id": 999,
                "name": "Gudu De Lily",
                "image": {"preview": "/assets/globals/missing_preview.jpg"},
                "aired_on": "2020-01-01",
            }
        ]
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(json_data=noisy)
        ):
            hits = await ShikimoriChannel().search("Sousou no Frieren")
        titles = [h.title for h in hits]
        self.assertIn("Sousou no Frieren", titles)
        self.assertIn("Sousou no Frieren 2nd Season", titles)
        self.assertNotIn("Gudu De Lily", titles)

    async def test_search_returns_empty_for_cjk_keyword(self):
        # Shikimori's index is romaji/Russian; CJK queries hit pinyin fuzzy
        # matching that returns noise, so the provider yields nothing and the
        # registry's Latin keyword expansion supplies the actual match.
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(json_data=SHIKIMORI_SEARCH)
        ) as req:
            hits = await ShikimoriChannel().search("葬送的芙莉莲")
        self.assertEqual(hits, [])
        req.assert_not_called()

    async def test_search_skips_missing_name_or_id(self):
        with mock.patch(
            "app.services.channels.http.request",
            return_value=_FakeResponse(json_data=[{"id": 1}, {"name": "no-id"}]),
        ):
            hits = await ShikimoriChannel().search("x")
        self.assertEqual(hits, [])

    async def test_search_invalid_payload_raises_channel_error(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(json_data={"foo": 1})
        ):
            with self.assertRaises(ChannelError) as ctx:
                await ShikimoriChannel().search("x")
        self.assertEqual(ctx.exception.channel, "shikimori")
        self.assertEqual(ctx.exception.stage, "search")
        self.assertFalse(ctx.exception.retryable)

    def test_external_url_points_to_official_page(self):
        self.assertEqual(ShikimoriChannel().external_url("52991"), f"{ORIGIN}/animes/52991")

    def test_channel_metadata(self):
        info = ShikimoriChannel().info(healthy=True)
        self.assertEqual(info.id, "shikimori")
        self.assertTrue(info.external)
        self.assertFalse(info.supports_streams)
        self.assertFalse(info.supports_detail)
        self.assertEqual(info.priority, 65)
        self.assertEqual(info.language, "en")


class ShikimoriRegistryTests(unittest.TestCase):
    def test_registry_includes_shikimori_backup_source(self):
        from app.services.channels.registry import registry

        infos = {c.id: c for c in registry.list_channels()}
        self.assertIn("shikimori", infos)
        self.assertTrue(infos["shikimori"].external)
        self.assertFalse(infos["shikimori"].supports_streams)
        self.assertEqual(infos["shikimori"].priority, 65)
