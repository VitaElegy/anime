"""AGE动漫 channel — clean JSON API at api.agedm.org.

Pattern based on the Miru extension `agedm.org.js`
(https://github.com/miru-project/repo, MIT).
"""

from __future__ import annotations

import logging
import re

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

API_BASE = "https://api.agedm.org"
WEB_ORIGIN = "https://m.agedm.org"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/244.178.44.111 Safari/537.36"
)


class AgeChannel(ChannelProvider):
    """AGE动漫 (api.agedm.org/v2)."""

    id = "age"
    name = "AGE动漫"
    language = "zh"
    description = "在线动漫站 JSON API"

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        resp = await http.request(
            self.id,
            "search",
            "GET",
            f"{API_BASE}/v2/search",
            params={"query": keyword, "page": page},
            headers={"User-Agent": UA},
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ChannelError(self.id, "search", f"invalid json: {exc}") from exc

        videos = ((payload or {}).get("data") or {}).get("videos") or []
        out: list[ChannelSearchResult] = []
        for item in videos:
            vid = item.get("id")
            if vid is None:
                continue
            out.append(
                ChannelSearchResult(
                    channel=self.id,
                    title=str(item.get("name") or ""),
                    title_original=str(item.get("name_other") or ""),
                    cover_url=str(item.get("cover") or ""),
                    description=str(item.get("intro") or "")[:300],
                    detail_ref=str(vid),
                    extra={"uptodate": str(item.get("uptodate") or "")},
                )
            )
        return out

    async def get_detail(self, detail_ref: str) -> ChannelDetail:
        resp = await http.request(
            self.id,
            "detail",
            "GET",
            f"{API_BASE}/v2/detail/{detail_ref}",
            headers={"User-Agent": UA, "Referer": f"{WEB_ORIGIN}/"},
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ChannelError(self.id, "detail", f"invalid json: {exc}") from exc

        video = ((payload or {}).get("video")) or {}
        playlists = video.get("playlists") or {}
        labels = video.get("player_label_arr") or {}
        jx_prefix = (video.get("player_jx") or {}).get("zj") or ""

        groups: list[ChannelEpisodeGroup] = []
        for key, items in playlists.items():
            if "m3u8" not in key:
                continue
            episodes: list[ChannelEpisode] = []
            for item in items or []:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                episodes.append(
                    ChannelEpisode(
                        title=str(item[0]),
                        episode_ref=f"{jx_prefix}{item[1]}",
                    )
                )
            if episodes:
                groups.append(
                    ChannelEpisodeGroup(title=str(labels.get(key) or key), episodes=episodes)
                )

        return ChannelDetail(
            channel=self.id,
            title=str(video.get("name") or ""),
            cover_url=f"https://cdn.aqdstatic.com:966/age/{detail_ref}.jpg",
            description=str(video.get("intro") or ""),
            groups=groups,
        )

    async def get_streams(self, episode_ref: str) -> list[ChannelStream]:
        resp = await http.request(
            self.id,
            "streams",
            "GET",
            episode_ref,
            headers={"User-Agent": UA, "Referer": f"{WEB_ORIGIN}/"},
        )
        match = re.search(r"Vurl\s*=\s*'(.+?)'", resp.text or "")
        if not match:
            return []
        url = match.group(1).strip()
        if not url.startswith("http"):
            return []
        return [
            ChannelStream(
                type="hls",
                url=url,
                quality="auto",
                format="m3u8",
                headers={"User-Agent": UA, "Referer": f"{WEB_ORIGIN}/"},
                note="AGE动漫",
            )
        ]
