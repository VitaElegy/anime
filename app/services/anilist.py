"""AniList GraphQL API service — native Chinese/Japanese/English anime search with covers."""

import logging

import httpx

from app.config import settings
from app.services import response_cache

logger = logging.getLogger(__name__)

ANILIST_URL = "https://graphql.anilist.co"

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        kwargs: dict = {
            "timeout": 15,
            "headers": {
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        }
        if settings.HTTP_PROXY:
            kwargs["proxy"] = settings.HTTP_PROXY
        _client = httpx.AsyncClient(**kwargs)
    return _client


# ─── Search ───

SEARCH_QUERY = """
query ($search: String, $page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { total currentPage lastPage hasNextPage }
    media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
      id
      title { romaji english native userPreferred }
      coverImage { large medium }
      bannerImage
      averageScore
      episodes
      status
      season
      seasonYear
      description(asHtml: false)
      genres
      format
    }
  }
}
"""

TRENDING_QUERY = """
query ($page: Int, $perPage: Int, $season: MediaSeason, $seasonYear: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { total }
    media(type: ANIME, sort: TRENDING_DESC, season: $season, seasonYear: $seasonYear) {
      id
      title { romaji english native userPreferred }
      coverImage { large medium }
      averageScore
      episodes
      status
      season
      seasonYear
      description(asHtml: false)
      genres
      format
    }
  }
}
"""

SCHEDULE_QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    airingSchedules(notYetAired: true, sort: TIME) {
      id
      airingAt
      episode
      media {
        id
        title { romaji english native userPreferred }
        coverImage { large medium }
        averageScore
        episodes
        status
      }
    }
  }
}
"""


def _format_anime(media: dict) -> dict:
    """Format AniList media into our standard structure."""
    title = media.get("title", {})
    cover = media.get("coverImage", {})
    return {
        "id": media.get("id", 0),
        "title_romaji": title.get("romaji", ""),
        "title_english": title.get("english", ""),
        "title_native": title.get("native", ""),
        "title_preferred": title.get("userPreferred", ""),
        "cover_large": cover.get("large", ""),
        "cover_medium": cover.get("medium", ""),
        "banner": media.get("bannerImage", ""),
        "score": (media.get("averageScore") or 0) / 10.0,  # AniList uses 0-100, we use 0-10
        "episodes": media.get("episodes") or 0,
        "status": media.get("status", ""),
        "season": media.get("season", ""),
        "season_year": media.get("seasonYear") or 0,
        "description": (media.get("description") or "")[:500],
        "genres": media.get("genres", []),
        "format": media.get("format", ""),
    }


async def search(keyword: str, page: int = 1, per_page: int = 20, force_refresh: bool = False) -> dict:
    """
    Search anime on AniList.
    AniList supports Chinese (full titles like '葬送的芙莉莲'), Japanese, and English.
    For partial Chinese names (like '芙莉莲') that AniList can't match,
    we fallback to Bangumi to get the full Japanese title and retry.
    """
    cache_key = response_cache.make_cache_key(
        "anilist.search",
        keyword=keyword.strip().lower(),
        page=page,
        per_page=per_page,
    )

    async def producer():
        return await _search_uncached(keyword, page=page, per_page=per_page)

    return await response_cache.get_or_set_json(
        cache_key=cache_key,
        cache_group="anilist.search",
        ttl_seconds=21600,
        producer=producer,
        force_refresh=force_refresh,
        allow_stale=True,
    )


async def _search_uncached(keyword: str, page: int = 1, per_page: int = 20) -> dict:
    """Raw AniList search with Bangumi fallback."""
    import re

    result = await _do_search(keyword, page, per_page)

    # If no results and keyword contains Chinese, translate via Bangumi
    if not result["items"] and re.search(r"[\u4e00-\u9fff]", keyword):
        try:
            from app.services import bangumi

            bgm_results = await bangumi.search(keyword, limit=3)
            for bgm in bgm_results:
                # Try Japanese name on AniList
                if bgm.name:
                    result = await _do_search(bgm.name, page, per_page)
                    if result["items"]:
                        break
                # Try English-ish name
                if bgm.name_cn and bgm.name_cn != keyword:
                    result = await _do_search(bgm.name_cn, page, per_page)
                    if result["items"]:
                        break
        except Exception as e:
            logger.warning("Bangumi fallback failed: %s", e)

    return result


async def _do_search(keyword: str, page: int = 1, per_page: int = 20) -> dict:
    """Raw AniList search."""
    client = _get_client()
    try:
        resp = await client.post(
            ANILIST_URL,
            json={
                "query": SEARCH_QUERY,
                "variables": {"search": keyword, "page": page, "perPage": per_page},
            },
        )
        resp.raise_for_status()
        data = resp.json()

        page_data = data.get("data", {}).get("Page", {})
        page_info = page_data.get("pageInfo", {})
        media_list = page_data.get("media", [])

        return {
            "items": [_format_anime(m) for m in media_list],
            "total": page_info.get("total", 0),
            "has_next": page_info.get("hasNextPage", False),
            "source": "anilist",
        }
    except Exception as e:
        logger.error("AniList search failed: %s", e)
        return {"items": [], "total": 0, "has_next": False, "source": "anilist"}


async def get_trending(
    season: str = "",
    year: int = 0,
    page: int = 1,
    per_page: int = 20,
    force_refresh: bool = False,
) -> dict:
    """Get currently trending anime."""
    cache_key = response_cache.make_cache_key(
        "anilist.trending",
        season=season.upper(),
        year=year,
        page=page,
        per_page=per_page,
    )

    async def producer():
        return await _get_trending_uncached(season=season, year=year, page=page, per_page=per_page)

    return await response_cache.get_or_set_json(
        cache_key=cache_key,
        cache_group="anilist.trending",
        ttl_seconds=1800,
        producer=producer,
        force_refresh=force_refresh,
        allow_stale=True,
    )


async def _get_trending_uncached(season: str = "", year: int = 0, page: int = 1, per_page: int = 20) -> dict:
    """Fetch trending anime from AniList."""
    client = _get_client()
    variables: dict = {"page": page, "perPage": per_page}
    if season:
        variables["season"] = season.upper()
    if year:
        variables["seasonYear"] = year

    try:
        resp = await client.post(
            ANILIST_URL,
            json={
                "query": TRENDING_QUERY,
                "variables": variables,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        media_list = data.get("data", {}).get("Page", {}).get("media", [])
        return {
            "items": [_format_anime(m) for m in media_list],
            "total": len(media_list),
            "source": "anilist",
        }
    except Exception as e:
        logger.error("AniList trending failed: %s", e)
        return {"items": [], "total": 0, "source": "anilist"}


async def get_airing_schedule(page: int = 1, per_page: int = 50, force_refresh: bool = False) -> dict:
    """Get upcoming airing schedule."""
    cache_key = response_cache.make_cache_key(
        "anilist.schedule",
        page=page,
        per_page=per_page,
    )

    async def producer():
        return await _get_airing_schedule_uncached(page=page, per_page=per_page)

    return await response_cache.get_or_set_json(
        cache_key=cache_key,
        cache_group="anilist.schedule",
        ttl_seconds=900,
        producer=producer,
        force_refresh=force_refresh,
        allow_stale=True,
    )


async def _get_airing_schedule_uncached(page: int = 1, per_page: int = 50) -> dict:
    """Fetch upcoming airing schedule."""
    client = _get_client()
    try:
        resp = await client.post(
            ANILIST_URL,
            json={
                "query": SCHEDULE_QUERY,
                "variables": {"page": page, "perPage": per_page},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        schedules = data.get("data", {}).get("Page", {}).get("airingSchedules", [])

        items = []
        for s in schedules:
            media = s.get("media", {})
            item = _format_anime(media)
            item["airing_at"] = s.get("airingAt", 0)
            item["next_episode"] = s.get("episode", 0)
            items.append(item)

        return {"items": items, "total": len(items), "source": "anilist"}
    except Exception as e:
        logger.error("AniList schedule failed: %s", e)
        return {"items": [], "total": 0, "source": "anilist"}
