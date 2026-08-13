"""Tests for the AnimeHeaven backup channel (docs/RESOURCE_BACKUP_PLAN.md §2.2).

External calls are mocked with real HTML shapes captured from animeheaven.me
(verified playable 2026-08-13); these tests never touch the real internet.
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.routers.watch import _host_allowed
from app.services.channels.animeheaven import AnimeHeavenChannel
from app.services.channels.base import ChannelError
from app.services.channels.registry import registry

# Real /fastsearch.php?xhr=1&s=frieren response (trimmed to the two hits).
HEAVEN_SEARCH = """
<a class='ac' href='/anime.php?hgj3i'><div class='fastitem bc1 ac'><div class='fastimg'><img class='coverimg' src='/image.php?neiap' alt='Frieren: Beyond Journey&#039;s End Season 2'></div><div class='fastname'>Frieren: Beyond Journey&#039;s End Season 2</div></div></a><a class='ac' href='/anime.php?ak2gr'><div class='fastitem bc1 ac'><div class='fastimg'><img class='coverimg' src='/image.php?z4mfi' alt='Frieren: Beyond Journey&#039;s End'></div><div class='fastname'>Frieren: Beyond Journey&#039;s End</div></div></a>
"""

# Real /anime.php?ak2gr response (trimmed): title, poster, desc, 3 episode anchors.
# The site lists episodes newest-first (3, 2, 1) — the channel must sort ascending.
HEAVEN_ANIME = """
<html><head><title>Frieren: Beyond Journey&#039;s End Anime | AnimeHeaven.Me</title></head>
<body>
<div class='info bc1'> <div class='infoimg'><img class='posterimg' src='https://animeheaven.me/image.php?wdjis' alt='Frieren: Beyond Journey&#039;s End Anime Poster' width='320' height='480'></div><div class='info'>
<div class='infodes c'>Elf mage Frieren and her courageous fellow adventurers have defeated the Demon King and brought peace to the land.</div>
</div></div>
<div class='episodes'>
<a class='c' onmouseover='gateh("aaa111222333444555666777888999000")' onclick='gatea("aaa111222333444555666777888999000")'  id="aaa111222333444555666777888999000" href= 'gate.php'      ><div class='trackep0 watch bc2'><div class='trackep watchb bc'><div class='watch1 bc c'>Episode</div><div  class=' watch2 bc '>3</div><div class='watch1 bc c'>208 d ago</div></div></div></a>
<a class='c' onmouseover='gateh("bbb222333444555666777888999000111")' onclick='gatea("bbb222333444555666777888999000111")'  id="bbb222333444555666777888999000111" href= 'gate.php'      ><div class='trackep0 watch bc2'><div class='trackep watchb bc'><div class='watch1 bc c'>Episode</div><div  class=' watch2 bc '>2</div><div class='watch1 bc c'>208 d ago</div></div></div></a>
<a class='c' onmouseover='gateh("ccc333444555666777888999000111222")' onclick='gatea("ccc333444555666777888999000111222")'  id="ccc333444555666777888999000111222" href= 'gate.php'      ><div class='trackep0 watch bc2'><div class='trackep watchb bc'><div class='watch1 bc c'>Episode</div><div  class=' watch2 bc '>1</div><div class='watch1 bc c'>208 d ago</div></div></div></a>
</div>
</body></html>
"""

# Real /gate.php response (trimmed): video element with mp4 sources.
HEAVEN_GATE = """
<html><body>
<video id='vid' class='videodiv' controls autoplay playsinline crossOrigin='anonymous'>
<source src='https://ct.animeheaven.me/video.mp4?47edc338ae59c34cc3ea427c7f6871df&57af05947cd59bcd601d7768ad042ae2' type='video/mp4' onerror="xhr()">
<source src='https://ct.animeheaven.me/video.mp4?47edc338ae59c34cc3ea427c7f6871df&57af05947cd59bcd601d7768ad042ae2&error' type='video/mp4' onerror="xhr()">
</video>
</body></html>
"""


class _FakeResponse:
    """Minimal httpx.Response stand-in (text only)."""

    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class AnimeHeavenChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_parses_real_fixture(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(HEAVEN_SEARCH)
        ) as req:
            hits = await AnimeHeavenChannel().search("Frieren")
        self.assertEqual(len(hits), 2)
        first = hits[0]
        self.assertEqual(first.channel, "animeheaven")
        self.assertEqual(first.title, "Frieren: Beyond Journey's End Season 2")
        self.assertEqual(first.detail_ref, "hgj3i")
        self.assertEqual(first.cover_url, "https://animeheaven.me/image.php?neiap")
        second = hits[1]
        self.assertEqual(second.title, "Frieren: Beyond Journey's End")
        self.assertEqual(second.detail_ref, "ak2gr")
        self.assertEqual(second.cover_url, "https://animeheaven.me/image.php?z4mfi")
        req.assert_called_once()
        self.assertEqual(req.call_args.args[3], "https://animeheaven.me/fastsearch.php")
        self.assertEqual(req.call_args.kwargs["params"], {"xhr": 1, "s": "Frieren"})

    async def test_search_empty_html_returns_empty(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse("<html></html>")
        ):
            hits = await AnimeHeavenChannel().search("Nope Nope Nope")
        self.assertEqual(hits, [])

    async def test_detail_parses_episodes_sorted_ascending(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(HEAVEN_ANIME)
        ) as req:
            detail = await AnimeHeavenChannel().get_detail("ak2gr")
        self.assertEqual(detail.channel, "animeheaven")
        self.assertEqual(detail.title, "Frieren: Beyond Journey's End")
        self.assertEqual(detail.cover_url, "https://animeheaven.me/image.php?wdjis")
        self.assertTrue(detail.description.startswith("Elf mage Frieren"))
        self.assertEqual(len(detail.groups), 1)
        group = detail.groups[0]
        self.assertEqual(group.title, "AnimeHeaven")
        nums = [ep.title for ep in group.episodes]
        self.assertEqual(nums, ["第1集", "第2集", "第3集"])  # ascending despite page order
        self.assertEqual(
            [ep.episode_ref for ep in group.episodes],
            ["ccc333444555666777888999000111222", "bbb222333444555666777888999000111", "aaa111222333444555666777888999000"],
        )
        req.assert_called_once()
        self.assertEqual(req.call_args.args[3], "https://animeheaven.me/anime.php?ak2gr")

    async def test_detail_missing_title_raises_channel_error(self):
        with mock.patch(
            "app.services.channels.http.request",
            return_value=_FakeResponse("<html><body><p>oops</p></body></html>"),
        ):
            with self.assertRaises(ChannelError) as ctx:
                await AnimeHeavenChannel().get_detail("bogus")
        self.assertFalse(ctx.exception.retryable)

    async def test_streams_parses_mp4_url(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse(HEAVEN_GATE)
        ) as req:
            streams = await AnimeHeavenChannel().get_streams("47edc338ae59c34cc3ea427c7f6871df")
        self.assertEqual(len(streams), 1)
        stream = streams[0]
        self.assertEqual(stream.type, "mp4")
        self.assertEqual(stream.format, "mp4")
        self.assertIn("/video.mp4?", stream.url)
        self.assertIn("47edc338ae59c34cc3ea427c7f6871df", stream.url)
        self.assertEqual(stream.headers.get("Referer"), "https://animeheaven.me/")
        req.assert_called_once()
        self.assertEqual(req.call_args.args[3], "https://animeheaven.me/gate.php")
        self.assertEqual(req.call_args.kwargs["headers"]["Cookie"], "key=47edc338ae59c34cc3ea427c7f6871df")

    async def test_streams_no_source_raises_channel_error(self):
        with mock.patch(
            "app.services.channels.http.request", return_value=_FakeResponse("<html></html>")
        ):
            with self.assertRaises(ChannelError):
                await AnimeHeavenChannel().get_streams("deadbeef")

    def test_registry_registered(self):
        provider = registry.get("animeheaven")
        self.assertIsNotNone(provider)
        self.assertTrue(provider.enabled)
        self.assertEqual(provider.priority, 55)
        self.assertTrue(provider.supports_streams)
        self.assertFalse(provider.external)
        ids = [info.id for info in registry.list_channels()]
        self.assertIn("animeheaven", ids)

    def test_stream_proxy_allowlist_covers_cdn(self):
        self.assertTrue(_host_allowed("https://animeheaven.me/gate.php"))
        self.assertTrue(_host_allowed("https://ct.animeheaven.me/video.mp4?abc"))
        self.assertTrue(_host_allowed("https://ck.animeheaven.me/video.mp4?abc"))
        self.assertFalse(_host_allowed("https://example.com/video.mp4"))


if __name__ == "__main__":
    unittest.main()
