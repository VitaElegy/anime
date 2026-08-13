"""Gogoanime channel — HTML scraping + megaplay HLS extraction.

Chain (verified 2026-08-13):
  /search.html?keyword= -> /category/{slug} (episode list)
  -> /{slug}-episode-{n} -> data-video "gogoanime.me.uk/newplayer.php?..."
  -> iframe "megaplay.buzz/stream/..." -> data-id -> getSourcesNew?id= -> master.m3u8

getSourcesNew returns a clean master (no tiktokcdn ad segments, verified on
multiple variants); getSources is kept as a fallback line (the stream proxy
strips tiktokcdn ad segments from those playlists).
"""

from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup

from app.models import (
    ChannelDetail,
    ChannelEpisode,
    ChannelEpisodeGroup,
    ChannelSearchResult,
    ChannelStream,
)
from app.services.channels import http
from app.services.channels.base import ChannelError, ChannelProvider

logger = logging.getLogger(__name__)

BASE = "https://www.gogoanime.is"
PLAYER_ORIGIN = "https://megaplay.buzz"
NEWPLAYER_HOST = "gogoanime.me.uk"


class GogoanimeChannel(ChannelProvider):
    """Gogoanime (English subs, megaplay HLS)."""

    id = "gogoanime"
    name = "Gogoanime"
    language = "en"
    description = "英文资源站（megaplay HLS，需代理访问）"

    @staticmethod
    def _episode_ref(slug: str, ep: int) -> str:
        return json.dumps({"slug": slug, "ep": ep}, separators=(",", ":"))

    @staticmethod
    def _parse_episode_ref(ref: str) -> tuple[str, int]:
        try:
            data = json.loads(ref)
            return str(data["slug"]), int(data["ep"])
        except Exception:
            slug, _, ep = ref.rpartition("-episode-")
            return slug or ref, int(ep or 0)

    @staticmethod
    def _absolute(url: str) -> str:
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return f"{BASE}{url}"

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        resp = await http.request(
            self.id,
            "search",
            "GET",
            f"{BASE}/search.html",
            params={"keyword": keyword},
        )
        soup = BeautifulSoup(resp.text or "", "html.parser")
        out: list[ChannelSearchResult] = []
        seen: set[str] = set()
        for item in soup.select("ul.items li"):
            link = item.select_one("a[href^='/category/']")
            if not link:
                continue
            slug = (link.get("href") or "").rstrip("/")
            if slug in seen:
                continue
            seen.add(slug)
            img = link.select_one("img")
            out.append(
                ChannelSearchResult(
                    channel=self.id,
                    title=(link.get("title") or link.get_text(" ", strip=True) or "").strip(),
                    cover_url=self._absolute(img.get("src") or "") if img else "",
                    description="",
                    detail_ref=slug,
                    extra={"slug": slug},
                )
            )
        return out

    async def get_detail(self, detail_ref: str) -> ChannelDetail:
        url = self._absolute(detail_ref if detail_ref.startswith("/") else f"/category/{detail_ref}")
        resp = await http.request(self.id, "detail", "GET", url)
        soup = BeautifulSoup(resp.text or "", "html.parser")

        title_el = soup.select_one("div.anime_info_body_bg h1")
        cover_el = soup.select_one("div.anime_info_body_bg img")

        slug = detail_ref.rstrip("/").rsplit("/", 1)[-1]
        episodes: list[ChannelEpisode] = []
        seen_eps: set[int] = set()
        for a in soup.select("ul#episode_related a[href]"):
            href = a.get("href") or ""
            m = re.match(rf"^/{re.escape(slug)}-episode-(\d+)$", href)
            if not m:
                continue
            ep = int(m.group(1))
            if ep in seen_eps:
                continue
            seen_eps.add(ep)
            episodes.append(ChannelEpisode(title=f"第{ep}集", episode_ref=self._episode_ref(slug, ep)))
        episodes.sort(key=lambda e: int(json.loads(e.episode_ref)["ep"]))

        group = ChannelEpisodeGroup(title="Gogoanime", episodes=episodes)
        return ChannelDetail(
            channel=self.id,
            title=title_el.get_text(" ", strip=True) if title_el else "",
            cover_url=self._absolute(cover_el.get("src") or "") if cover_el else "",
            description="",
            groups=[group] if episodes else [],
        )

    async def get_streams(self, episode_ref: str) -> list[ChannelStream]:
        slug, ep = self._parse_episode_ref(episode_ref)
        watch_url = f"{BASE}/{slug}-episode-{ep}"

        # 1. Watch page -> pick the gogoanime player server.
        resp = await http.request(self.id, "streams", "GET", watch_url)
        soup = BeautifulSoup(resp.text or "", "html.parser")
        player_url = ""
        for el in soup.select("[data-video]"):
            url = (el.get("data-video") or "").strip()
            if NEWPLAYER_HOST in url:
                player_url = url
                break
        if not player_url:
            raise ChannelError(self.id, "streams", "no gogoanime player on watch page", retryable=False)

        # 2. newplayer.php -> megaplay iframe.
        resp = await http.request(
            self.id,
            "streams",
            "GET",
            player_url,
            headers={"Referer": watch_url},
        )
        iframe_match = re.search(r'<iframe[^>]+src="([^"]*megaplay\.buzz[^"]*)"', resp.text or "")
        if not iframe_match:
            raise ChannelError(self.id, "streams", "no megaplay iframe", retryable=False)
        mega_url = iframe_match.group(1).replace("&amp;", "&")

        # 3. megaplay page -> data-id.
        resp = await http.request(
            self.id,
            "streams",
            "GET",
            mega_url,
            headers={"Referer": player_url},
        )
        did_match = re.search(r'data-id=["\'](\d+)["\']', resp.text or "")
        if not did_match:
            raise ChannelError(self.id, "streams", "no data-id on megaplay page", retryable=False)
        did = did_match.group(1)

        # 4. Resolve master playlists. Primary: getSourcesNew (clean).
        streams: list[ChannelStream] = []
        primary = await self._fetch_sources(did, mega_url, new=True)
        if primary:
            streams.append(self._make_stream(primary, f"Gogoanime（线路{self._server_label(primary, 'A')}）"))
        fallback = await self._fetch_sources(did, mega_url, new=False)
        if fallback and fallback.get("file") != primary.get("file"):
            streams.append(self._make_stream(fallback, "Gogoanime 备用（混淆分片由代理剥离）"))
        if not streams:
            raise ChannelError(self.id, "streams", "no playable source", retryable=False)
        return streams

    async def _fetch_sources(self, did: str, mega_url: str, *, new: bool) -> dict:
        endpoint = "getSourcesNew" if new else "getSources"
        try:
            resp = await http.request(
                self.id,
                "streams",
                "GET",
                f"{PLAYER_ORIGIN}/stream/{endpoint}",
                params={"id": did},
                headers={
                    "Referer": mega_url,
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            payload = resp.json()
        except Exception:
            return {}
        sources = payload.get("sources") or {}
        file_url = sources.get("file") or ""
        if not file_url:
            return {}
        return {"file": str(file_url), "server": str(payload.get("server") or "")}

    @staticmethod
    def _server_label(source: dict, default: str) -> str:
        return source.get("server") or default

    @staticmethod
    def _make_stream(source: dict, note: str) -> ChannelStream:
        return ChannelStream(
            type="hls",
            url=source["file"],
            quality="auto",
            format="m3u8",
            headers={"User-Agent": http.DEFAULT_UA, "Referer": f"{PLAYER_ORIGIN}/"},
            note=note,
        )
