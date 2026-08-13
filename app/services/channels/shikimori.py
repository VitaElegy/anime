"""Shikimori channel — free open metadata + official external links (backup source).

Backup Resource Library (docs/RESOURCE_BACKUP_PLAN.md §2.3):
- ``search``: GET https://shikimori.one/api/animes?search=<kw> → standardized
  hits (romaji display title, Russian original, poster, score/status/episodes).
  Shikimori is an open community DB (no auth, stable); it has **no Chinese
  titles**, so it is a secondary metadata fallback after Kitsu/Bangumi.
- ``external_url``: official page https://shikimori.one/animes/{id} (the page
  lists licensed streaming links where available).
- v1 is external-only (like Kitsu): no per-episode UI, no streams.

Verified 2026-08-13 (via Clash 7892): search "frieren" → 3 hits (main series
ranked 3rd — relevance is weaker than Kitsu, acceptable for a backup source).
"""

from __future__ import annotations

import logging
import re

from app.models import ChannelSearchResult
from app.services.channels import http
from app.services.channels.base import ChannelError, ChannelProvider

logger = logging.getLogger(__name__)

ORIGIN = "https://shikimori.one"
API_BASE = f"{ORIGIN}/api"
SEARCH_LIMIT = 6
HEADERS = {"User-Agent": http.DEFAULT_UA, "Accept": "application/json"}

#: CJK ranges (CJK Unified Ideographs + Hiragana + Katakana + Hangul).
_CJK_RE = re.compile(r"[\u3000-\u30ff\u4e00-\u9fff\uac00-\ud7af]")


class ShikimoriChannel(ChannelProvider):
    """Shikimori — free open metadata + official watching entry (backup)."""

    id = "shikimori"
    name = "Shikimori"
    language = "en"
    description = "开源社区元数据 + 官方观看入口（备选库）"
    supports_detail = False
    supports_streams = False
    external = True
    priority = 65

    @staticmethod
    def _has_cjk(keyword: str) -> bool:
        """True when the keyword contains CJK characters."""
        return bool(_CJK_RE.search(keyword))

    @staticmethod
    def _relevant(item: dict, keyword: str) -> bool:
        """Drop clearly unrelated hits from Shikimori's fuzzy search.

        The index is romaji/Russian; a CJK keyword makes Shikimori fall back to
        pinyin fuzzy matching that returns mostly noise, so CJK queries return
        no hits here (the registry's keyword expansion supplies the Latin
        alternative that matches, docs/CHANNEL_ARCHITECTURE.md §1.2). For Latin
        keywords we keep a hit only when a significant query token (>=3 alnum
        chars) appears in its romanized name.
        """
        name = (item.get("name") or "").lower()
        tokens = {t.lower() for t in re.findall(r"[a-z0-9']+", keyword) if len(t) >= 3}
        return not tokens or any(tok in name for tok in tokens)

    @staticmethod
    def _abs_image(path: str) -> str:
        """API image paths are relative (/system/...) → absolute URL."""
        if not path:
            return ""
        if path.startswith("http"):
            return path
        return f"{ORIGIN}{path}" if path.startswith("/") else path

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        # Short-circuit CJK before any upstream call: Shikimori's romaji index
        # cannot match Chinese/Japanese meaningfully (see _relevant docstring).
        if self._has_cjk(keyword):
            return []
        resp = await http.request(
            self.id,
            "search",
            "GET",
            f"{API_BASE}/animes",
            params={"search": keyword, "limit": SEARCH_LIMIT, "page": page},
            headers=HEADERS,
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ChannelError(self.id, "search", f"invalid json: {exc}") from exc
        if not isinstance(payload, list):
            raise ChannelError(self.id, "search", "unexpected payload shape", retryable=False)

        out: list[ChannelSearchResult] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            if not self._relevant(item, keyword):
                continue
            anime_id = str(item.get("id") or "")
            name = item.get("name") or ""
            if not anime_id or not name:
                continue
            image = item.get("image") or {}
            cover = self._abs_image(image.get("preview") or image.get("original") or "")
            aired = item.get("aired_on") or ""
            out.append(
                ChannelSearchResult(
                    channel=self.id,
                    title=name,
                    title_original=item.get("russian") or "",
                    cover_url=cover,
                    description="",
                    year=aired[:4],
                    detail_ref=anime_id,
                    extra={
                        "score": item.get("score") or "",
                        "status": item.get("status") or "",
                        "kind": item.get("kind") or "",
                        "episodes": item.get("episodes") or 0,
                        "episodes_aired": item.get("episodes_aired") or 0,
                        "url": item.get("url") or "",
                    },
                )
            )
        return out

    def external_url(self, detail_ref: str) -> str:
        return f"{ORIGIN}/animes/{detail_ref}"
