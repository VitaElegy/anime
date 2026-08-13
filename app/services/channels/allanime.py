"""AllAnime channel — free open GraphQL catalog + official watch pages (backup source).

Backup Resource Library v1 (docs/RESOURCE_BACKUP_PLAN.md §2.4):
- ``search``: POST https://api.mkissa.net/api (GraphQL) → standardized hits.
  AllAnime is a large free English anime catalog; the mkissa.net mirror is the
  current working API host (ani-cli PR #1779 migrated off the dead
  api.allanime.day 2026-07-22). Search carries sub/dub/raw episode counts.
- ``external_url``: https://mkissa.to/anime/{_id} (official watch page).
- v1 is external-only (same scope as Kitsu / Shikimori): no ``get_detail`` /
  ``get_streams``. Full in-player HLS requires the aaReq AES-256-GCM proof
  token, the per-epoch key scraped from the obfuscated mkissa bundle and
  ``tobeparsed`` decryption — reserved as P1 in RESOURCE_BACKUP_PLAN.md §2.4.

Verified 2026-08-13 (via Clash 7892): GraphQL search "Frieren" → 5 hits, main
series (28 sub / 28 dub) ranked first after sort; mkissa.to/anime/{_id} → 200;
Chinese query → 0 edges (no noise, no short-circuit needed).
"""

from __future__ import annotations

import logging

from app.models import ChannelSearchResult
from app.services.channels import http
from app.services.channels.base import ChannelError, ChannelProvider

logger = logging.getLogger(__name__)

API_ENDPOINT = "https://api.mkissa.net/api"
WEB_BASE = "https://mkissa.to/anime"
ORIGIN = "https://mkissa.to"
SEARCH_LIMIT = 10
HEADERS = {
    "Content-Type": "application/json",
    "Referer": ORIGIN,
    "Origin": ORIGIN,
}

#: GraphQL search query (mirrors the Curd / ani-cli reference shape).
SEARCH_GQL = """\
query($search: SearchInput, $limit: Int, $page: Int, $translationType: VaildTranslationTypeEnumType, $countryOrigin: VaildCountryOriginEnumType) {
  shows(search: $search, limit: $limit, page: $page, translationType: $translationType, countryOrigin: $countryOrigin) {
    edges {
      _id
      name
      englishName
      availableEpisodes
      __typename
    }
  }
}
"""


def _int_count(value) -> int:
    """Coerce an episode count from the GraphQL payload (int/float/str/None)."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class AllAnimeChannel(ChannelProvider):
    """AllAnime — free open English catalog + official watch entry (backup)."""

    id = "allanime"
    name = "AllAnime (mkissa)"
    language = "en"
    description = "开源 GraphQL 目录 + 官方观看页（备选库）"
    supports_detail = False
    supports_streams = False
    external = True
    priority = 62

    @staticmethod
    def _edges(payload: dict) -> list:
        data = payload.get("data") if isinstance(payload, dict) else None
        shows = data.get("shows") if isinstance(data, dict) else None
        edges = shows.get("edges") if isinstance(shows, dict) else None
        if not isinstance(edges, list):
            raise ChannelError(
                "allanime", "search", "unexpected payload shape", retryable=False
            )
        return edges

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        variables = {
            "search": {
                "allowAdult": False,
                "allowUnknown": False,
                "query": keyword,
            },
            "limit": SEARCH_LIMIT,
            "page": page,
            "translationType": "sub",
            "countryOrigin": "ALL",
        }
        resp = await http.request(
            self.id,
            "search",
            "POST",
            API_ENDPOINT,
            headers=HEADERS,
            json_body={"variables": variables, "query": SEARCH_GQL},
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ChannelError(self.id, "search", f"invalid json: {exc}") from exc

        edges = [e for e in self._edges(payload) if isinstance(e, dict)]
        # Main series (most episodes) first, like the GoAnime reference sort.
        edges.sort(
            key=lambda e: _int_count((e.get("availableEpisodes") or {}).get("sub"))
            + _int_count((e.get("availableEpisodes") or {}).get("dub")),
            reverse=True,
        )

        out: list[ChannelSearchResult] = []
        for edge in edges:
            anime_id = str(edge.get("_id") or "")
            romaji = str(edge.get("name") or "").strip()
            english = str(edge.get("englishName") or "").strip()
            if not anime_id or not (romaji or english):
                continue
            episodes = edge.get("availableEpisodes") or {}
            sub = _int_count(episodes.get("sub"))
            dub = _int_count(episodes.get("dub"))
            raw = _int_count(episodes.get("raw"))
            display = english or romaji
            out.append(
                ChannelSearchResult(
                    channel=self.id,
                    title=display,
                    title_original=romaji if english else "",
                    cover_url="",
                    description="",
                    year="",
                    detail_ref=anime_id,
                    extra={
                        "sub_episodes": sub,
                        "dub_episodes": dub,
                        "raw_episodes": raw,
                        "total_episodes": sub + dub + raw,
                    },
                )
            )
        return out

    def external_url(self, detail_ref: str) -> str:
        return f"{WEB_BASE}/{detail_ref}"
