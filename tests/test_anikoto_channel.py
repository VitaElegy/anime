"""Tests for the Anikoto backup channel (docs/RESOURCE_BACKUP_PLAN.md §2.7).

External calls are mocked with real HTML/JSON shapes captured from anikoto.net
and megaplay.buzz/vidtube.site (verified playable 2026-08-13 via Clash 7892);
these tests never touch the internet.
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.routers.watch import _host_allowed
from app.services.channels.anikoto import BASE, AnikotoChannel
from app.services.channels.base import ChannelError
from app.services.channels.registry import registry

# Real /filter?keyword=frieren response (trimmed to two item blocks).
ANIKOTO_SEARCH = """
<div id="list-items" class="ani items">
<div class="item ">
<div class="inner">
<div class="ani poster tip"><a href="https://anikoto.net/watch/frieren-beyond-journey-s-end-c6fbj/ep-1">
<img src="https://cdn.anipixcdn.co/thumbnail/bb6d2babd7797d94d8f4a8600bc9b44e.jpg" alt="Frieren: Beyond Journey&#039;s End" />
</a></div>
<div class="info"><div class="b1">
<a class="name d-title" href="https://anikoto.net/watch/frieren-beyond-journey-s-end-c6fbj/ep-1" data-jp="Sousou no Frieren">Frieren: Beyond Journey&#039;s End</a>
</div></div>
</div>
</div>
<div class="item ">
<div class="inner">
<div class="ani poster tip"><a href="/watch/solo-leveling-ilh08/ep-1">
<img src="/thumbnail/solo.jpg" alt="Solo Leveling">
</a></div>
<div class="info"><div class="b1">
<a class="name d-title" href="/watch/solo-leveling-ilh08/ep-1" data-jp="Ore dake Level Up na Ken">Solo Leveling</a>
</div></div>
</div>
</div>
</div>
"""

# Real /watch/<slug> response (trimmed): watch-main data-id, og:image, h1,
# synopsis; NO inline episodes (lazy AJAX fallback exercised).
ANIKOTO_WATCH = """
<html><head>
<meta property="og:title" content="Watch Frieren: Beyond Journey&#039;s End Online in HD - Anikoto" />
<meta property="og:image" content="https://cdn.anipixcdn.co/thumbnail/bb6d2babd7797d94d8f4a8600bc9b44e.jpg" />
<title>Watch Frieren: Beyond Journey&#039;s End Online in HD - Anikoto</title>
</head><body>
<div id="watch-main" class="layout-page-watchtv " data-id="6351"></div>
<div id="w-info"><div class="binfo"><div class="poster">
<span><img itemprop="image" src="https://cdn.anipixcdn.co/thumbnail/bb6d2babd7797d94d8f4a8600bc9b44e.jpg" alt="Frieren: Beyond Journey&#039;s End" /></span>
</div><div class="info">
<h1 itemprop="name" class="title d-title" data-jp="Sousou no Frieren"> Frieren: Beyond Journey&#039;s End </h1>
<div class="synopsis mb-3"><div class="shorting"><div class="content">During their decade-long quest to defeat the Demon King, the members of the hero's party forge bonds through adventures.</div></div></div>
</div></div></div>
<div id="w-episodes"><div class="loading"></div></div>
</body></html>
"""

# Real /ajax/episode/list/6351 response (trimmed to 3 episodes; data-ids
# shortened with "...").
ANIKOTO_EPISODES = {
    "status": 200,
    "result": """
<div class="head"><div class="dropdown filter type"></div></div>
<ul id="w-episodes" class="ep-range">
<li title="The Journey&#39;s End" data-html="true">
<a href="#" data-id="97908" data-num="1" data-slug="1" data-mal="52991" data-timestamp="1729242913" data-sub="1" data-dub="1" data-ids="SURLAAA..." class="active"><b>1</b><span class="d-title" data-jp="Bōken no Owari">The Journey&#39;s End</span><i></i></a>
</li>
<li title="It Didn&#39;t Have to Be Magic..." data-html="true">
<a href="#" data-id="97909" data-num="2" data-slug="2" data-mal="52991" data-timestamp="1729242913" data-sub="1" data-dub="1" data-ids="KzVBAA..." class=""><b>2</b><span class="d-title" data-jp="Sore wa Hitsuyō na Koto de wa Nakatta">It Didn&#39;t Have to Be Magic...</span><i></i></a>
</li>
<li title="Killing Magic" data-html="true">
<a href="#" data-id="97910" data-num="3" data-slug="3" data-mal="52991" data-timestamp="1729242913" data-sub="1" data-dub="1" data-ids="WlA4AA..." class=""><b>3</b><span class="d-title" data-jp="Killing Magic">Killing Magic</span><i></i></a>
</li>
</ul>
""",
}

# Real /ajax/server/list response (trimmed; 6 servers = 3 names x sub/dub).
ANIKOTO_SERVERS = {
    "status": 200,
    "result": """
<li data-ep-id="97908" data-cmid="animixplay-fqsqfvdf4u" data-sv-id="e54" data-link-id="MTF1...AA">Vidstream-2</li>
<li data-ep-id="97908" data-cmid="animixplay-fqsqfvdf4u" data-sv-id="323" data-link-id="MTF1...BB">HD-1</li>
<li data-ep-id="97908" data-cmid="animixplay-fqsqfvdf4u" data-sv-id="8e4" data-link-id="MTF1...CC">VidPlay-1</li>
<li data-ep-id="97908" data-cmid="animixplay-fqsqfvdf4u" data-sv-id="e54" data-link-id="MTF1...DD">Vidstream-2</li>
<li data-ep-id="97908" data-cmid="animixplay-fqsqfvdf4u" data-sv-id="323" data-link-id="MTF1...EE">HD-1</li>
<li data-ep-id="97908" data-cmid="animixplay-fqsqfvdf4u" data-sv-id="8e4" data-link-id="MTF1...FF">VidPlay-1</li>
""",
}

# Real /ajax/server?get=&sv= responses -> megaplay (poisoned source still
# resolves; playable through the proxy's SegmentStrip) and vidtube (raw TS).
ANIKOTO_SERVER_MEGAPLAY = {
    "status": 200,
    "result": {
        "url": "https://megaplay.buzz/stream/s-2/107257/sub",
        "skip_data": {"intro": [0, 89], "outro": [1460, 1549]},
    },
}
ANIKOTO_SERVER_VIDTUBE = {
    "status": 200,
    "result": {
        "url": "https://vidtube.site/stream/ci9JcmN0dld0dlVVWTYyK0YwcE9RWDF6RHhtd0FyTi9BaHhXS3FrU3JCeEpUZm9TU2ZHMVNEd3BsVjNaemg5UA/sub",
        "skip_data": {"intro": [0, 89], "outro": [1460, 1549]},
    },
}

# Real megaplay embed page (trimmed).
MEGAPLAY_PAGE = """
<html><head><title>File 13461 - MegaPlay</title></head><body></body></html>
"""

# Real vidtube embed page (trimmed).
VIDTUBE_PAGE = """
<html><head><title>File 7599 - VidTube</title></head><body></body></html>
"""

# Real /stream/getSources responses.
MEGAPLAY_SOURCES = {
    "sources": {
        "file": "https://megap.shiora.site/bb6d2babd7797d94d8f4a8600bc9b44e/b7d51fb7e838ee9b60dcdb34b953bc07/master.m3u8"
    },
    "tracks": [
        {"file": "https://1oe.lostproject.club/anime/bb6d2babd7797d94d8f4a8600bc9b44e/subtitles/eng-2.vtt", "label": "English", "kind": "captions", "default": True},
        {"file": "https://1oe.lostproject.club/anime/bb6d2babd7797d94d8f4a8600bc9b44e/subtitles/jpn-1.vtt", "label": "Japanese", "kind": "captions"},
    ],
    "intro": {"start": 0, "end": 89},
    "outro": {"start": 1460, "end": 1549},
}
VIDTUBE_SOURCES = {
    "sources": {
        "file": "https://s1.akirax.buzz/agbf9aa0bc977556508e15754883731bc54h/master.m3u8"
    },
    "tracks": [
        {"file": "https://vidtub.shiora.site/c104d4358b3f8868b3e5e68f9d83ff17/subtitles/English.vtt", "label": "English", "kind": "captions", "default": True},
    ],
    "server": 6,
}


class _FakeResponse:
    """Minimal httpx.Response stand-in (text only)."""

    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _json_response(obj) -> _FakeResponse:
    import json

    return _FakeResponse(json.dumps(obj))


class AnikotoChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_parses_real_fixture(self):
        # Fixture contains Frieren + Solo Leveling; the relevance guard keeps
        # only the query-matching item (noise filter, §2.7).
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(ANIKOTO_SEARCH)
        ) as req:
            hits = await AnikotoChannel().search("Frieren")
        self.assertEqual(len(hits), 1)
        first = hits[0]
        self.assertEqual(first.channel, "anikoto")
        self.assertEqual(first.title, "Frieren: Beyond Journey's End")
        self.assertEqual(first.title_original, "Sousou no Frieren")
        self.assertEqual(first.detail_ref, "frieren-beyond-journey-s-end-c6fbj")
        self.assertEqual(
            first.cover_url,
            "https://cdn.anipixcdn.co/thumbnail/bb6d2babd7797d94d8f4a8600bc9b44e.jpg",
        )
        req.assert_called_once()
        self.assertEqual(req.call_args.args[3], f"{BASE}/filter")
        self.assertEqual(req.call_args.kwargs["params"], {"keyword": "Frieren"})

    async def test_search_keeps_other_title_when_query_matches(self):
        # Same fixture: a Solo Leveling query must keep Solo Leveling instead.
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(ANIKOTO_SEARCH)
        ):
            hits = await AnikotoChannel().search("Solo Leveling")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].detail_ref, "solo-leveling-ilh08")
        self.assertEqual(hits[0].cover_url, f"{BASE}/thumbnail/solo.jpg")

    async def test_search_multiword_phrase_filters_noise(self):
        # Real shape of /filter?keyword=sousou no frieren (trimmed): the site
        # returns ~30 loosely-related items; only the three Frieren entries
        # must survive the relevance guard. The fixture's Solo Leveling block
        # is renamed to an unrelated Overlord title to simulate the noise.
        noisy = ANIKOTO_SEARCH.replace(
            "Solo Leveling", "Overlord Movie 2: The Dark Hero"
        )
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(noisy)
        ):
            hits = await AnikotoChannel().search("sousou no frieren")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].detail_ref, "frieren-beyond-journey-s-end-c6fbj")

    def test_relevance_guard_helpers(self):
        from app.services.channels.anikoto import (
            _is_relevant_result,
            _query_tokens,
            _relevance_token,
        )

        self.assertEqual(_query_tokens("Sousou no Frieren"), ["sousou", "frieren"])
        self.assertEqual(_query_tokens("Frieren: Beyond Journey's End"), ["frieren", "beyond", "journey", "end"])
        self.assertEqual(_relevance_token("sousou no frieren"), "frieren")
        self.assertEqual(_relevance_token("solo leveling"), "leveling")
        self.assertEqual(_relevance_token("葬送的芙莉莲"), "")
        # stopwords-only query -> no filtering
        self.assertEqual(_relevance_token("Season 2 OVA"), "")
        self.assertTrue(_is_relevant_result("Frieren: Beyond Journey's End", "Sousou no Frieren", "sousou no frieren"))
        self.assertFalse(_is_relevant_result("Overlord Movie 2: The Dark Hero", "Overlord: Fukkatsu no Shi", "sousou no frieren"))
        self.assertTrue(_is_relevant_result("Solo Leveling", "Ore dake Level Up na Ken", "Solo Leveling"))
        self.assertFalse(_is_relevant_result("Frieren: Beyond Journey's End", "Sousou no Frieren", "solo leveling"))
        # CJK-only keyword: nothing distinctive -> keep everything
        self.assertTrue(_is_relevant_result("Anything", "", "葬送的芙莉莲"))

    async def test_search_empty_html_returns_empty(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse("<html></html>")
        ):
            hits = await AnikotoChannel().search("Nope Nope Nope")
        self.assertEqual(hits, [])

    async def test_detail_parses_episodes_via_ajax(self):
        async def side_effect(channel, stage, method, url, **kwargs):
            if url.endswith("/watch/frieren-beyond-journey-s-end-c6fbj"):
                return _FakeResponse(ANIKOTO_WATCH)
            if "ajax/episode/list/6351" in url:
                return _json_response(ANIKOTO_EPISODES)
            raise AssertionError(f"unexpected url: {url}")

        with mock.patch(
            "app.services.channels.http.request", side_effect=side_effect
        ) as req:
            detail = await AnikotoChannel().get_detail("frieren-beyond-journey-s-end-c6fbj")
        self.assertEqual(detail.channel, "anikoto")
        self.assertEqual(detail.title, "Frieren: Beyond Journey's End")
        self.assertEqual(
            detail.cover_url,
            "https://cdn.anipixcdn.co/thumbnail/bb6d2babd7797d94d8f4a8600bc9b44e.jpg",
        )
        self.assertTrue(detail.description.startswith("During their decade-long"))
        self.assertEqual(len(detail.groups), 1)
        group = detail.groups[0]
        self.assertEqual(group.title, "Anikoto")
        self.assertEqual(len(group.episodes), 3)
        self.assertEqual(group.episodes[0].title, "The Journey's End")
        self.assertEqual(group.episodes[0].episode_ref.split("::")[0], "frieren-beyond-journey-s-end-c6fbj")
        self.assertEqual(group.episodes[0].episode_ref.split("::")[1], "1")
        self.assertEqual(group.episodes[0].episode_ref.split("::")[3], "52991")
        self.assertEqual(req.call_count, 2)

    async def test_streams_resolve_megaplay_and_vidtube(self):
        ep_ref = "frieren-beyond-journey-s-end-c6fbj::1::SURLAAA...::52991::1729242913::97908"

        async def side_effect(channel, stage, method, url, **kwargs):
            params = kwargs.get("params") or {}
            if "ajax/server/list" in url:
                return _json_response(ANIKOTO_SERVERS)
            if "ajax/server" in url and params.get("get") in ("MTF1...AA", "MTF1...BB", "MTF1...DD", "MTF1...EE"):
                return _json_response(ANIKOTO_SERVER_MEGAPLAY)
            if "ajax/server" in url and params.get("get") in ("MTF1...CC", "MTF1...FF"):
                return _json_response(ANIKOTO_SERVER_VIDTUBE)
            if url.startswith("https://megaplay.buzz/stream/s-2/107257/sub"):
                return _FakeResponse(MEGAPLAY_PAGE)
            if url.startswith("https://megaplay.buzz/stream/getSources"):
                return _json_response(MEGAPLAY_SOURCES)
            if url.startswith("https://vidtube.site/stream/ci9JcmN0dld0dlVVWTYyK0YwcE9RWDF6RHhtd0FyTi9BaHhXS3FrU3JCeEpUZm9TU2ZHMVNEd3BsVjNaemg5UA/sub"):
                return _FakeResponse(VIDTUBE_PAGE)
            if url.startswith("https://vidtube.site/stream/getSources"):
                return _json_response(VIDTUBE_SOURCES)
            raise AssertionError(f"unexpected url: {url}")

        with mock.patch(
            "app.services.channels.http.request", side_effect=side_effect
        ):
            streams = await AnikotoChannel().get_streams(ep_ref)
        self.assertEqual(len(streams), 2)
        # vidtube (raw TS) sorts before megaplay (prefix-stripped).
        self.assertTrue("akirax.buzz" in streams[0].url)
        self.assertTrue("shiora.site" in streams[1].url)
        self.assertEqual(streams[0].type, "hls")
        self.assertIn("Referer", streams[0].headers)
        self.assertIn("VidPlay-1", streams[0].note)
        self.assertIn("2 字幕", streams[1].note)

    async def test_streams_empty_raises_channel_error(self):
        ep_ref = "slug::1::IDS::52991::1729242913::97908"
        with mock.patch(
            "app.services.channels.http.request", return_value=_json_response({"status": 200, "result": ""})
        ):
            with self.assertRaises(ChannelError):
                await AnikotoChannel().get_streams(ep_ref)

    def test_host_allowlist_covers_anikoto_cdns(self):
        self.assertTrue(_host_allowed("https://s1.akirax.buzz/abc/master.m3u8"))
        self.assertTrue(_host_allowed("https://megap.shiora.site/abc/master.m3u8"))
        self.assertTrue(_host_allowed("https://vidtub.shiora.site/abc/subtitles/en.vtt"))
        self.assertTrue(_host_allowed("https://1oe.lostproject.club/anime/x/subtitles/en.vtt"))
        self.assertTrue(_host_allowed("https://megap.shiora.top/abc/master.m3u8"))
        self.assertFalse(_host_allowed("https://evil.example.com/abc/master.m3u8"))

    def test_registry_includes_anikoto(self):
        provider = registry.get("anikoto")
        self.assertIsNotNone(provider)
        self.assertEqual(provider.priority, 57)
        self.assertFalse(provider.external)
        self.assertTrue(provider.supports_streams)


if __name__ == "__main__":
    unittest.main()
