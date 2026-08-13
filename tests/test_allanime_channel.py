"""Tests for the AllAnime backup channel (docs/RESOURCE_BACKUP_PLAN.md §2.4).

External calls are mocked with a real api.mkissa.net GraphQL response shape
(verified 2026-08-13 via Clash proxy); these tests never touch the internet.
"""

from __future__ import annotations

import base64
import json
import unittest
from unittest import mock

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.services.channels.allanime import (
    API_ENDPOINT,
    DETAIL_GQL,
    EPISODE_GQL,
    ORIGIN,
    AllAnimeChannel,
    _decode_source_url,
    _normalize_sources,
)
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
    def __init__(self, json_data=None, status_code: int = 200, text: str = ""):
        self._json = json_data
        self.status_code = status_code
        self.text = text if text else (json.dumps(json_data) if json_data is not None else "")

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

    async def test_channel_registered_playable_backup(self):
        reg = ChannelRegistry()
        reg.register_all([AllAnimeChannel(), KitsuChannel(), ShikimoriChannel()])
        infos = {c.id: c for c in reg.list_channels()}
        self.assertIn("allanime", infos)
        info = infos["allanime"]
        self.assertEqual(info.priority, 61)
        self.assertFalse(info.external)
        self.assertTrue(info.supports_detail)
        self.assertTrue(info.supports_streams)


    # ------------------------------------------------------------------
    # get_detail
    # ------------------------------------------------------------------

    async def test_get_detail_parses_episode_groups(self):
        payload = {
            "data": {
                "show": {
                    "_id": "ReHMC7TQnch3C6z8j",
                    "name": "Sousou no Frieren",
                    "englishName": "Frieren: Beyond Journey's End",
                    "availableEpisodesDetail": {"sub": ["28", "1", "5"], "dub": ["2", "1"], "raw": []},
                }
            }
        }
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(json_data=payload)
        ) as req:
            detail = await AllAnimeChannel().get_detail("ReHMC7TQnch3C6z8j")
        args, kwargs = req.call_args
        self.assertEqual(args[2], "POST")
        self.assertEqual(kwargs["json_body"]["query"], DETAIL_GQL)
        self.assertEqual(kwargs["json_body"]["variables"]["id"], "ReHMC7TQnch3C6z8j")
        self.assertEqual(detail.channel, "allanime")
        self.assertEqual(detail.title, "Frieren: Beyond Journey's End")
        self.assertEqual([g.title for g in detail.groups], ["字幕", "配音"])
        sub = detail.groups[0]
        self.assertEqual([e.title for e in sub.episodes], ["第 1 集", "第 5 集", "第 28 集"])
        self.assertEqual(sub.episodes[0].episode_ref, "ReHMC7TQnch3C6z8j::sub::1")
        dub = detail.groups[1]
        self.assertEqual(dub.episodes[1].episode_ref, "ReHMC7TQnch3C6z8j::dub::2")

    async def test_get_detail_errors(self):
        with mock.patch(
            "app.services.channels.http.request",
            return_value=_FakeResponse(json_data={"errors": [{"message": "boom"}]}),
        ):
            with self.assertRaises(ChannelError) as ctx:
                await AllAnimeChannel().get_detail("x")
            self.assertFalse(ctx.exception.retryable)
        with mock.patch(
            "app.services.channels.http.request",
            return_value=_FakeResponse(json_data={"data": {"show": None}}),
        ):
            with self.assertRaises(ChannelError):
                await AllAnimeChannel().get_detail("x")
        with mock.patch(
            "app.services.channels.http.request",
            return_value=_FakeResponse(json_data={"data": {"show": {"_id": "x", "availableEpisodesDetail": {}}}}),
        ):
            with self.assertRaises(ChannelError):
                await AllAnimeChannel().get_detail("x")

    # ------------------------------------------------------------------
    # source decoding / normalization
    # ------------------------------------------------------------------

    def test_decode_source_url_hex_form(self):
        # "--" prefix + hex-pair substitution (ani-cli cipher).
        # Fixture decodes to the relative Luf-Mp4 clock path ("/apivtwo/clock?id=7"),
        # matching AllAnime's source-url shape (absolute https URLs are left
        # plaintext by _normalize_sources, never hex-prefixed).
        enc = "--175948514e4c4f57175b54575b5307515c050f"
        self.assertEqual(_decode_source_url(enc[2:]), "/apivtwo/clock?id=7")
        # And an https URL round-trips through the table when hex-encoded.
        enc_https = "--504c4c484b021717" + "175948514e4c4f57175b54575b5307515c0540"
        self.assertTrue(_decode_source_url(enc_https[2:]).startswith("https://"))

    def test_normalize_sources_keeps_plaintext_and_decodes_hex(self):
        rows = _normalize_sources(
            [
                {
                    "sourceName": "Yt-mp4",
                    "sourceUrl": "https://tools.fast4speed.rsvp/media9/videos/x/sub/1?Authorization=3_20260812213125_4e8f",
                    "priority": 7.9,
                },
                {
                    "sourceName": "Mp4",
                    "sourceUrl": "https://mp4upload.com/embed-abc123.html",
                    "priority": 4.0,
                },
                {"sourceName": "no-url", "sourceUrl": "", "priority": 9.0},
                "junk",
            ]
        )
        self.assertEqual(len(rows), 2)
        # Plaintext must NOT be passed through the hex table (would corrupt digits).
        self.assertEqual(
            rows[0]["sourceUrl"],
            "https://tools.fast4speed.rsvp/media9/videos/x/sub/1?Authorization=3_20260812213125_4e8f",
        )
        self.assertEqual(rows[1]["sourceUrl"], "https://mp4upload.com/embed-abc123.html")
        # Highest priority first.
        self.assertEqual(rows[0]["sourceName"], "Yt-mp4")

    # ------------------------------------------------------------------
    # get_streams
    # ------------------------------------------------------------------

    @staticmethod
    def _tobeparsed(payload: dict, key: bytes) -> str:
        nonce = b"0123456789ab"
        plain = json.dumps(payload).encode()
        sealed = AESGCM(key).encrypt(nonce, plain, None)
        return base64.b64encode(b"\x01" + nonce + sealed).decode()

    def _episode_response(self, key: bytes) -> _FakeResponse:
        payload = {
            "data": {
                "episode": {
                    "episodeString": "1",
                    "sourceUrls": [
                        {
                            "sourceName": "Yt-mp4",
                            "sourceUrl": "https://tools.fast4speed.rsvp/media9/videos/SHOW/sub/1?Authorization=3_20260812213125_4e8f",
                            "priority": 7.9,
                        },
                        {
                            "sourceName": "Mp4",
                            "sourceUrl": "https://mp4upload.com/embed-abc123.html",
                            "priority": 4.0,
                        },
                    ],
                    "show": {"_id": "SHOW", "name": "Sousou no Frieren", "countryOfOrigin": "JP"},
                }
            }
        }
        return _FakeResponse(
            json_data=None,
            text=json.dumps({"data": {"episode": None}, "extensions": {"tobeparsed": self._tobeparsed(payload, key)}}),
        )

    async def test_get_streams_resolves_yt_mp4_and_mp4upload(self):
        key = bytes.fromhex("00" * 32)
        keys = {"KEY": "00" * 32, "EPOCH": "2953", "BUILDID": "110", "LANE": "k7"}

        def fake_request(channel, stage, method, url, **kwargs):
            if url == API_ENDPOINT and "episode" in kwargs["json_body"]["query"]:
                body = kwargs["json_body"]
                self.assertEqual(body["variables"]["showId"], "SHOW")
                self.assertEqual(body["variables"]["translationType"], "sub")
                self.assertEqual(body["variables"]["episodeString"], "1")
                ext = body["extensions"]
                self.assertEqual(ext["k"], "k7")
                self.assertEqual(ext["persistedQuery"]["sha256Hash"], EPISODE_GQL and __import__("hashlib").sha256(EPISODE_GQL.encode()).hexdigest())
                self.assertIsInstance(ext["aaReq"], str)
                return self._episode_response(key)
            if url == "https://mp4upload.com/embed-abc123.html":
                return _FakeResponse(
                    json_data=None,
                    text='<html><video src="https://a4.mp4upload.com:183/d/abc/video.mp4"></video></html>',
                )
            raise AssertionError(f"unexpected request: {method} {url}")

        with mock.patch("app.services.channels.http.request", side_effect=fake_request), mock.patch(
            "app.services.channels.allanime._get_keys", new=mock.AsyncMock(return_value=keys)
        ):
            streams = await AllAnimeChannel().get_streams("SHOW::sub::1")

        self.assertEqual(len(streams), 2)
        self.assertEqual(streams[0].type, "mp4")
        self.assertEqual(streams[0].note, "AllAnime Yt-mp4")
        self.assertEqual(streams[0].headers["Referer"], "https://allanime.day/")
        self.assertIn("fast4speed.rsvp", streams[0].url)
        self.assertEqual(streams[1].note, "AllAnime Mp4upload")
        self.assertEqual(streams[1].headers["Referer"], "https://www.mp4upload.com/")
        self.assertIn("/video.mp4", streams[1].url)

    async def test_get_streams_plaintext_sources_without_tobeparsed(self):
        keys = {"KEY": "00" * 32, "EPOCH": "2953", "BUILDID": "110", "LANE": "k7"}

        def fake_request(channel, stage, method, url, **kwargs):
            if url == API_ENDPOINT:
                return _FakeResponse(
                    json_data={
                        "data": {
                            "episode": {
                                "sourceUrls": [
                                    {
                                        "sourceName": "Yt-mp4",
                                        "sourceUrl": "https://tools.fast4speed.rsvp/media9/videos/SHOW/sub/1?Authorization=ok",
                                        "priority": 7.9,
                                    }
                                ]
                            }
                        }
                    }
                )
            raise AssertionError(f"unexpected request: {method} {url}")

        with mock.patch("app.services.channels.http.request", side_effect=fake_request), mock.patch(
            "app.services.channels.allanime._get_keys", new=mock.AsyncMock(return_value=keys)
        ):
            streams = await AllAnimeChannel().get_streams("SHOW::sub::1")
        self.assertEqual(len(streams), 1)
        self.assertIn("Authorization=ok", streams[0].url)

    async def test_get_streams_needs_captcha_is_not_retryable(self):
        keys = {"KEY": "00" * 32, "EPOCH": "2953", "BUILDID": "110", "LANE": "k7"}
        with mock.patch(
            "app.services.channels.http.request",
            return_value=_FakeResponse(
                json_data={
                    "errors": [{"message": "NEED_CAPTCHA", "extensions": {"code": "INTERNAL_SERVER_ERROR"}}]
                }
            ),
        ), mock.patch("app.services.channels.allanime._get_keys", new=mock.AsyncMock(return_value=keys)):
            with self.assertRaises(ChannelError) as ctx:
                await AllAnimeChannel().get_streams("SHOW::sub::1")
        self.assertEqual(ctx.exception.stage, "streams")
        self.assertIn("NEED_CAPTCHA", str(ctx.exception))
        self.assertFalse(ctx.exception.retryable)

    async def test_get_streams_retries_once_with_fresh_key_on_crypto_error(self):
        keys = {"KEY": "00" * 32, "EPOCH": "2953", "BUILDID": "110", "LANE": "k7"}
        calls = {"n": 0}

        async def fake_get_keys(force: bool = False) -> dict:
            calls["n"] += 1
            return {**keys, "KEY": ("11" * 32) if force else keys["KEY"]}

        def fake_request(channel, stage, method, url, **kwargs):
            calls["req"] = calls.get("req", 0) + 1
            # First attempt returns a stale-key error; second returns sources.
            if calls["req"] == 1:
                return _FakeResponse(json_data={"errors": [{"message": "AA_CRYPTO_MISSING"}]})
            return _FakeResponse(
                json_data={
                    "data": {
                        "episode": {
                            "sourceUrls": [
                                {
                                    "sourceName": "Yt-mp4",
                                    "sourceUrl": "https://tools.fast4speed.rsvp/media9/videos/SHOW/sub/1?Authorization=retry-ok",
                                    "priority": 7.9,
                                }
                            ]
                        }
                    }
                }
            )

        with mock.patch("app.services.channels.http.request", side_effect=fake_request), mock.patch(
            "app.services.channels.allanime._get_keys", new=fake_get_keys
        ):
            streams = await AllAnimeChannel().get_streams("SHOW::sub::1")
        self.assertEqual(calls["n"], 2)
        self.assertEqual(len(streams), 1)
        self.assertIn("retry-ok", streams[0].url)

    async def test_get_streams_malformed_ref(self):
        with self.assertRaises(ChannelError) as ctx:
            await AllAnimeChannel().get_streams("just-an-id")
        self.assertFalse(ctx.exception.retryable)

    async def test_get_streams_no_playable_sources(self):
        keys = {"KEY": "00" * 32, "EPOCH": "2953", "BUILDID": "110", "LANE": "k7"}
        with mock.patch(
            "app.services.channels.http.request",
            return_value=_FakeResponse(
                json_data={
                    "data": {
                        "episode": {
                            "sourceUrls": [
                                {
                                    "sourceName": "Luf-Mp4",
                                    "sourceUrl": "https://allanime.day/apivtwo/clock.json?id=x",
                                    "priority": 7.5,
                                }
                            ]
                        }
                    }
                }
            ),
        ), mock.patch("app.services.channels.allanime._get_keys", new=mock.AsyncMock(return_value=keys)):
            with self.assertRaises(ChannelError) as ctx:
                await AllAnimeChannel().get_streams("SHOW::sub::1")
        self.assertTrue(ctx.exception.retryable)


if __name__ == "__main__":
    unittest.main()
