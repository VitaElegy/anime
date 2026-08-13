"""Libvio channel — HTML scraping + signed HLS URLs.

Ported from zaxtyson/Anime-API `api/anime/libvio.py`
(MIT License, Copyright (c) 2020 zaxtyson). See docs/CHANNEL_ARCHITECTURE.md §8.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from app.models import (
    ChannelDetail,
    ChannelEpisode,
    ChannelEpisodeGroup,
    ChannelSearchResult,
    ChannelStream,
)
from app.services.channels import http
from app.services.channels.base import ChannelProvider

logger = logging.getLogger(__name__)

BASE = "https://www.libvio.com"
SIGN_KEY = "y4nZpZYXK7SOr3wWlvyD0RTl8ti61IbeVFTjpLQv21hPKKTy"


class LibvioChannel(ChannelProvider):
    """Libvio 在线影视站."""

    id = "libvio"
    name = "Libvio"
    language = "zh"
    description = "在线影视站（HTML + 签名 HLS）"

    # 实测不可用（2026-08-13 403/超时），禁用避免拖慢聚合搜索；恢复后移除本行即可。
    enabled = False

    @staticmethod
    def _sign_url(url: str) -> str:
        """Compute the short-lived sign query (see Anime-API libvio.py)."""
        path = urlparse(url).path
        t = format(int(time.time()) + 300, "x")
        sign = hashlib.md5((SIGN_KEY + path + t).encode("utf-8")).hexdigest()
        return f"{url}?sign={sign}&t={t}"

    @staticmethod
    def _absolute(base: str, url: str) -> str:
        if not url:
            return ""
        if url.startswith("http://") or url.startswith("https://"):
            return url
        if url.startswith("/"):
            return f"{base}{url}"
        return f"{base}/{url}"

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        resp = await http.request(
            self.id,
            "search",
            "GET",
            f"{BASE}/search/-------------.html",
            params={"wd": keyword, "submit": ""},
        )
        soup = BeautifulSoup(resp.text or "", "html.parser")
        out: list[ChannelSearchResult] = []
        for box in soup.select("div.stui-vodlist__box"):
            link = box.select_one("a")
            if not link:
                continue
            href = link.get("href") or ""
            if not href:
                continue
            out.append(
                ChannelSearchResult(
                    channel=self.id,
                    title=(link.get("title") or "").strip(),
                    cover_url=(link.get("data-original") or "").strip(),
                    description=(box.get_text(" ", strip=True) or "")[:200],
                    detail_ref=href,
                )
            )
        return out

    async def get_detail(self, detail_ref: str) -> ChannelDetail:
        url = self._absolute(BASE, detail_ref)
        resp = await http.request(self.id, "detail", "GET", url)
        soup = BeautifulSoup(resp.text or "", "html.parser")

        title_el = soup.select_one("div.stui-content__detail h1.title")
        cover_el = soup.select_one("a.pic img")
        desc_el = soup.select_one("div.stui-content__detail span.detail-content")

        playlist_names = [
            h.get_text(" ", strip=True)
            for h in soup.select("div.stui-pannel__head.clearfix h3")
        ]
        playlist_nodes = soup.select("ul.stui-content__playlist.clearfix")

        groups: list[ChannelEpisodeGroup] = []
        for idx, ul in enumerate(playlist_nodes):
            name = playlist_names[idx] if idx < len(playlist_names) else f"线路{idx + 1}"
            episodes: list[ChannelEpisode] = []
            for li in ul.select("li"):
                a = li.select_one("a")
                if not a:
                    continue
                href = a.get("href") or ""
                if not href:
                    continue
                episodes.append(
                    ChannelEpisode(
                        title=a.get_text(" ", strip=True),
                        episode_ref=href,
                    )
                )
            if episodes:
                groups.append(ChannelEpisodeGroup(title=name, episodes=episodes))

        return ChannelDetail(
            channel=self.id,
            title=title_el.get_text(" ", strip=True) if title_el else "",
            cover_url=(cover_el.get("data-original") or "") if cover_el else "",
            description=desc_el.get_text(" ", strip=True) if desc_el else "",
            groups=groups,
        )

    async def get_streams(self, episode_ref: str) -> list[ChannelStream]:
        url = self._absolute(BASE, episode_ref)
        resp = await http.request(self.id, "streams", "GET", url)
        match = re.search(r"player_aaaa=(\{.*?\})(?:<|;)", resp.text or "", re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(1))
        except Exception:
            return []
        video_url = unquote(data.get("url") or "")
        if not video_url:
            return []
        signed = self._sign_url(video_url)
        return [
            ChannelStream(
                type="hls",
                url=signed,
                quality="auto",
                format="m3u8",
                headers={"User-Agent": http.DEFAULT_UA, "Referer": f"{BASE}/"},
                expires_in=300,
                note="Libvio",
            )
        ]
