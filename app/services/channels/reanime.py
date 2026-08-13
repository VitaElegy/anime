"""ReAnime channel — free open search + external watch page (backup source).

Backup Resource Library P2 (docs/RESOURCE_BACKUP_PLAN.md §2.9 / roadmap item 6):
- ``search``:  GET /api/v1/search?q=<kw> → standardized hits (AniList-derived
  metadata: english/native/romaji titles, cover, year, score, episode count).
- ``external_url``: site player page https://reanime.to/watch/{anime_id}
  (real page verified 200; stream API `/api/v1/episodes` still requires the
  site's JS-generated auth, so this provider is external-only like Kitsu).

Verified 2026-08-13 (via Clash 7892): /api/v1/search?q=Frieren → 200 JSON with
4 hits; /api/v1/anime/{slug} → 200 metadata; /api/v1/watch/{slug} → 200
metadata + progress (but no episode list); /api/v1/episodes/{slug} → 401.
Reference (endpoints only, independent implementation):
~/work/Project/_reference/ReAnime.to-API (reanime.py + decrypt.mjs).
"""

from __future__ import annotations

import logging

from app.models import ChannelSearchResult
from app.services.channels import http
from app.services.channels.base import ChannelError, ChannelProvider

logger = logging.getLogger(__name__)

API_BASE = "https://reanime.to/api/v1"
WEB_BASE = "https://reanime.to/watch"
SEARCH_LIMIT = 20
HEADERS = {"User-Agent": http.DEFAULT_UA, "Accept": "application/json"}


class ReAnimeChannel(ChannelProvider):
    """ReAnime.to — free anime search + official site watch page (backup)."""

    id = "reanime"
    name = "ReAnime"
    language = "en"
    description = "免费开放搜索 + 站点观看页（备选库 P2）"
    supports_detail = False
    supports_streams = False
    external = True
    priority = 70

    @staticmethod
    def _title(item: dict) -> tuple[str, str]:
        """Return (display_title, original_title): user_preferred/english first,
        then romaji, then native."""
        raw = item.get("title") or {}
        if not isinstance(raw, dict):
            return "", ""
        preferred = raw.get("user_preferred") or ""
        english = raw.get("english") or ""
        romaji = raw.get("romaji") or ""
        native = raw.get("native") or ""
        return (preferred or english or romaji or native), (romaji or english or native)

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        resp = await http.request(
            self.id,
            "search",
            "GET",
            f"{API_BASE}/search",
            params={"q": keyword, "limit": SEARCH_LIMIT, "offset": (page - 1) * SEARCH_LIMIT},
            headers=HEADERS,
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ChannelError(self.id, "search", f"invalid json: {exc}") from exc
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise ChannelError(self.id, "search", "unexpected payload shape", retryable=False)

        out: list[ChannelSearchResult] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            anime_id = str(item.get("anime_id") or "")
            if not anime_id:
                continue
            display, original = self._title(item)
            if not display:
                continue
            cover = (item.get("cover_image") or {})
            cover_url = (
                cover.get("medium")
                or cover.get("large")
                or cover.get("extra_large")
                or ""
            )
            out.append(
                ChannelSearchResult(
                    channel=self.id,
                    title=display,
                    title_original=original,
                    cover_url=cover_url,
                    description="",
                    year=str(item.get("season_year") or "")[:4],
                    detail_ref=anime_id,
                    extra={
                        "format": item.get("format") or "",
                        "status": item.get("status") or "",
                        "episode_count": item.get("episodes") or 0,
                        "average_score": item.get("average_score") or 0,
                        "can_watch": bool(item.get("can_watch")),
                    },
                )
            )
        return out

    def external_url(self, detail_ref: str) -> str:
        return f"{WEB_BASE}/{detail_ref}"
