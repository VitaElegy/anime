"""Tests for the AnimeXin backup channel (docs/RESOURCE_BACKUP_PLAN.md §2.6).

External calls are mocked with real HTML shapes captured from animexin.dev and
dailymotion.com (verified playable 2026-08-13 via Clash 7892); these tests never
touch the internet. The curl_cffi Dailymotion call is the documented exception
declared in §2.6, so tests stub ``AnimeXinChannel._dm_master`` (and exercise the
token/metadata parsing directly against the fake AsyncSession).
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.routers.watch import _host_allowed
from app.services.channels.animexin import BASE, AnimeXinChannel
from app.services.channels.base import ChannelError
from app.services.channels.registry import registry

# Real /page/1/?s=supreme response shape (trimmed to two hits): listupd ->
# article.bs -> a.tip[href][title] + img.ts-post-image[src][title].
XIN_SEARCH = """
<div class="listupd">
<article class="bs">
  <div class="bsx">
    <a href="https://animexin.dev/supreme-god-emperor/" class="tip" title="Supreme God Emperor">
      <div class="limit"><span class="sb">Sub</span></div>
      <img class="ts-post-image" src="https://animexin.dev/wp-content/uploads/2024/01/sge.jpg" title="Supreme God Emperor">
    </a>
  </div>
</article>
<article class="bs">
  <div class="bsx">
    <a href="/battle-through-the-heavens/" class="tip" title="Battle Through the Heavens">
      <img class="ts-post-image" src="/wp-content/uploads/2023/btth.jpg">
    </a>
  </div>
</article>
</div>
"""

# Real /anime/<slug>/ response shape (trimmed): title, Chinese alter, thumb
# cover, entry-content synopsis, eplister with 3 episode anchors listed
# newest-first (626, 625, 624) — the channel must sort ascending.
XIN_DETAIL = """
<html><head><title>Supreme God Emperor - AnimeXin</title></head>
<body>
<div class="thumb"><img src="https://animexin.dev/wp-content/uploads/2024/01/sge.jpg" alt="Supreme God Emperor"></div>
<span class="alter">无上神帝</span>
<div class="mindesc">The Supreme God Emperor rises again.</div>
<div class="entry-content"><p>The protagonist regains his power and seeks revenge across the nine heavens.</p></div>
<div class="eplister"><ul>
<li data-index="0"><a href="https://animexin.dev/supreme-god-emperor-episode-626-indonesia-english-sub/"><div class="epl-num">626</div><div class="epl-title">Episode 626</div></a></li>
<li data-index="1"><a href="https://animexin.dev/supreme-god-emperor-episode-625-indonesia-english-sub/"><div class="epl-num">625</div><div class="epl-title">Episode 625</div></a></li>
<li data-index="2"><a href="https://animexin.dev/supreme-god-emperor-episode-624-indonesia-english-sub/"><div class="epl-num">624</div><div class="epl-title">Episode 624</div></a></li>
</ul></div>
</body></html>
"""

# Real episode page shape: the player iframe is the first iframe.
XIN_EPISODE_DM = """
<html><body>
<iframe width="100%" height="450" src="https://www.dailymotion.com/embed/video/x8abcde" allowfullscreen></iframe>
</body></html>
"""

XIN_EPISODE_OTHER = """
<html><body>
<iframe width="100%" height="450" src="https://gdriveplayer.to/embed2.php?id=xyz" allowfullscreen></iframe>
</body></html>
"""

# Real Dailymotion embed page dmInternalData fragment (ts/v1st tokens).
DM_EMBED_HTML = """
<script>window.__dmInternalData = {"ts":1723456789,"v1st":"abc123DEF==","page":"video"};</script>
"""

# Real /player/metadata/video/<id> response (qualities.auto[0].url = HLS master).
DM_METADATA = {
    "qualities": {
        "auto": [
            {
                "url": "https://cdndirector.dailymotion.com/video/x8abcde/master.m3u8?token=xyz",
                "type": "application/vnd.apple.mpegurl",
                "quality": "auto",
            }
        ]
    }
}


class _FakeResponse:
    """Minimal httpx.Response stand-in (text only)."""

    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeCurlResponse:
    """Minimal curl_cffi response stand-in (text/json)."""

    def __init__(self, text: str = "", payload: dict | None = None):
        self.text = text
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeAsyncSession:
    """In-memory AsyncSession stand-in: embed page then metadata JSON."""

    instances: list[_FakeAsyncSession] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls: list[tuple[str, dict]] = []
        _FakeAsyncSession.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        if "/embed/video/" in url:
            return _FakeCurlResponse(text=DM_EMBED_HTML)
        return _FakeCurlResponse(payload=DM_METADATA)


class AnimeXinChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_parses_real_fixture(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(XIN_SEARCH)
        ) as req:
            hits = await AnimeXinChannel().search("Supreme")
        self.assertEqual(len(hits), 2)
        first = hits[0]
        self.assertEqual(first.channel, "animexin")
        self.assertEqual(first.title, "Supreme God Emperor")
        self.assertEqual(first.detail_ref, "https://animexin.dev/supreme-god-emperor/")
        self.assertEqual(
            first.cover_url, "https://animexin.dev/wp-content/uploads/2024/01/sge.jpg"
        )
        second = hits[1]
        self.assertEqual(second.title, "Battle Through the Heavens")
        # Relative href/src are made absolute.
        self.assertEqual(second.detail_ref, f"{BASE}/battle-through-the-heavens/")
        self.assertEqual(second.cover_url, f"{BASE}/wp-content/uploads/2023/btth.jpg")
        req.assert_called_once()
        self.assertEqual(req.call_args.args[3], f"{BASE}/page/1/")
        self.assertEqual(req.call_args.kwargs["params"], {"s": "Supreme"})

    async def test_search_empty_html_returns_empty(self):
        with mock.patch(
            "app.services.channels.http.request",
            return_value=_FakeResponse("<center><h3>Not Found</h3></center>"),
        ):
            hits = await AnimeXinChannel().search("Naruto")
        self.assertEqual(hits, [])

    async def test_detail_parses_chinese_title_cover_synopsis_episodes_sorted(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(XIN_DETAIL)
        ) as req:
            detail = await AnimeXinChannel().get_detail("https://animexin.dev/supreme-god-emperor/")
        self.assertEqual(detail.channel, "animexin")
        self.assertEqual(detail.title, "无上神帝")  # span.alter preferred
        self.assertEqual(
            detail.cover_url, "https://animexin.dev/wp-content/uploads/2024/01/sge.jpg"
        )
        self.assertIn("英文名：Supreme God Emperor", detail.description)
        self.assertIn("protagonist regains his power", detail.description)
        self.assertEqual(len(detail.groups), 1)
        group = detail.groups[0]
        self.assertEqual(group.title, "AnimeXin")
        self.assertEqual([ep.title for ep in group.episodes], ["第624集", "第625集", "第626集"])
        self.assertEqual(
            [ep.episode_ref for ep in group.episodes],
            [
                "https://animexin.dev/supreme-god-emperor-episode-624-indonesia-english-sub/",
                "https://animexin.dev/supreme-god-emperor-episode-625-indonesia-english-sub/",
                "https://animexin.dev/supreme-god-emperor-episode-626-indonesia-english-sub/",
            ],
        )
        self.assertEqual(group.episodes[0].extra["number"], 624)
        req.assert_called_once()
        self.assertEqual(req.call_args.kwargs["timeout"], 20.0)  # documented exception

    async def test_detail_accepts_relative_ref(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(XIN_DETAIL)
        ) as req:
            await AnimeXinChannel().get_detail("supreme-god-emperor/")
        self.assertEqual(req.call_args.args[3], f"{BASE}/supreme-god-emperor/")

    async def test_detail_missing_title_raises_channel_error(self):
        with mock.patch(
            "app.services.channels.http.request",
            return_value=_FakeResponse("<html><body><p>oops</p></body></html>"),
        ):
            with self.assertRaises(ChannelError) as ctx:
                await AnimeXinChannel().get_detail("supreme-god-emperor/")
        self.assertFalse(ctx.exception.retryable)

    async def test_streams_dm_embed_resolves_hls_master(self):
        seen: dict[str, str] = {}

        async def fake_master(self, video_id):
            seen["video_id"] = video_id
            return "https://cdndirector.dailymotion.com/video/x8abcde/master.m3u8?token=xyz"

        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(XIN_EPISODE_DM)
        ) as req, mock.patch.object(AnimeXinChannel, "_dm_master", fake_master):
                streams = await AnimeXinChannel().get_streams(
                    "https://animexin.dev/supreme-god-emperor-episode-626-indonesia-english-sub/"
                )
        self.assertEqual(seen["video_id"], "x8abcde")
        self.assertEqual(len(streams), 1)
        stream = streams[0]
        self.assertEqual(stream.type, "hls")
        self.assertIn("cdndirector.dailymotion.com", stream.url)
        self.assertEqual(stream.headers.get("Referer"), "https://www.dailymotion.com/")
        self.assertEqual(stream.headers.get("Origin"), "https://www.dailymotion.com")
        self.assertIn("User-Agent", stream.headers)
        self.assertEqual(stream.note, "AnimeXin · Dailymotion")
        req.assert_called_once()
        self.assertEqual(req.call_args.kwargs["timeout"], 20.0)  # documented exception

    async def test_streams_non_dm_embed_raises_not_retryable(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(XIN_EPISODE_OTHER)
        ):
            with self.assertRaises(ChannelError) as ctx:
                await AnimeXinChannel().get_streams(
                    "https://animexin.dev/some-episode-1-english-sub/"
                )
        self.assertFalse(ctx.exception.retryable)
        self.assertIn("gdriveplayer.to", str(ctx.exception))

    async def test_streams_no_iframe_raises_channel_error(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse("<html></html>")
        ):
            with self.assertRaises(ChannelError):
                await AnimeXinChannel().get_streams(
                    "https://animexin.dev/some-episode-1-english-sub/"
                )

    async def test_streams_malformed_ref_raises_channel_error(self):
        with self.assertRaises(ChannelError) as ctx:
            await AnimeXinChannel().get_streams("not-a-url")
        self.assertFalse(ctx.exception.retryable)

    async def test_dm_master_uses_chrome124_fingerprint_and_tokens(self):
        with mock.patch("app.services.channels.animexin.AsyncSession", _FakeAsyncSession):
            master = await AnimeXinChannel()._dm_master("x8abcde")
        fake = _FakeAsyncSession.instances[-1]
        self.assertEqual(
            master, "https://cdndirector.dailymotion.com/video/x8abcde/master.m3u8?token=xyz"
        )
        self.assertEqual(fake.kwargs["impersonate"], "chrome124")
        embed_url, meta_url = [c[0] for c in fake.calls]
        self.assertEqual(embed_url, "https://www.dailymotion.com/embed/video/x8abcde")
        self.assertIn("/player/metadata/video/x8abcde?", meta_url)
        # v1st (contains '=') must be URL-encoded in the metadata query.
        self.assertIn("dmV1st=abc123DEF%3D%3D", meta_url)
        self.assertIn("dmTs=1723456789", meta_url)
        meta_headers = fake.calls[1][1]["headers"]
        self.assertEqual(meta_headers.get("Referer"), "https://www.dailymotion.com/")
        self.assertEqual(meta_headers.get("Origin"), "https://www.dailymotion.com")

    def test_dm_tokens_parser(self):
        self.assertEqual(AnimeXinChannel._dm_tokens(DM_EMBED_HTML), ("1723456789", "abc123DEF=="))
        self.assertIsNone(AnimeXinChannel._dm_tokens("<html></html>"))

    def test_registry_registered(self):
        provider = registry.get("animexin")
        self.assertIsNotNone(provider)
        self.assertTrue(provider.enabled)
        self.assertEqual(provider.priority, 56)
        self.assertTrue(provider.supports_search)
        self.assertTrue(provider.supports_detail)
        self.assertTrue(provider.supports_streams)
        self.assertFalse(provider.external)
        self.assertEqual(provider.language, "en")
        ids = [info.id for info in registry.list_channels()]
        self.assertIn("animexin", ids)

    def test_stream_proxy_allowlist_covers_dailymotion(self):
        self.assertTrue(
            _host_allowed("https://cdndirector.dailymotion.com/video/x8abcde/master.m3u8?token=xyz")
        )
        self.assertTrue(_host_allowed("https://vod3.cf.dmcdn.net/video/x8abcde/seg-1.ts"))
        self.assertTrue(_host_allowed("https://www.dailymotion.com/embed/video/x8abcde"))
        self.assertFalse(_host_allowed("https://example.com/video.mp4"))


if __name__ == "__main__":
    unittest.main()
