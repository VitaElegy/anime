"""Zzzfun channel — Android app JSON API.

Ported from zaxtyson/Anime-API `api/anime/zzzfun.py`
(MIT License, Copyright (c) 2020 zaxtyson). See docs/CHANNEL_ARCHITECTURE.md §8.
"""

from __future__ import annotations

import hashlib
import logging
import time

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

API_BASE = "http://service-agbhuggw-1259251677.gz.apigw.tencentcs.com/android"
SECRET_KEY = "zan109drdddzz"
APP_UA = "okhttp/3.12.0"


class ZzzfunChannel(ChannelProvider):
    """Zzzfun（Android 接口）."""

    id = "zzzfun"
    name = "Zzzfun"
    language = "zh"
    description = "在线动漫（App 接口，播放地址访问后可能失效）"

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        resp = await http.request(
            self.id,
            "search",
            "POST",
            f"{API_BASE}/search",
            data={"userid": "", "key": keyword},
            headers={"User-Agent": APP_UA},
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ChannelError(self.id, "search", f"invalid json: {exc}") from exc

        out: list[ChannelSearchResult] = []
        for meta in payload.get("data") or []:
            vid = meta.get("videoId")
            if vid is None:
                continue
            out.append(
                ChannelSearchResult(
                    channel=self.id,
                    title=str(meta.get("videoName") or ""),
                    cover_url=str(meta.get("videoImg") or ""),
                    description=str(meta.get("videoDoc") or "")[:300],
                    detail_ref=str(vid),
                    extra={"videoClass": str(meta.get("videoClass") or "")},
                )
            )
        return out

    async def get_detail(self, detail_ref: str) -> ChannelDetail:
        resp = await http.request(
            self.id,
            "detail",
            "POST",
            f"{API_BASE}/video/list_ios",
            params={"userid": "", "videoId": detail_ref},
            headers={"User-Agent": APP_UA},
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ChannelError(self.id, "detail", f"invalid json: {exc}") from exc

        data = payload.get("data") or {}
        groups: list[ChannelEpisodeGroup] = []
        for video_set in data.get("videoSets") or []:
            episodes = [
                ChannelEpisode(
                    title=str(ep.get("ji") or ""),
                    episode_ref=str(ep.get("playid") or ""),
                )
                for ep in (video_set.get("list") or [])
                if ep.get("playid")
            ]
            if episodes:
                groups.append(
                    ChannelEpisodeGroup(title=str(video_set.get("load") or "线路"), episodes=episodes)
                )

        return ChannelDetail(
            channel=self.id,
            title=str(data.get("videoName") or ""),
            cover_url=str(data.get("videoImg") or ""),
            description=str(data.get("videoDoc") or "").replace("\r\n", ""),
            groups=groups,
        )

    async def get_streams(self, episode_ref: str) -> list[ChannelStream]:
        now = int(time.time() * 1000)
        sing = hashlib.md5((SECRET_KEY + str(now)).encode("utf-8")).hexdigest()
        resp = await http.request(
            self.id,
            "streams",
            "POST",
            f"{API_BASE}/video/112play",
            data={
                "playid": episode_ref,
                "userid": "",
                "apptoken": "",
                "sing": sing,
                "map": now,
            },
            headers={"User-Agent": APP_UA},
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ChannelError(self.id, "streams", f"invalid json: {exc}") from exc

        data = payload.get("data") or {}
        url = str(data.get("videoplayurl") or "")
        if not url:
            return []
        is_hls = "alicdn" in url or "zzzhls" in url
        return [
            ChannelStream(
                type="hls" if is_hls else "mp4",
                url=url,
                quality="auto",
                format="m3u8" if is_hls else "mp4",
                headers={"User-Agent": APP_UA},
                note="Zzzfun（访问后可能失效）",
            )
        ]
