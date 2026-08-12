"""Bilibili channel — official external-link only (no proxied playback).

Reuses the existing app/services/bilibili.py metadata search and exposes it
through the channel contract so the detail page can offer Bilibili as a
"watch on official site" option.
"""

from __future__ import annotations

import logging

from app.models import ChannelSearchResult
from app.services import bilibili as bilibili_service
from app.services.channels.base import ChannelProvider

logger = logging.getLogger(__name__)


class BilibiliChannel(ChannelProvider):
    """Bilibili 番剧正版入口."""

    id = "bilibili"
    name = "Bilibili 番剧"
    language = "zh"
    supports_detail = False
    supports_streams = False
    external = True
    description = "B站正版番剧（跳转官方页面观看）"

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        links = await bilibili_service.search_bangumi(keyword, limit=12)
        out: list[ChannelSearchResult] = []
        for link in links:
            if not link.season_id:
                continue
            out.append(
                ChannelSearchResult(
                    channel=self.id,
                    title=link.title or "",
                    cover_url=link.cover_url or "",
                    detail_ref=str(link.season_id),
                    extra={
                        "total_episodes": link.total_episodes,
                        "is_paid": link.is_paid,
                        "score": link.score,
                    },
                )
            )
        return out

    def external_url(self, detail_ref: str) -> str:
        return f"https://www.bilibili.com/bangumi/play/ss{detail_ref}"
