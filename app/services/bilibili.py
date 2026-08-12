"""Bilibili 番剧正版入口服务 — 查询番剧播放信息，提供 B 站正版观看入口。

Public endpoints (no cookie required, confirmed by live audit):
- Lightweight card:   GET /pgc/review/user?media_id={media_id}
- Full season detail: GET /pgc/view/web/season?season_id={season_id}
- Search:             GET /x/web-interface/search/type?search_type=media_bangumi&keyword={kw}

We use search → season_id lookup as the primary path, with the lightweight
review API as a fallback / listing helper.
"""

import asyncio
import logging
import time

import httpx

from app.config import settings
from app.models import StreamingLink
from app.services import response_cache

logger = logging.getLogger(__name__)

_last_request_time: float = 0
_lock = asyncio.Lock()
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        kwargs: dict = {
            "timeout": 30,
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                "Referer": "https://www.bilibili.com/",
            },
            "follow_redirects": True,
        }
        if settings.HTTP_PROXY:
            kwargs["proxy"] = settings.HTTP_PROXY
        _client = httpx.AsyncClient(**kwargs)
    return _client


async def _rate_limit():
    global _last_request_time
    async with _lock:
        now = time.monotonic()
        wait = settings.BILIBILI_RATE_LIMIT - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time = time.monotonic()


def _clean_title(raw: str) -> str:
    """B 站搜索结果的 title 含 <em> 高亮标签，去掉它。"""
    import re

    return re.sub(r"</?em[^>]*>", "", raw or "").strip()


# ---------------------------------------------------------------------------
# search_bangumi — returns list of StreamingLink candidates
# ---------------------------------------------------------------------------


async def search_bangumi(keyword: str, limit: int = 3, force_refresh: bool = False) -> list[StreamingLink]:
    """Search Bilibili for 番剧 matching the given keyword. Returns up to `limit` items."""
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    cache_key = response_cache.make_cache_key("bilibili.search_bangumi", keyword=keyword.lower(), limit=limit)

    async def producer():
        results = await _search_bangumi_uncached(keyword, limit=limit)
        return [r.model_dump(mode="json") for r in results]

    payload = await response_cache.get_or_set_json(
        cache_key=cache_key,
        cache_group="bilibili.search",
        ttl_seconds=21600,
        producer=producer,
        force_refresh=force_refresh,
        allow_stale=True,
    )
    return [StreamingLink.model_validate(p) for p in (payload or [])]


async def _search_bangumi_uncached(keyword: str, limit: int = 3) -> list[StreamingLink]:
    await _rate_limit()
    client = _get_client()
    url = f"{settings.BILIBILI_API_BASE}/x/web-interface/search/type"
    params = {
        "search_type": "media_bangumi",
        "keyword": keyword,
        "page": 1,
    }

    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Bilibili search failed: %s", e)
        return []

    try:
        data = resp.json()
    except Exception:
        return []

    if data.get("code") != 0:
        # 412 / 403 happen when Bilibili's anti-crawl kicks in without cookie.
        logger.info("Bilibili search rejected: %s", data.get("message"))
        return []

    results = data.get("data", {}).get("result", []) or []
    out: list[StreamingLink] = []
    for r in results[: max(1, limit)]:
        season_id = str(r.get("season_id") or "")
        if not season_id:
            continue
        share_url = (
            r.get("goto_url") or r.get("url") or f"https://www.bilibili.com/bangumi/play/ss{season_id}"
        )
        if share_url.startswith("//"):
            share_url = "https:" + share_url
        cover = r.get("cover") or ""
        if cover.startswith("//"):
            cover = "https:" + cover
        out.append(
            StreamingLink(
                platform="bilibili",
                title=_clean_title(r.get("title") or r.get("org_title") or ""),
                url=share_url,
                season_id=season_id,
                cover_url=cover,
                total_episodes=int(r.get("ep_size") or 0) or 0,
                is_finished=bool(r.get("is_finish", 0)) if r.get("is_finish") is not None else False,
                is_paid=bool(r.get("pay_pack_paid", 0)),
                paid_note="大会员/付费" if r.get("pay_pack_paid") else "",
            )
        )
    return out


# ---------------------------------------------------------------------------
# get_season_detail — rich data from /pgc/view/web/season
# ---------------------------------------------------------------------------


async def get_season_detail(season_id: str | int, force_refresh: bool = False) -> dict | None:
    """Return the raw `result` object from /pgc/view/web/season (or None)."""
    if not season_id:
        return None

    cache_key = response_cache.make_cache_key("bilibili.season", season_id=str(season_id))

    async def producer():
        data = await _get_season_detail_uncached(season_id)
        return data

    payload = await response_cache.get_or_set_json(
        cache_key=cache_key,
        cache_group="bilibili.season",
        ttl_seconds=10800,
        producer=producer,
        force_refresh=force_refresh,
        allow_stale=True,
    )
    return payload


async def _get_season_detail_uncached(season_id: str | int) -> dict | None:
    await _rate_limit()
    client = _get_client()
    url = f"{settings.BILIBILI_API_BASE}/pgc/view/web/season"
    try:
        resp = await client.get(url, params={"season_id": season_id})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Bilibili season detail failed for %s: %s", season_id, e)
        return None

    try:
        data = resp.json()
    except Exception:
        return None

    if data.get("code") != 0:
        logger.info("Bilibili season detail rejected: %s", data.get("message"))
        return None

    result = data.get("result") or {}
    # Extract only what we need so we're not caching unbounded blobs forever.
    stat = result.get("stat") or {}
    rating = result.get("rating") or {}
    publish = result.get("publish") or {}
    new_ep = result.get("new_ep") or {}
    return {
        "season_id": str(result.get("season_id") or season_id),
        "media_id": str(result.get("media_id") or ""),
        "title": result.get("title") or result.get("season_title") or "",
        "cover": result.get("cover") or "",
        "evaluate": result.get("evaluate") or "",
        "total_episodes": int(result.get("total") or new_ep.get("total") or 0) or 0,
        "is_finish": bool(publish.get("is_finish", 0)),
        "pub_time": publish.get("pub_time_show") or publish.get("pub_time") or "",
        "score": float(rating.get("score") or 0.0),
        "score_count": int(rating.get("count") or 0),
        "views": int(stat.get("views") or 0),
        "follow": int(stat.get("follow") or 0),
        "share_url": result.get("share_url")
        or f"https://www.bilibili.com/bangumi/play/ss{result.get('season_id') or season_id}",
        "styles": result.get("styles") or [],
        "new_ep_index": new_ep.get("index") or "",
        "new_ep_desc": new_ep.get("desc") or "",
        "can_watch": bool((result.get("rights") or {}).get("can_watch", 1)),
    }


async def find_best_bangumi_link(keyword: str) -> StreamingLink | None:
    """High-level helper: search, then return the first StreamingLink w/ seasonId."""
    candidates = await search_bangumi(keyword, limit=3)
    return candidates[0] if candidates else None
