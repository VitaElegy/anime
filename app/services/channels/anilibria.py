"""Anilibria channel — public JSON API (anilibria.top).

Anilibria is a clean open API for anime releases:
- search: GET /api/v1/app/search/releases?query=...
- detail: GET /api/v1/anime/releases/{id} (episodes carry hls_480/720/1080)
- streams: GET /api/v1/anime/releases/episodes/{episodeId}

Playback is plain HLS on cache.libria.fun and works without a proxy (verified
2026-08-13). Chinese keywords are expanded to English/romaji by the registry
(docs/CHANNEL_ARCHITECTURE.md §1.2) before hitting this English-title index.
"""

from __future__ import annotations

import json
import logging

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

API_BASE = "https://anilibria.top/api/v1"
WEB_ORIGIN = "https://anilibria.top"


class AnilibriaChannel(ChannelProvider):
    """Anilibria (English/romaji title index, clean HLS streams)."""

    id = "anilibria"
    name = "Anilibria"
    language = "en"
    description = "英文索引 + 直连 HLS（无防盗链）"
    #: Main playable source — top of the channel tab (docs/CHANNEL_ARCHITECTURE.md §1.1).
    priority = 10

    #: Episode references are compact JSON so get_streams can pick the fastest
    #: path (single-episode endpoint) and fall back to the release detail.
    @staticmethod
    def _episode_ref(release_id: int, episode_id: str) -> str:
        return json.dumps({"release_id": release_id, "episode_id": episode_id}, separators=(",", ":"))

    @staticmethod
    def _parse_episode_ref(ref: str) -> tuple[int | None, str]:
        try:
            data = json.loads(ref)
            return int(data["release_id"]), str(data["episode_id"])
        except Exception:
            return None, ref.strip()

    @staticmethod
    def _abs(path: str) -> str:
        if not path:
            return ""
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{WEB_ORIGIN}{path}"

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        resp = await http.request(
            self.id,
            "search",
            "GET",
            f"{API_BASE}/app/search/releases",
            params={"query": keyword, "limit": 10},
            headers={"User-Agent": http.DEFAULT_UA, "Referer": f"{WEB_ORIGIN}/"},
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ChannelError(self.id, "search", f"invalid json: {exc}") from exc
        if not isinstance(payload, list):
            raise ChannelError(self.id, "search", "unexpected payload shape", retryable=False)

        out: list[ChannelSearchResult] = []
        for item in payload:
            rid = item.get("id")
            if rid is None:
                continue
            name = item.get("name") or {}
            title = str(name.get("english") or name.get("main") or item.get("alias") or "")
            if not title:
                continue
            poster = item.get("poster") or ""
            if isinstance(poster, dict):
                cover_path = str(poster.get("optimized", {}).get("preview") or poster.get("src") or "")
            else:
                cover_path = str(poster)
            out.append(
                ChannelSearchResult(
                    channel=self.id,
                    title=title,
                    title_original=str(name.get("main") or ""),
                    cover_url=self._abs(cover_path),
                    description=str(item.get("description") or "")[:300],
                    year=str(item.get("year") or ""),
                    detail_ref=str(rid),
                    extra={
                        "alias": str(item.get("alias") or ""),
                        "ongoing": bool(item.get("is_ongoing")),
                    },
                )
            )
        return out

    async def get_detail(self, detail_ref: str) -> ChannelDetail:
        resp = await http.request(
            self.id,
            "detail",
            "GET",
            f"{API_BASE}/anime/releases/{detail_ref}",
            headers={"User-Agent": http.DEFAULT_UA, "Referer": f"{WEB_ORIGIN}/"},
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ChannelError(self.id, "detail", f"invalid json: {exc}") from exc

        name = payload.get("name") or {}
        poster = payload.get("poster") or ""
        if isinstance(poster, dict):
            cover_path = str(poster.get("optimized", {}).get("preview") or poster.get("src") or "")
        else:
            cover_path = str(poster)
        episodes = payload.get("episodes") or []
        episodes.sort(key=lambda e: float(e.get("ordinal") or 0))

        group = ChannelEpisodeGroup(
            title="Anilibria",
            episodes=[
                ChannelEpisode(
                    title=f"第{int(float(e.get('ordinal') or 0))}集" if e.get("ordinal") else str(e.get("name") or ""),
                    episode_ref=self._episode_ref(int(payload.get("id") or 0), str(e.get("id") or "")),
                )
                for e in episodes
                if e.get("id")
            ],
        )
        return ChannelDetail(
            channel=self.id,
            title=str(name.get("english") or name.get("main") or ""),
            cover_url=self._abs(cover_path),
            description=str(payload.get("description") or "")[:500],
            groups=[group] if group.episodes else [],
        )

    async def get_streams(self, episode_ref: str) -> list[ChannelStream]:
        release_id, episode_id = self._parse_episode_ref(episode_ref)
        try:
            return await self._streams_from_episode(episode_id)
        except ChannelError:
            if release_id is not None:
                return await self._streams_from_release(release_id, episode_id)
            raise

    async def _streams_from_episode(self, episode_id: str) -> list[ChannelStream]:
        resp = await http.request(
            self.id,
            "streams",
            "GET",
            f"{API_BASE}/anime/releases/episodes/{episode_id}",
            headers={"User-Agent": http.DEFAULT_UA, "Referer": f"{WEB_ORIGIN}/"},
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ChannelError(self.id, "streams", f"invalid json: {exc}") from exc
        return self._build_streams(payload)

    async def _streams_from_release(self, release_id: int, episode_id: str) -> list[ChannelStream]:
        resp = await http.request(
            self.id,
            "streams",
            "GET",
            f"{API_BASE}/anime/releases/{release_id}",
            headers={"User-Agent": http.DEFAULT_UA, "Referer": f"{WEB_ORIGIN}/"},
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ChannelError(self.id, "streams", f"invalid json: {exc}") from exc
        for ep in payload.get("episodes") or []:
            if str(ep.get("id")) == episode_id:
                return self._build_streams(ep)
        raise ChannelError(self.id, "streams", "episode not found", retryable=False)

    @staticmethod
    def _build_streams(episode: dict) -> list[ChannelStream]:
        urls = [
            ("1080p", episode.get("hls_1080")),
            ("720p", episode.get("hls_720")),
            ("480p", episode.get("hls_480")),
        ]
        out: list[ChannelStream] = []
        for quality, url in urls:
            if not url:
                continue
            out.append(
                ChannelStream(
                    type="hls",
                    url=str(url),
                    quality=quality,
                    format="m3u8",
                    headers={"User-Agent": http.DEFAULT_UA, "Referer": f"{WEB_ORIGIN}/"},
                    note="Anilibria",
                )
            )
        return out
