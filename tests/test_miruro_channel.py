"""Tests for the Miruro backup channel (docs/RESOURCE_BACKUP_PLAN.md §2.5).

External calls are mocked with real shapes captured from graphql.anilist.co and
miruro.tv /api/secure/pipe (verified playable 2026-08-13 via curl_cffi); these
tests never touch the internet. The curl_cffi pipe call is the documented
exception declared in §2.5, so tests stub ``MiruroChannel._pipe`` directly.
"""

from __future__ import annotations

import base64
import unittest
from unittest import mock

from app.routers.watch import _host_allowed
from app.services.channels.base import ChannelError
from app.services.channels.miruro import MiruroChannel
from app.services.channels.registry import registry

ANILIST_SEARCH = {
    "data": {
        "Page": {
            "media": [
                {
                    "id": 154587,
                    "title": {
                        "romaji": "Sousou no Frieren",
                        "english": "Frieren: Beyond Journey’s End",
                        "native": "葬送のフリーレン",
                    },
                    "coverImage": {
                        "large": "https://s4.anilist.co/cover/large/bx154587.jpg",
                        "extraLarge": "https://s4.anilist.co/cover/xlarge/bx154587.jpg",
                    },
                    "format": "TV",
                    "episodes": 28,
                    "averageScore": 88,
                    "seasonYear": 2023,
                },
                {
                    "id": 182255,
                    "title": {
                        "romaji": "Sousou no Frieren 2nd Season",
                        "english": None,
                        "native": "葬送のフリーレン 第2期",
                    },
                    "coverImage": {"large": None, "extraLarge": "https://s4.anilist.co/cover/xlarge/bx182255.jpg"},
                    "format": "TV",
                    "episodes": 10,
                    "averageScore": None,
                    "seasonYear": 2027,
                },
            ]
        }
    }
}


def _enc_id(plain: str) -> str:
    """base64url encode a pipe episode id (same as Miruro's _translate_id)."""
    return base64.urlsafe_b64encode(plain.encode()).decode().rstrip("=")


def _ep(number: int, title: str, plain_id: str) -> dict:
    return {
        "id": _enc_id(plain_id),
        "number": number,
        "title": title,
        "duration": 1561,
        "description": "sample",
        "filler": False,
        "uncensored": False,
        "audio": "japanese",
    }


# Real /api/secure/pipe episodes shape (2026-08-13): 4 providers with sub,
# pewe first in preference order, ally has no sub episodes.
PIPE_EPISODES = {
    "mappings": {
        "id": 25219,
        "title": "Sousou no Frieren",
        "malId": 52991,
        "aniId": 154587,
        "anidbId": 17617,
        "kitsuId": 46474,
    },
    "providers": {
        "pewe": {
            "episodes": {
                "sub": [
                    _ep(1, "Shall We Go, Then?", "anidbapp:1663:3062"),
                    _ep(2, "Episode 2", "anidbapp:1663:3063"),
                ],
                "dub": [_ep(1, "Shall We Go, Then? (Dub)", "anidbapp:1663:362")],
            }
        },
        "bee": {
            "episodes": {
                "sub": [_ep(1, "Shall We Go, Then?", "anidbapp:991:1")],
                "dub": [],
            }
        },
        "kiwi": {
            "episodes": {
                "sub": [_ep(1, "Shall We Go, Then?", "kiwivv:abc:1")],
                "dub": [],
            }
        },
        "hop": {
            "episodes": {
                "sub": [_ep(1, "Shall We Go, Then?", "hopstream:xyz:1")],
                "dub": [],
            }
        },
        "ally": {"episodes": {"sub": [], "dub": []}},
    },
}

# Real /api/secure/pipe sources shape: HLS + embed; HLS must be picked.
PIPE_SOURCES = {
    "streams": [
        {
            "url": "https://hls.anidb.app/stream/TOKEN123/master.m3u8",
            "type": "hls",
            "server": "AniDBApp",
            "referer": "https://anidb.app/",
            "default": True,
            "isActive": True,
        },
        {
            "url": "https://anidb.app/embed/Hu3l70wH-KCFJyMKbzSNNhG0UJK5S362dJj5x_uz0v8",
            "type": "embed",
            "server": "AniDBApp",
            "referer": "https://anidb.app/",
            "default": None,
            "isActive": None,
        },
    ]
}

# Sources where a non-anidb HLS appears first — provider must prefer anidb.app.
PIPE_SOURCES_MIXED = {
    "streams": [
        {
            "url": "https://cdn.other.example/master.m3u8",
            "type": "hls",
            "server": "Other",
            "referer": "https://other.example/",
            "default": False,
            "isActive": True,
        },
        PIPE_SOURCES["streams"][0],
    ]
}


class _FakeResponse:
    """Minimal httpx.Response stand-in (json only)."""

    def __init__(self, json_data=None, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class MiruroChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_parses_anilist_fixture(self):
        with mock.patch(
            "app.services.channels.http.request",
            return_value=_FakeResponse(json_data=ANILIST_SEARCH),
        ) as req:
            hits = await MiruroChannel().search("Frieren")
        self.assertEqual(len(hits), 2)
        first = hits[0]
        self.assertEqual(first.channel, "miruro")
        self.assertEqual(first.title, "Frieren: Beyond Journey’s End")
        self.assertEqual(first.title_original, "Sousou no Frieren")
        self.assertEqual(first.cover_url, "https://s4.anilist.co/cover/large/bx154587.jpg")
        self.assertEqual(first.year, "2023")
        self.assertEqual(first.detail_ref, "154587")
        self.assertEqual(first.extra["format"], "TV")
        self.assertEqual(first.extra["episodes"], 28)
        # No english title -> romaji fallback.
        self.assertEqual(hits[1].title, "Sousou no Frieren 2nd Season")
        self.assertEqual(hits[1].title_original, "Sousou no Frieren 2nd Season")
        self.assertEqual(hits[1].cover_url, "https://s4.anilist.co/cover/xlarge/bx182255.jpg")
        req.assert_called_once()
        self.assertEqual(req.call_args.args[2], "POST")
        self.assertEqual(req.call_args.args[3], "https://graphql.anilist.co")
        self.assertEqual(req.call_args.kwargs["json_body"]["variables"]["search"], "Frieren")

    async def test_search_empty_returns_empty(self):
        with mock.patch(
            "app.services.channels.http.request",
            return_value=_FakeResponse(json_data={"data": {"Page": {"media": []}}}),
        ):
            hits = await MiruroChannel().search("Nope Nope Nope")
        self.assertEqual(hits, [])

    async def test_detail_builds_provider_groups_capped_and_sorted(self):
        seen = {}

        async def fake_pipe(self, stage, payload):
            seen["payload"] = payload
            return PIPE_EPISODES

        with mock.patch.object(MiruroChannel, "_pipe", fake_pipe):
            detail = await MiruroChannel().get_detail("154587")
        self.assertEqual(seen["payload"]["path"], "episodes")
        self.assertEqual(seen["payload"]["query"], {"anilistId": 154587})
        self.assertEqual(detail.channel, "miruro")
        # 4 providers have sub episodes but MAX_GROUPS caps at 3, in preference order.
        self.assertEqual([g.title for g in detail.groups], ["pewe · 字幕", "bee · 字幕", "kiwi · 字幕"])
        pewe = detail.groups[0]
        self.assertEqual(len(pewe.episodes), 2)
        ep1, ep2 = pewe.episodes
        self.assertEqual(ep1.title, "第 1 集 · Shall We Go, Then?")
        self.assertEqual(ep1.episode_ref, "pewe:sub:154587:anidbapp:1663:3062")
        self.assertEqual(ep1.extra["number"], 1)
        # Generic "Episode 2" title is dropped (redundant with the number).
        self.assertEqual(ep2.title, "第 2 集")
        self.assertEqual(ep2.episode_ref, "pewe:sub:154587:anidbapp:1663:3063")

    async def test_detail_invalid_ref_raises_channel_error(self):
        with self.assertRaises(ChannelError) as ctx:
            await MiruroChannel().get_detail("not-an-id")
        self.assertFalse(ctx.exception.retryable)

    async def test_detail_pipe_failure_raises_channel_error(self):
        async def fake_pipe(self, stage, payload):
            raise ChannelError("miruro", stage, "pipe http 403")

        with mock.patch.object(MiruroChannel, "_pipe", fake_pipe):
            with self.assertRaises(ChannelError):
                await MiruroChannel().get_detail("154587")

    async def test_streams_parses_hls_with_referer(self):
        seen = {}

        async def fake_pipe(self, stage, payload):
            seen["payload"] = payload
            return PIPE_SOURCES

        with mock.patch.object(MiruroChannel, "_pipe", fake_pipe):
            streams = await MiruroChannel().get_streams("pewe:sub:154587:anidbapp:1663:3062")
        self.assertEqual(len(streams), 1)
        stream = streams[0]
        self.assertEqual(stream.type, "hls")
        self.assertIn("hls.anidb.app", stream.url)
        self.assertEqual(stream.headers.get("Referer"), "https://anidb.app/")
        self.assertIn("User-Agent", stream.headers)
        self.assertEqual(stream.note, "Miruro · pewe")
        query = seen["payload"]["query"]
        self.assertEqual(query["provider"], "pewe")
        self.assertEqual(query["category"], "sub")
        self.assertEqual(query["anilistId"], 154587)
        self.assertEqual(query["episodeId"], _enc_id("anidbapp:1663:3062"))

    async def test_streams_prefers_anidb_hls_over_other_hls(self):
        async def fake_pipe(self, stage, payload):
            return PIPE_SOURCES_MIXED

        with mock.patch.object(MiruroChannel, "_pipe", fake_pipe):
            streams = await MiruroChannel().get_streams("pewe:sub:154587:anidbapp:1663:3062")
        self.assertIn("hls.anidb.app", streams[0].url)

    async def test_streams_no_hls_raises_channel_error(self):
        async def fake_pipe(self, stage, payload):
            return {"streams": [{"url": "https://anidb.app/embed/x", "type": "embed"}]}

        with mock.patch.object(MiruroChannel, "_pipe", fake_pipe):
            with self.assertRaises(ChannelError):
                await MiruroChannel().get_streams("pewe:sub:154587:anidbapp:1663:3062")

    async def test_streams_malformed_ref_raises_channel_error(self):
        with self.assertRaises(ChannelError) as ctx:
            await MiruroChannel().get_streams("bogus")
        self.assertFalse(ctx.exception.retryable)

    def test_registry_registered(self):
        provider = registry.get("miruro")
        self.assertIsNotNone(provider)
        self.assertTrue(provider.enabled)
        self.assertEqual(provider.priority, 58)
        self.assertTrue(provider.supports_search)
        self.assertTrue(provider.supports_detail)
        self.assertTrue(provider.supports_streams)
        self.assertFalse(provider.external)
        self.assertEqual(provider.language, "en")
        ids = [info.id for info in registry.list_channels()]
        self.assertIn("miruro", ids)

    def test_stream_proxy_allowlist_covers_anidb(self):
        self.assertTrue(_host_allowed("https://hls.anidb.app/stream/TOKEN/master.m3u8"))
        self.assertTrue(_host_allowed("https://anidb.app/embed/x"))
        self.assertFalse(_host_allowed("https://example.com/video.mp4"))


if __name__ == "__main__":
    unittest.main()
