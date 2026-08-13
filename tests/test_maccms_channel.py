"""Tests for the Maccms (AppleCMS) resource-site channels
(docs/RESOURCE_BACKUP_PLAN.md §2.8).

The JSON payloads below are real shapes captured live 2026-08-13 from
360zy.com / ikunzyapi.com / yhzy.cc via Clash 7892 (search/detail) and the
m3u8 CDNs (maowushi / bfikuncdn / wgslsw). Tests never touch the internet.
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.routers.watch import _host_allowed
from app.services.channels.base import ChannelError
from app.services.channels.maccms import (
    BaofengChannel,
    FeifanChannel,
    IKunChannel,
    JisuChannel,
    SuboChannel,
    YinghuaChannel,
    Ziyuan360Channel,
)
from app.services.channels.registry import registry

# Real 360zy search response for 葬送的芙莉莲 (trimmed).
SEARCH_360ZY = {
    "code": 1,
    "list": [
        {
            "vod_id": 89400,
            "vod_name": "葬送的芙莉莲第二季",
            "vod_pic": "https://www.imgzy360.com:7788/upload/vod/20260116-1/88fa6786a34b3f21c096cebcd8abebf0.webp",
            "vod_remarks": "更新至05集",
            "vod_year": "2026",
            "vod_content": "<p>内详</p>",
        },
        {
            "vod_id": 57133,
            "vod_name": "葬送的芙莉莲",
            "vod_pic": "https://www.imgzy360.com:7788/upload/vod/20240419-1/236a9c31663385fc2fe35b57e582f276.jpg",
            "vod_remarks": "已完结",
            "vod_year": "2023",
            "vod_content": "<p>中央大陆古老城邦，人们夹道欢呼，为击败了魔王的四人组高声喝彩。</p>",
        },
    ],
}

# Real jisuzy detail response with dual play sources (jsyun player page +
# jsm3u8 direct HLS), separated by $$$. The m3u8 source must win.
DETAIL_JISUZY = {
    "code": 1,
    "list": [
        {
            "vod_id": 92376,
            "vod_name": "葬送的芙莉莲第二季",
            "vod_play_from": "jsyun$$$jsm3u8",
            "vod_play_url": (
                "第1集$https://vv.jisuzyv.com/play/av223w5a#"
                "第2集$https://vv.jisuzyv.com/play/bYEEj3Mb"
                "$$$"
                "第1集$https://vv.jisuzyv.com/play/av223w5a/index.m3u8#"
                "第2集$https://vv.jisuzyv.com/play/bYEEj3Mb/index.m3u8"
            ),
        }
    ],
}

# Real 360zy detail response (episode play_url trimmed to 3 eps).
DETAIL_360ZY = {
    "code": 1,
    "list": [
        {
            "vod_id": 57133,
            "vod_name": "葬送的芙莉莲",
            "vod_pic": "https://www.imgzy360.com:7788/upload/vod/20240419-1/236a9c31663385fc2fe35b57e582f276.jpg",
            "vod_remarks": "已完结",
            "vod_content": "<p>中央大陆古老城邦，人们夹道欢呼。</p>",
            "vod_play_url": (
                "第01集$https://vod1.maowushi.com/20250202/CaIhei8G/index.m3u8#"
                "第02集$https://vod1.maowushi.com/20250205/vOSWt07D/index.m3u8#"
                "第03集$https://vod1.maowushi.com/20250207/ok600iSf/index.m3u8"
            ),
        }
    ],
}


class MaccmsChannelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.channel = Ziyuan360Channel()

    async def _search(self, *responses):
        with mock.patch(
            "app.services.channels.maccms.http.request",
            new=mock.AsyncMock(side_effect=responses),
        ) as req:
            result = await self.channel.search("葬送的芙莉莲")
        return result, req

    def test_search_parses_list(self) -> None:
        import asyncio

        resp = mock.Mock()
        resp.json.return_value = SEARCH_360ZY

        result, req = asyncio.run(self._search(resp))
        self.assertEqual(len(result), 2)
        first = result[0]
        self.assertEqual(first.channel, "360zy")
        self.assertEqual(first.title, "葬送的芙莉莲第二季")
        self.assertEqual(first.year, "2026")
        self.assertEqual(first.detail_ref, "89400")
        self.assertEqual(first.extra["remarks"], "更新至05集")
        self.assertTrue(first.cover_url.startswith("https://"))
        # all mirrors are raced: 3 tasks created for the 3 domains
        self.assertEqual(req.call_count, 3)

    def test_search_domain_fallback(self) -> None:
        import asyncio

        ok = mock.Mock()
        ok.json.return_value = SEARCH_360ZY

        # first domain fails, the rest succeed -> first success wins
        with mock.patch(
            "app.services.channels.maccms.http.request",
            new=mock.AsyncMock(side_effect=[ChannelError("360zy", "search", "boom"), ok, ok]),
        ) as req:
            result = asyncio.run(self.channel.search("葬送的芙莉莲"))
        self.assertEqual(len(result), 2)
        self.assertEqual(req.call_count, 3)

    def test_search_all_domains_fail(self) -> None:
        import asyncio

        with mock.patch(
            "app.services.channels.maccms.http.request",
            new=mock.AsyncMock(side_effect=ChannelError("360zy", "search", "boom")),
        ):
            with self.assertRaises(ChannelError) as ctx:
                asyncio.run(self.channel.search("葬送的芙莉莲"))
        self.assertEqual(ctx.exception.stage, "search")
        self.assertTrue(ctx.exception.retryable)

    def test_get_detail_parses_episodes(self) -> None:
        import asyncio

        resp = mock.Mock()
        resp.json.return_value = DETAIL_360ZY

        with mock.patch(
            "app.services.channels.maccms.http.request",
            new=mock.AsyncMock(return_value=resp),
        ):
            detail = asyncio.run(self.channel.get_detail("57133"))

        self.assertEqual(detail.channel, "360zy")
        self.assertEqual(detail.title, "葬送的芙莉莲")
        self.assertEqual(len(detail.groups), 1)
        group = detail.groups[0]
        self.assertEqual(group.title, "线路")
        self.assertEqual(len(group.episodes), 3)
        self.assertEqual(group.episodes[0].title, "第01集")
        self.assertTrue(group.episodes[0].episode_ref.startswith("https://vod1.maowushi.com/"))

    def test_get_detail_empty_play_url(self) -> None:
        import asyncio

        payload = {"code": 1, "list": [{"vod_id": 1, "vod_name": "x", "vod_play_url": ""}]}
        resp = mock.Mock()
        resp.json.return_value = payload

        with mock.patch(
            "app.services.channels.maccms.http.request",
            new=mock.AsyncMock(return_value=resp),
        ):
            detail = asyncio.run(self.channel.get_detail("1"))
        self.assertEqual(detail.groups, [])

    def test_get_detail_multi_source_prefers_direct_m3u8(self) -> None:
        import asyncio

        resp = mock.Mock()
        resp.json.return_value = DETAIL_JISUZY

        with mock.patch(
            "app.services.channels.maccms.http.request",
            new=mock.AsyncMock(return_value=resp),
        ):
            detail = asyncio.run(JisuChannel().get_detail("92376"))

        # Player-page source (jsyun) is dropped; only the m3u8 source remains.
        self.assertEqual(len(detail.groups), 1)
        group = detail.groups[0]
        self.assertEqual(group.title, "线路")
        self.assertEqual(len(group.episodes), 2)
        for episode in group.episodes:
            # Only direct m3u8 URLs survive; the player-page form
            # (https://vv.jisuzyv.com/play/<id> with no extension) is dropped.
            self.assertTrue(episode.episode_ref.endswith(".m3u8"))
            self.assertTrue(episode.episode_ref.endswith("/index.m3u8"))

    def test_search_passes_api_from_hint(self) -> None:
        import asyncio

        resp = mock.Mock()
        resp.json.return_value = SEARCH_360ZY

        with mock.patch(
            "app.services.channels.maccms.http.request",
            new=mock.AsyncMock(return_value=resp),
        ) as req:
            asyncio.run(JisuChannel().search("葬送的芙莉莲"))

        for call in req.call_args_list:
            url = call.args[3]  # request(channel, stage, method, url, ...)
            self.assertIn("from=jsm3u8", url)

    def test_get_streams_hls(self) -> None:
        import asyncio

        streams = asyncio.run(
            self.channel.get_streams("https://vod1.maowushi.com/20250202/CaIhei8G/index.m3u8")
        )
        self.assertEqual(len(streams), 1)
        stream = streams[0]
        self.assertEqual(stream.type, "hls")
        self.assertEqual(stream.format, "m3u8")
        self.assertIn("Referer", stream.headers)
        self.assertIn("maowushi.com", stream.url)

    def test_get_streams_rejects_non_http(self) -> None:
        import asyncio

        self.assertEqual(asyncio.run(self.channel.get_streams("/relative/path")), [])
        self.assertEqual(asyncio.run(self.channel.get_streams("")), [])


class MaccmsWhitelistTest(unittest.TestCase):
    def test_stream_cdn_hosts_allowed(self) -> None:
        for host in (
            "vod1.maowushi.com",
            "maowushi.com",
            "bfikuncdn.com",
            "cdn.bfikuncdn.com",
            "vod12.wgslsw.com",
            "ts1.yhzybf.com",
            "yhzybf.com",
            "vv.jisuzyv.com",
            "p.jisuts.com",
            "play.xluuss.com",
            "g.xlzyd.com",
            "c1.rrcdnbf5.com",
            "v.baofeng9.com",
            "vip.ffzy-plays.com",
        ):
            self.assertTrue(_host_allowed(f"https://{host}/x/index.m3u8"), host)

    def test_unrelated_hosts_denied(self) -> None:
        self.assertFalse(_host_allowed("https://evil.example.com/x.m3u8"))


class MaccmsRegistryTest(unittest.TestCase):
    def test_channels_registered(self) -> None:
        infos = {info.id: info for info in registry.list_channels()}
        for cid in ("360zy", "ikunzy", "yhzy", "jisuzy", "subozy", "bfzyapi", "ffzy"):
            self.assertIn(cid, infos)
            info = infos[cid]
            self.assertTrue(info.enabled)
            self.assertTrue(info.supports_search)
            self.assertTrue(info.supports_detail)
            self.assertTrue(info.supports_streams)
            self.assertEqual(info.priority, 59)
            self.assertFalse(info.external)

    def test_new_channel_language_zh(self) -> None:
        self.assertEqual(Ziyuan360Channel().language, "zh")
        self.assertEqual(IKunChannel().domains, ("ikunzyapi.com", "ikunzy.com", "ikunzy.net", "ikunzy.org", "ikunzy.vip"))
        self.assertEqual(YinghuaChannel().domains, ("yhzy.cc",))
        self.assertEqual(JisuChannel().domains, ("jszyapi.com", "jisuzy.com"))
        self.assertEqual(JisuChannel().api_from, "jsm3u8")
        self.assertEqual(SuboChannel().api_from, "subm3u8")
        self.assertEqual(SuboChannel().domains, ("subocaiji.com", "subozy.com", "suboziyuan.com", "suboziyuan.net"))
        self.assertEqual(BaofengChannel().domains, ("bfzyapi.com",))
        self.assertEqual(FeifanChannel().domains, ("ffzy.tv", "ffzy1.tv", "ffzy2.tv", "ffzy3.tv", "ffzy4.tv", "ffzy5.tv"))
        self.assertEqual(FeifanChannel().api_from, "ffm3u8")


if __name__ == "__main__":
    unittest.main()
