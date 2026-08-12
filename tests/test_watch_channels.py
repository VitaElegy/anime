"""Tests for the online watch channel layer.

All external calls are mocked — these tests never touch the real internet.
Coverage:
- provider parsers (AGE / Libvio / Zzzfun fixtures)
- registry aggregation + circuit breaker
- /api/watch HTTP contract + stream proxy allow/block/Range
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.main import app
from app.models import ChannelDetail, ChannelSearchResult, ChannelStream
from app.services import database as db
from app.services import response_cache
from app.services.channels.age import AgeChannel
from app.services.channels.base import ChannelError, ChannelProvider
from app.services.channels.libvio import LibvioChannel
from app.services.channels.registry import ChannelRegistry
from app.services.channels.zzzfun import ZzzfunChannel
from fastapi.testclient import TestClient


class FakeResponse:
    """Minimal stand-in for httpx.Response used by channel fixtures."""

    def __init__(self, text: str = "", json_data=None, status_code: int = 200, headers=None):
        self.text = text
        self._json = json_data
        self.status_code = status_code
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

    async def test_detail_and_streams_raise_on_unknown_channel(self):
        reg = ChannelRegistry()
        with self.assertRaises(LookupError):
            await reg.detail("nope", "ref")
        with self.assertRaises(LookupError):
            await reg.streams("nope", "ref")


class WatchApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_channels_endpoint_returns_registered_channels(self):
        resp = self.client.get("/api/watch/channels")
        self.assertEqual(resp.status_code, 200)
        ids = {c["id"] for c in resp.json()}
        self.assertTrue({"age", "libvio", "zzzfun", "bilibili"} <= ids)

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
    async def test_search_expands_keywords_and_dedupes_per_channel(self):
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


if __name__ == "__main__":
    unittest.main()
