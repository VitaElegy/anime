"""Kitsu channel — free open metadata + official external links (backup source).

Backup Resource Library v1 (docs/RESOURCE_BACKUP_PLAN.md §1.1 / §2.1):
- ``search``:  GET /api/edge/anime?filter[text]=<kw> → standardized hits.
  Kitsu records carry ``titles.zh_cn`` so Chinese-first search still renders
  Chinese titles/descriptions/covers even when Bangumi is unreachable.
- ``external_url``: official page https://kitsu.io/anime/{id} (lists licensed
  streaming links such as Crunchyroll).
- v1 is external-only: episodes / streaming-links endpoints are documented in
  RESOURCE_BACKUP_PLAN.md §2.1 and reserved for P2 (per-episode external UI).

Verified 2026-08-13 (via Clash 7892): search "Frieren" → 葬送的芙莉蓮,
28 episodes, poster + synopsis; kitsu.io/anime/46474 → 200.
"""

from __future__ import annotations

import logging

from app.models import ChannelSearchResult
from app.services.channels import http
from app.services.channels.base import ChannelError, ChannelProvider

logger = logging.getLogger(__name__)

API_BASE = "https://kitsu.io/api/edge"
WEB_BASE = "https://kitsu.io/anime"
SEARCH_LIMIT = 10
HEADERS = {"User-Agent": http.DEFAULT_UA, "Accept": "application/vnd.api+json"}


class KitsuChannel(ChannelProvider):
    """Kitsu — free open metadata + official watching entry (backup)."""

    id = "kitsu"
    name = "Kitsu"
    language = "zh-en"
    description = "免费开放元数据 + 官方观看入口（备选库）"
    supports_detail = False
    supports_streams = False
    external = True
    priority = 60

    @staticmethod
    def _attrs(item: dict) -> dict:
        return item.get("attributes") or {}

    @staticmethod
    def _title(attrs: dict) -> tuple[str, str]:
        """Return (display_title, original_title): zh_cn first, then canonical/en."""
        titles = attrs.get("titles") or {}
        zh = titles.get("zh_cn") or titles.get("zh") or ""
        canonical = attrs.get("canonicalTitle") or ""
        en = titles.get("en") or titles.get("en_jp") or ""
        return (zh or canonical or en), (canonical or en or zh)

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        resp = await http.request(
            self.id,
            "search",
            "GET",
            f"{API_BASE}/anime",
            params={
                "filter[text]": keyword,
                "page[limit]": SEARCH_LIMIT,
                "page[offset]": (page - 1) * SEARCH_LIMIT,
            },
            headers=HEADERS,
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ChannelError(self.id, "search", f"invalid json: {exc}") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise ChannelError(self.id, "search", "unexpected payload shape", retryable=False)

        out: list[ChannelSearchResult] = []
        for item in data:
            anime_id = str(item.get("id") or "")
            if not anime_id:
                continue
            attrs = self._attrs(item)
            display, original = self._title(attrs)
            if not display:
                continue
            poster = (attrs.get("posterImage") or {}).get("small") or (attrs.get("posterImage") or {}).get("original") or ""
            out.append(
                ChannelSearchResult(
                    channel=self.id,
                    title=display,
                    title_original=original,
                    cover_url=poster,
                    description=(attrs.get("synopsis") or "")[:200],
                    year=(attrs.get("startDate") or "")[:4],
                    detail_ref=anime_id,
                    extra={
                        "episode_count": attrs.get("episodeCount") or 0,
                        "average_rating": attrs.get("averageRating") or "",
                        "status": attrs.get("status") or "",
                    },
                )
            )
        return out

    def external_url(self, detail_ref: str) -> str:
        return f"{WEB_BASE}/{detail_ref}"
