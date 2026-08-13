"""Tests for the online watch channel layer.

All external calls are mocked — these tests never touch the real internet.
Coverage:
- provider parsers (AGE / Libvio / Zzzfun fixtures)
- registry aggregation + circuit breaker
- /api/watch HTTP contract + stream proxy allow/block/Range
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.main import app
from app.models import ChannelDetail, ChannelSearchResult, ChannelStream
from app.routers.watch import rewrite_hls_playlist
from app.services import database as db
from app.services import response_cache
from app.services.channels.age import AgeChannel
from app.services.channels.anilibria import AnilibriaChannel
from app.services.channels.base import ChannelError, ChannelProvider
from app.services.channels.gogoanime import GogoanimeChannel
from app.services.channels.libvio import LibvioChannel
from app.services.channels.registry import ChannelRegistry
from app.services.channels.zzzfun import ZzzfunChannel
from fastapi.testclient import TestClient


class FakeResponse:
    """Minimal stand-in for httpx.Response used by channel fixtures."""

    def __init__(self, text: str = "", json_data=None, status_code: int = 200, headers=None, content: bytes | None = None):
        self.text = text
        self._json = json_data
        self.status_code = status_code
        if content is not None:
            self.content = content
            self.text = content.decode("utf-8", errors="replace")
        else:
            self.content = text.encode("utf-8")
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


AGE_SEARCH = {
    "data": {
        "videos": [
            {"id": 1234, "name": "葬送的芙莉莲", "name_other": "Frieren", "cover": "https://cdn.example/1.jpg", "uptodate": "更新至28集"},
            {"id": 5678, "name": "孤独摇滚", "cover": "https://cdn.example/2.jpg"},
        ]
    }
}

AGE_DETAIL = {
    "video": {
        "name": "葬送的芙莉莲",
        "name_other": "Frieren",
        "intro": "勇者一行击败魔王后……",
        "playlists": {
            "m3u8_1": [["第1集", "/play/1"], ["第2集", "/play/2"]],
            "mp4_1": [["第1集", "/x/1"]],
        },
        "player_label_arr": {"m3u8_1": "第一线路", "mp4_1": "备用"},
        "player_jx": {"zj": "https://player.agedm.org/jx/"},
    }
}

LIBVIO_SEARCH = """
<html><body>
<div class="stui-vodlist__box">
  <a title="葬送的芙莉莲" href="/detail/5060.html" data-original="https://img.example/1.jpg">x</a>
</div>
<div class="stui-vodlist__box">
  <a title="孤独摇滚" href="/detail/5061.html" data-original="https://img.example/2.jpg">y</a>
</div>
</body></html>
"""

LIBVIO_DETAIL = """
<html><body>
<div class="stui-content__detail">
  <h1 class="title">葬送的芙莉莲</h1>
  <span class="detail-content">勇者一行……</span>
</div>
<a class="pic"><img data-original="https://img.example/1.jpg" /></a>
<div class="stui-pannel__head clearfix"><h3> 线路一 </h3></div>
<ul class="stui-content__playlist clearfix">
  <li><a href="/play/4988-1-1.html">第1集</a></li>
  <li><a href="/play/4988-1-2.html">第2集</a></li>
</ul>
</body></html>
"""

LIBVIO_STREAMS = '<html><script>var player_aaaa={"url":"https%3A%2F%2Fcdn.example.com%2Fa%2Fb.m3u8"};</script></html>'

ZZZFUN_SEARCH = {
    "data": [
        {"videoId": "v1", "videoName": "葬送的芙莉莲", "videoImg": "https://img.example/1.jpg", "videoClass": "番剧"},
    ]
}

ZZZFUN_DETAIL = {
    "data": {
        "videoName": "葬送的芙莉莲",
        "videoImg": "https://img.example/1.jpg",
        "videoDoc": "简介\r\n第二行",
        "videoClass": "番剧",
        "videoSets": [
            {"load": "线路 I", "list": [{"ji": "第1集", "playid": "p1"}, {"ji": "第2集", "playid": "p2"}]}
        ],
    }
}

ZZZFUN_STREAMS = {"data": {"videoplayurl": "https://zzzhls.example.com/live/a.m3u8"}}


class AgeChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_parses_fixture(self):
        with mock.patch("app.services.channels.http.request", return_value=FakeResponse(json_data=AGE_SEARCH)):
            hits = await AgeChannel().search("芙莉莲")
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0].channel, "age")
        self.assertEqual(hits[0].title, "葬送的芙莉莲")
        self.assertEqual(hits[0].detail_ref, "1234")
        self.assertEqual(hits[1].detail_ref, "5678")

    async def test_detail_keeps_only_m3u8_playlists(self):
        with mock.patch("app.services.channels.http.request", return_value=FakeResponse(json_data=AGE_DETAIL)):
            detail = await AgeChannel().get_detail("1234")
        self.assertEqual(detail.title, "葬送的芙莉莲")
        self.assertEqual(len(detail.groups), 1)
        group = detail.groups[0]
        self.assertEqual(group.title, "第一线路")
        self.assertEqual(len(group.episodes), 2)
        self.assertEqual(group.episodes[0].episode_ref, "https://player.agedm.org/jx//play/1")

    async def test_streams_extracts_vurl(self):
        with mock.patch(
            "app.services.channels.http.request",
            return_value=FakeResponse(text="<script>Vurl = 'https://cdn.example.com/a.m3u8'</script>"),
        ):
            streams = await AgeChannel().get_streams("https://player.agedm.org/jx/x")
        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0].url, "https://cdn.example.com/a.m3u8")
        self.assertEqual(streams[0].type, "hls")


class LibvioChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_parses_html(self):
        with mock.patch("app.services.channels.http.request", return_value=FakeResponse(text=LIBVIO_SEARCH)):
            hits = await LibvioChannel().search("芙莉莲")
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0].title, "葬送的芙莉莲")
        self.assertEqual(hits[0].detail_ref, "/detail/5060.html")

    async def test_detail_parses_episode_groups(self):
        with mock.patch("app.services.channels.http.request", return_value=FakeResponse(text=LIBVIO_DETAIL)):
            detail = await LibvioChannel().get_detail("/detail/5060.html")
        self.assertEqual(detail.title, "葬送的芙莉莲")
        self.assertEqual(len(detail.groups), 1)
        self.assertEqual(detail.groups[0].title, "线路一")
        self.assertEqual(detail.groups[0].episodes[1].episode_ref, "/play/4988-1-2.html")

    async def test_streams_signs_url(self):
        with mock.patch("app.services.channels.http.request", return_value=FakeResponse(text=LIBVIO_STREAMS)):
            streams = await LibvioChannel().get_streams("/play/4988-1-1.html")
        self.assertEqual(len(streams), 1)
        self.assertIn("sign=", streams[0].url)
        self.assertIn("t=", streams[0].url)
        self.assertIn("https://cdn.example.com/a/b.m3u8", streams[0].url)


class ZzzfunChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_parses_fixture(self):
        with mock.patch("app.services.channels.http.request", return_value=FakeResponse(json_data=ZZZFUN_SEARCH)):
            hits = await ZzzfunChannel().search("芙莉莲")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].detail_ref, "v1")

    async def test_detail_parses_groups(self):
        with mock.patch("app.services.channels.http.request", return_value=FakeResponse(json_data=ZZZFUN_DETAIL)):
            detail = await ZzzfunChannel().get_detail("v1")
        self.assertEqual(detail.description, "简介第二行")
        self.assertEqual(len(detail.groups), 1)
        self.assertEqual(detail.groups[0].episodes[1].episode_ref, "p2")

    async def test_streams_parses_hls(self):
        with mock.patch("app.services.channels.http.request", return_value=FakeResponse(json_data=ZZZFUN_STREAMS)):
            streams = await ZzzfunChannel().get_streams("p1")
        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0].type, "hls")
        self.assertEqual(streams[0].format, "m3u8")


ANILIBRIA_SEARCH = [
    {
        "id": 9293,
        "alias": "bocchi-the-rock",
        "year": 2022,
        "name": {"main": "Одинокий рокер!", "english": "BOCCHI THE ROCK!", "alternative": None},
        "poster": "/storage/releases/posters/9293/pqI3PQ8v8c7tlFHuPjsSbAbHrbm8madK.jpg",
        "is_ongoing": False,
        "description": "Hitori Gotou is a shy girl.",
    }
]

ANILIBRIA_DETAIL = {
    "id": 9293,
    "name": {"main": "Одинокий рокер!", "english": "BOCCHI THE ROCK!", "alternative": None},
    "poster": {
        "src": "/storage/releases/posters/9293/pqI3PQ8v8c7tlFHuPjsSbAbHrbm8madK.jpg",
        "optimized": {"preview": "/storage/releases/posters/9293/preview.jpg"},
    },
    "description": "Hitori Gotou is a shy girl who plays guitar.",
    "episodes": [
        {"id": "ep-1", "ordinal": 1, "name_english": None, "hls_1080": "https://cache.libria.fun/1/1080.m3u8", "hls_720": "https://cache.libria.fun/1/720.m3u8", "hls_480": "https://cache.libria.fun/1/480.m3u8"},
        {"id": "ep-2", "ordinal": 2, "name_english": None, "hls_1080": "https://cache.libria.fun/2/1080.m3u8", "hls_720": "https://cache.libria.fun/2/720.m3u8", "hls_480": "https://cache.libria.fun/2/480.m3u8"},
    ],
}

ANILIBRIA_EPISODE = {
    "id": "ep-1",
    "ordinal": 1,
    "hls_1080": "https://cache.libria.fun/1/1080.m3u8",
    "hls_720": "https://cache.libria.fun/1/720.m3u8",
    "hls_480": "https://cache.libria.fun/1/480.m3u8",
    "release": {"id": 9293},
}

GOGO_SEARCH = """
<html><body>
<ul class="items">
  <li>
    <div class="img"><a href="/category/one-piece" title="One Piece"><img src="/poster/one-piece.jpg"></a></div>
    <p class="name"><a href="/category/one-piece" title="One Piece">One Piece</a></p>
  </li>
  <li>
    <div class="img"><a href="/category/one-piece-dub" title="One Piece (Dub)"><img src="/poster/dub.jpg"></a></div>
    <p class="name"><a href="/category/one-piece-dub" title="One Piece (Dub)">One Piece (Dub)</a></p>
  </li>
</ul>
</body></html>
"""

GOGO_DETAIL = """
<html><body>
<div class="anime_info_body_bg">
  <img src="/poster/one-piece.jpg">
  <h1>One Piece</h1>
</div>
<input type="hidden" value="568" id="movie_id" class="movie_id"/>
<ul id="episode_related">
  <li><a href="/one-piece-episode-2"><div class="name"><span>EP</span> 2</div></a></li>
  <li><a href="/one-piece-episode-1"><div class="name"><span>EP</span> 1</div></a></li>
  <li><a href="/red-river-episode-6"><div class="name"><span>EP</span> 6</div></a></li>
</ul>
</body></html>
"""

GOGO_WATCH = """
<html><body>
<div class="play-video">
  <iframe data-video="https://vidmoly.biz/embed-x.html"></iframe>
  <iframe data-video="https://gogoanime.me.uk/newplayer.php?mal_id=21&ep=1173&category=sub"></iframe>
</div>
</body></html>
"""

GOGO_NEWPLAYER = """
<html><body>
<iframe src="https://megaplay.buzz/stream/mal/21/1173/sub?autostart=true"></iframe>
</body></html>
"""

GOGO_MEGAPLAY = """
<html><body>
<div class="player" data-id="178635"></div>
</body></html>
"""

GOGO_SOURCES_NEW = {"sources": {"file": "https://ncdn.mewstream.buzz/x/master.m3u8"}, "server": "4", "tracks": []}
GOGO_SOURCES = {"sources": {"file": "https://megap.mikora.top/x/master.m3u8"}, "server": "3", "tracks": []}


class AnilibriaChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_parses_fixture(self):
        with mock.patch("app.services.channels.http.request", return_value=FakeResponse(json_data=ANILIBRIA_SEARCH)):
            hits = await AnilibriaChannel().search("Bocchi")
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit.channel, "anilibria")
        self.assertEqual(hit.title, "BOCCHI THE ROCK!")
        self.assertEqual(hit.detail_ref, "9293")
        self.assertTrue(hit.cover_url.startswith("https://anilibria.top/"))
        self.assertEqual(hit.year, "2022")

    async def test_detail_parses_episodes_sorted(self):
        with mock.patch("app.services.channels.http.request", return_value=FakeResponse(json_data=ANILIBRIA_DETAIL)):
            detail = await AnilibriaChannel().get_detail("9293")
        self.assertEqual(detail.channel, "anilibria")
        self.assertEqual(detail.title, "BOCCHI THE ROCK!")
        self.assertEqual(len(detail.groups), 1)
        eps = detail.groups[0].episodes
        self.assertEqual(len(eps), 2)
        self.assertEqual(eps[0].title, "第1集")
        ref = AnilibriaChannel._parse_episode_ref(eps[0].episode_ref)
        self.assertEqual(ref, (9293, "ep-1"))

    async def test_streams_parses_hls_qualities(self):
        with mock.patch("app.services.channels.http.request", return_value=FakeResponse(json_data=ANILIBRIA_EPISODE)):
            streams = await AnilibriaChannel().get_streams('{"release_id":9293,"episode_id":"ep-1"}')
        self.assertEqual([s.quality for s in streams], ["1080p", "720p", "480p"])
        self.assertTrue(all(s.type == "hls" for s in streams))
        self.assertEqual(streams[0].url, "https://cache.libria.fun/1/1080.m3u8")


class GogoanimeChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_parses_html(self):
        with mock.patch("app.services.channels.http.request", return_value=FakeResponse(text=GOGO_SEARCH)):
            hits = await GogoanimeChannel().search("one piece")
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0].channel, "gogoanime")
        self.assertEqual(hits[0].detail_ref, "/category/one-piece")
        self.assertTrue(hits[0].cover_url.startswith("https://www.gogoanime.is/"))

    async def test_detail_parses_only_own_episodes_sorted(self):
        with mock.patch("app.services.channels.http.request", return_value=FakeResponse(text=GOGO_DETAIL)):
            detail = await GogoanimeChannel().get_detail("/category/one-piece")
        self.assertEqual(detail.title, "One Piece")
        self.assertEqual(len(detail.groups), 1)
        eps = detail.groups[0].episodes
        self.assertEqual(len(eps), 2)
        self.assertEqual(eps[0].title, "第1集")
        slug, ep = GogoanimeChannel._parse_episode_ref(eps[0].episode_ref)
        self.assertEqual((slug, ep), ("one-piece", 1))
        # The red-river-episode-6 link (a "last episodes" cross-link) must be ignored.
        self.assertFalse(any("red-river" in e.episode_ref for e in eps))

    async def test_streams_full_chain(self):
        responses = [
            FakeResponse(text=GOGO_WATCH),
            FakeResponse(text=GOGO_NEWPLAYER),
            FakeResponse(text=GOGO_MEGAPLAY),
            FakeResponse(json_data=GOGO_SOURCES_NEW),
            FakeResponse(json_data=GOGO_SOURCES),
        ]
        with mock.patch("app.services.channels.http.request", side_effect=responses) as mocked:
            streams = await GogoanimeChannel().get_streams('{"slug":"one-piece","ep":1173}')
        self.assertEqual(len(streams), 2)
        self.assertEqual(streams[0].url, "https://ncdn.mewstream.buzz/x/master.m3u8")
        self.assertEqual(streams[1].url, "https://megap.mikora.top/x/master.m3u8")
        urls = [str(call.args[3]) for call in mocked.call_args_list]
        self.assertTrue(any("newplayer.php" in u for u in urls))
        self.assertTrue(any("getSourcesNew" in u for u in urls))


class HlsSanitizerTests(unittest.TestCase):
    BASE = "https://megap.norami.top/abc/def/master.m3u8"

    def test_rewrites_all_uris_through_proxy_keeps_segments(self):
        playlist = """#EXTM3U
#EXT-X-VERSION:3
#EXTINF:4.004000,
https://p19-ad-site-sign-sg.tiktokcdn.com/ad/image?x=1
#EXTINF:10.0,
index-f1-v1-a1.m3u8
#EXTINF:4.004000,
https://p16-ad-site-sign-sg.tiktokcdn.com/ad/image?x=2
#EXTINF:10.0,
https://p6oaa-d2.trycloud.pro/anime/seg-00001.jpg?mod=1
"""
        cleaned = rewrite_hls_playlist(playlist, self.BASE, referer="https://megaplay.buzz/")
        # Nothing is dropped: megaplay "ad" segments are the real MPEG-TS
        # payloads (PNG-wrapped with a 252-byte prefix the proxy strips).
        self.assertIn("tiktokcdn", cleaned)
        # Relative URI resolved against the playlist base and proxied.
        self.assertIn("/api/watch/proxy/stream?url=https%3A%2F%2Fmegap.norami.top%2Fabc%2Fdef%2Findex-f1-v1-a1.m3u8", cleaned)
        self.assertIn("referer=https%3A%2F%2Fmegaplay.buzz%2F", cleaned)
        # Absolute segments (ad-look and regular) both proxied.
        self.assertIn("url=https%3A%2F%2Fp19-ad-site-sign-sg.tiktokcdn.com%2Fad%2Fimage", cleaned)
        self.assertIn("url=https%3A%2F%2Fp6oaa-d2.trycloud.pro%2Fanime%2Fseg-00001.jpg", cleaned)
        lines = [ln for ln in cleaned.splitlines() if ln.startswith("#EXTINF")]
        self.assertEqual(len(lines), 4)
        # Every non-comment line became a same-origin proxy URL.
        for ln in cleaned.splitlines():
            if ln.strip() and not ln.startswith("#"):
                self.assertTrue(ln.startswith("/api/watch/proxy/stream?"), ln)

    def test_rewrites_uri_tags_keeps_iframe(self):
        playlist = """#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="key.bin"
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=53136,RESOLUTION=640x360,URI="iframes-f3-v1-a1.m3u8"
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=1,URI="https://p19-ad-site-sign-sg.tiktokcdn.com/x"
seg-00000.ts
"""
        cleaned = rewrite_hls_playlist(playlist, self.BASE)
        self.assertIn('URI="/api/watch/proxy/stream?url=https%3A%2F%2Fmegap.norami.top%2Fabc%2Fdef%2Fkey.bin"', cleaned)
        self.assertIn("iframes-f3-v1-a1.m3u8", cleaned)
        # I-FRAME tags are kept (not dropped) and proxied.
        self.assertIn("tiktokcdn", cleaned)
        self.assertEqual(cleaned.count("#EXT-X-I-FRAME-STREAM-INF"), 2)
        self.assertIn("/api/watch/proxy/stream?url=https%3A%2F%2Fmegap.norami.top%2Fabc%2Fdef%2Fseg-00000.ts", cleaned)

    def test_strip_marker_detection(self):
        from app.routers.watch import _should_strip_prefix

        self.assertTrue(_should_strip_prefix("https://p19-ad-site-sign-sg.tiktokcdn.com/ad/x"))
        self.assertTrue(_should_strip_prefix("https://p6oaa-d2.trycloud.pro/anime/seg-1.jpg"))
        self.assertTrue(_should_strip_prefix("https://x.ibyteimg.com/seg"))
        self.assertFalse(_should_strip_prefix("https://megap.norami.top/abc/master.m3u8"))
        self.assertFalse(_should_strip_prefix("not a url"))


    def test_proxy_url_strips_url_fragment(self):
        # Dailymotion child manifests carry #cell=<cache> hints that must never
        # be forwarded to the CDN upstream (they break segment resolution).
        from app.routers.watch import _build_proxy_url

        proxied = _build_proxy_url("https://vod-abc.dmcdn.net/video/x/index.m3u8#cell=cf3")
        self.assertIn("url=https%3A%2F%2Fvod-abc.dmcdn.net%2Fvideo%2Fx%2Findex.m3u8", proxied)
        self.assertNotIn("cell", proxied)
        self.assertNotIn("#", proxied)


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.expand_patch = mock.patch(
            "app.services.channels.registry._expand_keywords",
            new=mock.AsyncMock(return_value=["测试"]),
        )
        self.expand_patch.start()
        self.addCleanup(self.expand_patch.stop)
        self.addCleanup(response_cache.clear_l1_for_tests)

    async def test_aggregation_skips_unhealthy_and_merges_results(self):
        class OkProvider(ChannelProvider):
            id = "ok"
            name = "OK"

            async def search(self, keyword, page=1):
                return [ChannelSearchResult(channel=self.id, title=keyword, detail_ref="r1")]

        class FlakyProvider(ChannelProvider):
            id = "flaky"
            name = "Flaky"

            async def search(self, keyword, page=1):
                raise ChannelError(self.id, "search", "boom")

        reg = ChannelRegistry()
        reg.register_all([OkProvider(), FlakyProvider()])

        # First search: flaky fails once but remains healthy (threshold 3).
        hits = await reg.search("测试")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].channel, "ok")

        # 2 more failures trip the circuit.
        for _ in range(2):
            await reg.search("测试")
        infos = {c.id: c for c in reg.list_channels()}
        self.assertFalse(infos["flaky"].healthy)
        self.assertTrue(infos["ok"].healthy)

        # After the circuit is open, flaky is skipped entirely.
        with mock.patch.object(FlakyProvider, "search", side_effect=AssertionError("must not be called")):
            hits = await reg.search("测试")
        self.assertEqual(len(hits), 1)

    async def test_aggregation_skips_disabled_providers(self):
        class DisabledProvider(ChannelProvider):
            id = "disabled"
            name = "Disabled"
            enabled = False

            async def search(self, keyword, page=1):
                raise AssertionError("disabled provider must not be called")

        class OkProvider(ChannelProvider):
            id = "ok"
            name = "OK"

            async def search(self, keyword, page=1):
                return [ChannelSearchResult(channel=self.id, title=keyword, detail_ref="r1")]

        reg = ChannelRegistry()
        reg.register_all([OkProvider(), DisabledProvider()])
        hits = await reg.search("测试")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].channel, "ok")
        infos = {c.id: c for c in reg.list_channels()}
        self.assertFalse(infos["disabled"].healthy)
        self.assertTrue(infos["ok"].healthy)

    async def test_aggregation_timeout_keeps_healthy_results(self):
        class SlowProvider(ChannelProvider):
            id = "slow"
            name = "Slow"

            async def search(self, keyword, page=1):
                await asyncio.sleep(0.3)
                return [ChannelSearchResult(channel=self.id, title="slow", detail_ref="r1")]

        class FastProvider(ChannelProvider):
            id = "fast"
            name = "Fast"

            async def search(self, keyword, page=1):
                return [ChannelSearchResult(channel=self.id, title="fast", detail_ref="r1")]

        reg = ChannelRegistry()
        reg.register_all([FastProvider(), SlowProvider()])
        with mock.patch("app.services.channels.registry.SEARCH_AGGREGATE_TIMEOUT_SECONDS", 0.05):
            hits = await reg.search("测试")
        self.assertEqual([h.channel for h in hits], ["fast"])

    async def test_detail_and_streams_raise_on_unknown_channel(self):
        reg = ChannelRegistry()
        with self.assertRaises(LookupError):
            await reg.detail("nope", "ref")
        with self.assertRaises(LookupError):
            await reg.streams("nope", "ref")

    async def test_list_channels_orders_by_priority(self):
        class LowProvider(ChannelProvider):
            id = "low"
            name = "Low"
            priority = 10

            async def search(self, keyword, page=1):
                return []

        class MidProvider(ChannelProvider):
            id = "mid"
            name = "Mid"
            priority = 55

            async def search(self, keyword, page=1):
                return []

        class HighProvider(ChannelProvider):
            id = "high"
            name = "High"
            priority = 100

            async def search(self, keyword, page=1):
                return []

        reg = ChannelRegistry()
        reg.register_all([HighProvider(), LowProvider(), MidProvider()])
        self.assertEqual([c.id for c in reg.list_channels()], ["low", "mid", "high"])

    async def test_search_dedupes_same_detail_ref_from_one_channel(self):
        # AnimeHeaven returns two title variants for ONE anime (same opaque
        # detail_ref) — must collapse to a single card (docs/RESOURCE_BACKUP_PLAN.md §1.2).
        class DupeProvider(ChannelProvider):
            id = "dupe"
            name = "Dupe"

            async def search(self, keyword, page=1):
                return [
                    ChannelSearchResult(channel=self.id, title="Sousou no Frieren", detail_ref="ak2gr"),
                    ChannelSearchResult(channel=self.id, title="Frieren: Beyond Journey's End", detail_ref="ak2gr"),
                ]

        reg = ChannelRegistry()
        reg.register(DupeProvider())
        hits = await reg.search("frieren")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].detail_ref, "ak2gr")

    async def test_search_preserves_provider_order_within_channel(self):
        # The aggregator groups by (priority, channel) with a STABLE sort, so a
        # provider's own ranking survives (e.g. AllAnime sorts the main series
        # first by episode count). Title-based re-sorting would bury it.
        class RankedProvider(ChannelProvider):
            id = "ranked"
            name = "Ranked"
            priority = 60

            async def search(self, keyword, page=1):
                return [
                    ChannelSearchResult(channel=self.id, title="Z Main Series", detail_ref="z1"),
                    ChannelSearchResult(channel=self.id, title="A Spin-off", detail_ref="a1"),
                ]

        reg = ChannelRegistry()
        reg.register(RankedProvider())
        hits = await reg.search("x")
        self.assertEqual([h.detail_ref for h in hits], ["z1", "a1"])

    async def test_search_orders_results_by_priority(self):
        class MainProvider(ChannelProvider):
            id = "main"
            name = "Main"
            priority = 10

            async def search(self, keyword, page=1):
                return [ChannelSearchResult(channel=self.id, title="A Main", detail_ref="m1")]

        class BackupProvider(ChannelProvider):
            id = "backup"
            name = "Backup"
            priority = 60

            async def search(self, keyword, page=1):
                return [ChannelSearchResult(channel=self.id, title="Z Backup", detail_ref="b1")]

        reg = ChannelRegistry()
        reg.register_all([BackupProvider(), MainProvider()])
        hits = await reg.search("x")
        self.assertEqual([h.channel for h in hits], ["main", "backup"])


class WatchApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_channels_endpoint_returns_registered_channels(self):
        resp = self.client.get("/api/watch/channels")
        self.assertEqual(resp.status_code, 200)
        ids = {c["id"] for c in resp.json()}
        self.assertTrue({"age", "libvio", "zzzfun", "anilibria", "gogoanime", "bilibili"} <= ids)

    def test_search_endpoint_contract(self):
        fake_registry = mock.Mock()
        fake_registry.search = mock.AsyncMock(
            return_value=[
                ChannelSearchResult(channel="age", title="葬送的芙莉莲", detail_ref="1234")
            ]
        )
        with mock.patch("app.routers.watch.registry", fake_registry):
            resp = self.client.get("/api/watch/search", params={"q": "芙莉莲"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["channel"], "age")

    def test_detail_and_streams_endpoints(self):
        fake_registry = mock.Mock()
        fake_registry.detail = mock.AsyncMock(return_value={"channel": "age", "title": "x", "groups": []})
        fake_registry.streams = mock.AsyncMock(return_value=[{"type": "hls", "url": "https://cdn.example/a.m3u8"}])
        with mock.patch("app.routers.watch.registry", fake_registry):
            detail = self.client.get("/api/watch/age/detail", params={"ref": "1234"})
            streams = self.client.get("/api/watch/age/streams", params={"ref": "ep1"})
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["channel"], "age")
        self.assertEqual(streams.status_code, 200)
        self.assertEqual(streams.json()[0]["type"], "hls")

    def test_unknown_channel_returns_404(self):
        fake_registry = mock.Mock()
        fake_registry.detail = mock.AsyncMock(side_effect=LookupError("nope"))
        fake_registry.streams = mock.AsyncMock(side_effect=LookupError("nope"))
        with mock.patch("app.routers.watch.registry", fake_registry):
            detail = self.client.get("/api/watch/nope/detail", params={"ref": "x"})
            streams = self.client.get("/api/watch/nope/streams", params={"ref": "x"})
        self.assertEqual(detail.status_code, 404)
        self.assertEqual(streams.status_code, 404)

    def test_stream_proxy_blocks_non_whitelisted_host(self):
        resp = self.client.get("/api/watch/proxy/stream", params={"url": "http://evil.example.com/x.m3u8"})
        self.assertEqual(resp.status_code, 403)

    def test_stream_proxy_forwards_whitelisted_host_with_range(self):
        class FakeClient:
            async def get(self, url, headers=None):
                self.received_headers = headers or {}
                return FakeResponse(
                    text="seg",
                    status_code=206,
                    headers={"content-range": "bytes 0-2/10"},
                )

        fake_client = FakeClient()
        with mock.patch("app.services.channels.http.get_client", return_value=fake_client):
            resp = self.client.get(
                "/api/watch/proxy/stream",
                params={"url": "https://cdn.agedm.org/seg.ts", "referer": "https://m.agedm.org/"},
                headers={"Range": "bytes=0-2"},
            )
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(fake_client.received_headers.get("Referer"), "https://m.agedm.org/")
        self.assertEqual(fake_client.received_headers.get("Range"), "bytes=0-2")
        self.assertEqual(resp.headers.get("content-range"), "bytes 0-2/10")
        self.assertEqual(resp.content, b"seg")

    def test_stream_proxy_rewrites_hls_manifest(self):
        class FakeClient:
            async def get(self, url, headers=None):
                return FakeResponse(
                    text='#EXTM3U\n#EXTINF:10.0,\nseg-00000.ts',
                    status_code=200,
                    headers={"content-type": "application/vnd.apple.mpegurl"},
                )

        fake_client = FakeClient()
        with mock.patch("app.services.channels.http.get_client", return_value=fake_client):
            resp = self.client.get(
                "/api/watch/proxy/stream",
                params={"url": "https://cdn.agedm.org/a/master.m3u8"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        self.assertIn("/api/watch/proxy/stream?url=", body)
        self.assertIn("https%3A%2F%2Fcdn.agedm.org%2Fa%2Fseg-00000.ts", body)
        self.assertNotIn("\nseg-00000.ts\n", body)

    def test_stream_proxy_strips_obfuscated_segment_prefix(self):
        class FakeClient:
            async def get(self, url, headers=None):
                self.received_headers = headers or {}
                return FakeResponse(
                    content=b"\x89PNG\r\n" + b"\x00" * 246 + b"\x47\x40\x11" + b"\x01\x02\x03",
                    status_code=200,
                    headers={"content-type": "image/png"},
                )

        fake_client = FakeClient()
        with mock.patch("app.services.channels.http.get_client", return_value=fake_client):
            resp = self.client.get(
                "/api/watch/proxy/stream",
                params={"url": "https://p19-ad-site-sign-sg.tiktokcdn.com/ad/seg-1?x=1"},
                headers={"Range": "bytes=0-99"},
            )
        self.assertEqual(resp.status_code, 200)
        # 252-byte junk prefix removed; raw MPEG-TS payload returned.
        self.assertEqual(resp.content, b"\x47\x40\x11\x01\x02\x03")
        self.assertEqual(resp.headers.get("content-type"), "video/mp2t")
        # Range is not forwarded upstream for stripped segments.
        self.assertNotIn("Range", fake_client.received_headers)
        self.assertNotIn("content-range", resp.headers)

    def test_stream_proxy_keeps_non_stripped_segment_intact(self):
        class FakeClient:
            async def get(self, url, headers=None):
                return FakeResponse(
                    content=b"\x47\x40\x11\x01\x02\x03",
                    status_code=200,
                    headers={"content-type": "video/mp2t"},
                )

        fake_client = FakeClient()
        with mock.patch("app.services.channels.http.get_client", return_value=fake_client):
            resp = self.client.get(
                "/api/watch/proxy/stream",
                params={"url": "https://megap.norami.top/abc/seg-1.ts"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"\x47\x40\x11\x01\x02\x03")
        self.assertEqual(resp.headers.get("content-type"), "video/mp2t")

    def test_external_channel_returns_official_url(self):
        fake_registry = mock.Mock()
        fake_registry.external_url = mock.Mock(return_value="https://www.bilibili.com/bangumi/play/ss123")
        with mock.patch("app.routers.watch.registry", fake_registry):
            resp = self.client.get("/api/watch/bilibili/external", params={"ref": "123"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["url"], "https://www.bilibili.com/bangumi/play/ss123")


class _TempDBCacheTestCase(unittest.IsolatedAsyncioTestCase):
    """Hermetic cache tests: temp SQLite so no state leaks from real runs."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tempdir.name) / "channel-cache.db"
        db.init_db()
        response_cache.clear_l1_for_tests()
        self.addCleanup(self._restore)

    def _restore(self):
        db.DB_PATH = self.original_db_path
        response_cache.clear_l1_for_tests()
        self.tempdir.cleanup()


class KeywordExpansionTests(_TempDBCacheTestCase):
    async def test_static_map_falls_back_when_remote_lookup_is_down(self):
        from app.services.keyword_expand import expand_keywords

        with mock.patch("app.services.keyword_expand.bangumi.search", side_effect=RuntimeError("offline")):
            alts = await expand_keywords("孤独摇滚")
        self.assertIn("孤独摇滚", alts)
        self.assertIn("BOCCHI THE ROCK!", alts)
        self.assertIn("Bocchi", alts)

    async def test_static_map_short_query_match(self):
        from app.services.keyword_expand import expand_keywords

        with mock.patch("app.services.keyword_expand.bangumi.search", side_effect=RuntimeError("offline")):
            alts = await expand_keywords("海贼王")
        self.assertIn("One Piece", alts)

    async def test_static_map_donghua_reaches_animexin_english_names(self):
        # Regression: AnimeXin indexes English/romaji titles (verified
        # 2026-08-13 on animexin.dev) — Chinese-only search must still expand
        # to the English name even when Bangumi is unreachable.
        from app.services.keyword_expand import expand_keywords

        with mock.patch("app.services.keyword_expand.bangumi.search", side_effect=RuntimeError("offline")):
            alts = await expand_keywords("无上神帝")
        self.assertIn("无上神帝", alts)
        self.assertIn("Supreme God Emperor", alts)
        self.assertIn("Wu Shang Shen Di", alts)

        alts = await expand_keywords("雪鹰领主")
        self.assertIn("Xue Ying", alts)
        self.assertIn("Snow Eagle Lord", alts)


        calls: list[str] = []

        class ExpandingProvider(ChannelProvider):
            id = "exp"
            name = "Exp"

            async def search(self, keyword, page=1):
                calls.append(keyword)
                return [ChannelSearchResult(channel=self.id, title="孤独摇滚", detail_ref=f"r-{keyword}")]

        reg = ChannelRegistry()
        reg.register(ExpandingProvider())
        with mock.patch(
            "app.services.channels.registry._expand_keywords",
            new=mock.AsyncMock(return_value=["测试", "Bocchi the Rock!", "ぼっち・ざ・ろっく！"]),
        ):
            hits = await reg.search("测试")
        self.assertEqual(calls, ["测试", "Bocchi the Rock!", "ぼっち・ざ・ろっく！"])
        # Same normalized title from three alternatives → one hit, first wins.
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].detail_ref, "r-测试")

    async def test_search_falls_back_to_original_keyword_on_expand_error(self):
        class SimpleProvider(ChannelProvider):
            id = "simple"
            name = "Simple"

            async def search(self, keyword, page=1):
                return [ChannelSearchResult(channel=self.id, title=keyword, detail_ref="r1")]

        reg = ChannelRegistry()
        reg.register(SimpleProvider())
        with mock.patch(
            "app.services.channels.registry.expand_keywords",
            new=mock.AsyncMock(side_effect=RuntimeError("boom")),
        ):
            hits = await reg.search("测试")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].detail_ref, "r1")


class ChannelCacheTests(_TempDBCacheTestCase):
    """TTL caching per docs/CHANNEL_ARCHITECTURE.md §1.7."""

    async def test_search_results_are_cached_within_ttl(self):
        calls: list[str] = []

        class CachedProvider(ChannelProvider):
            id = "cached"
            name = "Cached"

            async def search(self, keyword, page=1):
                calls.append(keyword)
                return [ChannelSearchResult(channel=self.id, title=keyword, detail_ref="r")]

        reg = ChannelRegistry()
        reg.register(CachedProvider())
        with mock.patch(
            "app.services.channels.registry._expand_keywords",
            new=mock.AsyncMock(return_value=["剧"]),
        ):
            first = await reg.search("剧")
            second = await reg.search("剧")
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(calls, ["剧"])  # second search served from cache

    async def test_detail_is_cached_within_ttl(self):
        calls: list[str] = []

        class CachedProvider(ChannelProvider):
            id = "cached-detail"
            name = "CachedDetail"

            async def search(self, keyword, page=1):
                return []

            async def get_detail(self, detail_ref):
                calls.append(detail_ref)
                return ChannelDetail(channel=self.id, title="葬送的芙莉莲", groups=[])

        reg = ChannelRegistry()
        reg.register(CachedProvider())
        first = await reg.detail("cached-detail", "ref1")
        second = await reg.detail("cached-detail", "ref1")
        self.assertEqual(calls, ["ref1"])
        self.assertEqual(first.title, "葬送的芙莉莲")
        self.assertEqual(second.title, "葬送的芙莉莲")

    async def test_streams_are_cached_in_memory_only(self):
        calls: list[str] = []

        class CachedProvider(ChannelProvider):
            id = "cached-streams"
            name = "CachedStreams"

            async def search(self, keyword, page=1):
                return []

            async def get_streams(self, episode_ref):
                calls.append(episode_ref)
                return [ChannelStream(type="hls", url="https://cdn.example.com/a.m3u8")]

        reg = ChannelRegistry()
        reg.register(CachedProvider())
        first = await reg.streams("cached-streams", "ep1")
        second = await reg.streams("cached-streams", "ep1")
        self.assertEqual(calls, ["ep1"])
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(first[0].url, second[0].url)


class DailymotionProxyTests(unittest.TestCase):
    """Stream proxy must route Dailymotion HLS through curl_cffi (chrome124).

    DM's CDN 403s the shared httpx TLS fingerprint (verified 2026-08-13), so
    the proxy uses curl_cffi + Referer/Origin and strips #cell fragments.
    """

    class FakeCurlSession:
        instances: list[DailymotionProxyTests.FakeCurlSession] = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            type(self).instances.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            self.url = url
            master = (
                "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1280000,RESOLUTION=1280x720\n"
                "https://vod-abc.dmcdn.net/video/x/720.m3u8#cell=cf3\n"
                "#EXT-X-STREAM-INF:BANDWIDTH=2560000,RESOLUTION=1920x1080\n"
                "https://vod-abc.dmcdn.net/video/x/1080.m3u8#cell=cf3\n"
            )
            return FakeResponse(text=master, status_code=200, headers={"content-type": "application/vnd.apple.mpegurl"})

    def test_dailymotion_master_rewritten_through_curl_cffi(self):
        client = TestClient(app)
        with mock.patch("app.routers.watch.CurlAsyncSession", self.FakeCurlSession):
            resp = client.get(
                "/api/watch/proxy/stream",
                params={"url": "https://www.dailymotion.com/cdn/manifest/video/x/master.m3u8", "referer": "https://www.dailymotion.com/video/x"},
            )
        client.close()
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        # Every DM child manifest rewritten to a same-origin proxy URL...
        self.assertIn("/api/watch/proxy/stream?url=https%3A%2F%2Fvod-abc.dmcdn.net%2Fvideo%2Fx%2F720.m3u8", body)
        self.assertIn("/api/watch/proxy/stream?url=https%3A%2F%2Fvod-abc.dmcdn.net%2Fvideo%2Fx%2F1080.m3u8", body)
        # ...and the #cell cache hint is stripped, never sent upstream.
        self.assertNotIn("cell", body)
        self.assertNotIn("%23", body)

    def test_dailymotion_upstream_gets_origin_referer_and_proxy(self):
        client = TestClient(app)
        with mock.patch("app.routers.watch.CurlAsyncSession", self.FakeCurlSession):
            resp = client.get(
                "/api/watch/proxy/stream",
                params={"url": "https://geo.dailymotion.com/player/x/master.m3u8", "referer": "https://animexin.dev/anime/supreme-god-emperor/"},
            )
        client.close()
        self.assertEqual(resp.status_code, 200)
        session = self.FakeCurlSession.instances[-1]
        headers = session.kwargs["headers"]
        self.assertEqual(headers["Origin"], "https://www.dailymotion.com")
        # DM's CDN 403s non-Dailymotion Referers (verified 2026-08-13), so the
        # embedding site's referer is normalized to the DM origin.
        self.assertEqual(headers["Referer"], "https://www.dailymotion.com/")
        self.assertIn("User-Agent", headers)
        # curl_cffi chrome124 impersonation + 20s timeout used for DM.
        self.assertEqual(session.kwargs["impersonate"], "chrome124")
        self.assertEqual(session.kwargs["timeout"], 20.0)
        # DM upstream fetch itself is fragment-free.
        self.assertEqual(session.url, "https://geo.dailymotion.com/player/x/master.m3u8")

    def test_non_dailymotion_host_never_touches_curl_cffi(self):
        class FakeClient:
            async def get(self, url, headers=None):
                self.url = url
                self.received_headers = headers or {}
                return FakeResponse(text="seg", status_code=200, headers={"content-type": "video/mp2t"})

        fake_client = FakeClient()
        curl_cffi = mock.Mock()
        with mock.patch("app.services.channels.http.get_client", return_value=fake_client), mock.patch("app.routers.watch.CurlAsyncSession", curl_cffi):
            client = TestClient(app)
            resp = client.get("/api/watch/proxy/stream", params={"url": "https://megap.norami.top/abc/seg-1.ts"})
            client.close()
        self.assertEqual(resp.status_code, 200)
        curl_cffi.assert_not_called()


if __name__ == "__main__":
    unittest.main()
