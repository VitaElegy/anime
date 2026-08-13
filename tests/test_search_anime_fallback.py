"""Tests for /api/search/anime metadata fallback chain.

Contract (docs/SEARCH_API.md + RESOURCE_BACKUP_PLAN.md §1.2):
  Bangumi → AniList → 渠道聚合 → error
The frontend SearchPage must always get clickable anime cards for a Chinese
keyword even when Bangumi is unreachable (the main pain point).

All external calls are mocked — these tests never touch the real internet.
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.routers import search as search_router
from app.services.channels.registry import registry as registry_instance

BANGUMI_HITS = [
    type(
        "M",
        (),
        {
            "id": 371814,
            "name_cn": "葬送的芙莉莲",
            "name": "Sousou no Frieren",
            "cover_url": "https://lain.bgm.tv/pic/cover/l/xx.jpg",
            "summary": "After the party of heroes defeated the Demon King...",
            "score": 8.8,
        },
    )()
]

ANILIST_ITEMS = [
    {
        "id": 154587,
        "title_romaji": "Sousou no Frieren",
        "title_english": "Frieren: Beyond Journey's End",
        "title_native": "葬送のフリーレン",
        "title_preferred": "葬送的芙莉莲",
        "cover_large": "https://s4.anilist.co/cover/large.jpg",
        "cover_medium": "https://s4.anilist.co/cover/medium.jpg",
        "score": 8.8,
        "season_year": 2023,
        "description": "The adventure is over...",
    }
]

CHANNEL_HITS = [
    type(
        "H",
        (),
        {
            "channel": "kitsu",
            "title": "葬送的芙莉蓮",
            "title_original": "Sousou no Frieren",
            "cover_url": "https://media.kitsu.app/poster.jpeg",
            "description": "After the party...",
            "year": "2023",
        },
    )(),
    type(
        "H",
        (),
        {
            "channel": "animeheaven",
            "title": "Frieren: Beyond Journey's End",
            "title_original": "Sousou no Frieren",
            "cover_url": "",
            "description": "",
            "year": "2023",
        },
    )(),
    type(
        "H",
        (),
        {
            "channel": "kitsu",
            "title": "葬送的芙莉蓮",
            "title_original": "Sousou no Frieren",
            "cover_url": "https://media.kitsu.app/poster2.jpeg",
            "description": "",
            "year": "2023",
        },
    )(),
]


class SearchAnimeFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_bangumi_primary_no_fallback(self):
        with mock.patch.object(search_router.bangumi, "search", return_value=BANGUMI_HITS) as bgm, \
             mock.patch.object(search_router.anilist, "search") as anilist_search:
            resp = await search_router.search_anime_for_frontend("葬送的芙莉莲", limit=12)
        self.assertEqual(resp["total"], 1)
        self.assertEqual(resp["anime"][0]["source"], "Bangumi")
        self.assertEqual(resp["anime"][0]["id"], "371814")
        self.assertNotIn("fallback", resp)
        bgm.assert_called_once()
        anilist_search.assert_not_called()

    async def test_bangumi_down_falls_back_to_anilist(self):
        async def boom(*args, **kwargs):
            raise RuntimeError("bangumi down")

        with mock.patch.object(search_router.bangumi, "search", new=boom), \
             mock.patch.object(search_router.anilist, "search", return_value={"items": ANILIST_ITEMS, "total": 1, "has_next": False}):
            resp = await search_router.search_anime_for_frontend("葬送的芙莉莲", limit=12)
        self.assertEqual(resp["fallback"], "anilist")
        self.assertEqual(resp["total"], 1)
        first = resp["anime"][0]
        self.assertEqual(first["source"], "AniList")
        self.assertEqual(first["id"], "154587")
        self.assertEqual(first["title"], "葬送的芙莉莲")
        self.assertEqual(first["titleOriginal"], "Sousou no Frieren")
        self.assertEqual(first["year"], 2023)
        self.assertEqual(first["coverImage"], "https://s4.anilist.co/cover/large.jpg")

    async def test_bangumi_and_anilist_empty_falls_back_to_channels(self):
        with mock.patch.object(search_router.bangumi, "search", return_value=[]), \
             mock.patch.object(search_router.anilist, "search", return_value={"items": [], "total": 0, "has_next": False}), \
             mock.patch.object(registry_instance, "search", return_value=CHANNEL_HITS):
            resp = await search_router.search_anime_for_frontend("葬送的芙莉莲", limit=12)
        self.assertEqual(resp["fallback"], "channels")
        # 中文标题优先 + 归一化去重：kitsu 中文一条 + animeheaven 英文一条
        self.assertEqual(resp["total"], 2)
        self.assertEqual(resp["anime"][0]["title"], "葬送的芙莉蓮")
        self.assertEqual(resp["anime"][0]["source"], "kitsu")
        self.assertEqual(resp["anime"][0]["id"], "0")
        self.assertEqual(resp["anime"][1]["title"], "Frieren: Beyond Journey's End")
        # 去重后第二个 kitsu 中文不再出现
        titles = [a["title"] for a in resp["anime"]]
        self.assertEqual(titles.count("葬送的芙莉蓮"), 1)

    async def test_all_sources_empty_returns_error(self):
        with mock.patch.object(search_router.bangumi, "search", return_value=[]), \
             mock.patch.object(search_router.anilist, "search", return_value={"items": [], "total": 0, "has_next": False}), \
             mock.patch.object(registry_instance, "search", return_value=[]):
            resp = await search_router.search_anime_for_frontend("不存在的番剧xyz", limit=12)
        self.assertEqual(resp["anime"], [])
        self.assertEqual(resp["error"], "bangumi_unavailable")

    async def test_channel_fallback_search_error_returns_empty(self):
        async def boom(*args, **kwargs):
            raise RuntimeError("registry down")

        with mock.patch.object(search_router.bangumi, "search", return_value=[]), \
             mock.patch.object(search_router.anilist, "search", return_value={"items": [], "total": 0, "has_next": False}), \
             mock.patch.object(registry_instance, "search", new=boom):
            resp = await search_router.search_anime_for_frontend("葬送的芙莉莲", limit=12)
        self.assertEqual(resp["anime"], [])
        self.assertEqual(resp["error"], "bangumi_unavailable")
