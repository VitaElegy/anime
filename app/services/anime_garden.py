"""AnimeGarden (https://animes.garden) — aggregated dmhy + moe mirror JSON API.

The upstream service normalizes resources from 动漫花园 (dmhy) and 萌番组 (moe),
exposing them via a clean JSON API that we can consume without HTML scraping.

Endpoint base: https://api.animes.garden
- GET /resources?page=1&pageSize=20&search=keyword
  Returns: {status, resources: [...], pagination: {...}}
- Resource schema (confirmed by live audit):
  {
    id, provider ("dmhy"|"moe"), providerId, title, href, type,
    magnet, size (bytes), createdAt, fetchedAt,
    publisher: {id, name, avatar},
    fansub: {id, name, avatar} | null,
  }
"""

import asyncio
import logging
import re
import time

import httpx

from app.config import settings
from app.models import SearchResult, TorrentItem
from app.services import response_cache

logger = logging.getLogger(__name__)

_last_request_time: float = 0
_lock = asyncio.Lock()
_client: httpx.AsyncClient | None = None

_INFO_HASH_RE = re.compile(r"btih:([a-fA-F0-9]{40})", re.IGNORECASE)


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        kwargs: dict = {
            "timeout": 30,
            "headers": {
                "User-Agent": "AnimeDownloader/1.0 (+https://github.com/)",
                "Accept": "application/json",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
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
        wait = settings.ANIME_GARDEN_RATE_LIMIT - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time = time.monotonic()


def _format_size(num_bytes: int) -> str:
    if not num_bytes or num_bytes <= 0:
        return ""
    # AnimeGarden returns size in KB (per live audit); treat < 1e7 as KB heuristic.
    # Practice: values look like 657920 -> ~642 MB, so assume KB when <= 1e9.
    if num_bytes < 10**9:
        kb = float(num_bytes)
        if kb >= 1024 * 1024:
            return f"{kb / (1024 * 1024):.2f} GB"
        if kb >= 1024:
            return f"{kb / 1024:.2f} MB"
        return f"{kb:.0f} KB"
    # Large fallback: treat as bytes
    b = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.2f} {unit}"
        b /= 1024
    return f"{b:.2f} PB"


def _extract_info_hash(magnet: str) -> str:
    if not magnet:
        return ""
    m = _INFO_HASH_RE.search(magnet)
    return m.group(1).lower() if m else ""


async def search(
    keyword: str,
    page: int = 1,
    page_size: int = 30,
    force_refresh: bool = False,
) -> SearchResult:
    keyword = (keyword or "").strip()
    if not keyword:
        return SearchResult(items=[], total=0, source="anime_garden")

    cache_key = response_cache.make_cache_key(
        "animegarden.search",
        keyword=keyword.lower(),
        page=page,
        page_size=page_size,
    )

    async def producer():
        result = await _search_uncached(keyword, page=page, page_size=page_size)
        return result.model_dump(mode="json")

    payload = await response_cache.get_or_set_json(
        cache_key=cache_key,
        cache_group="animegarden.search",
        ttl_seconds=600,
        producer=producer,
        force_refresh=force_refresh,
        allow_stale=True,
    )
    return SearchResult.model_validate(payload or {"items": [], "total": 0, "source": "anime_garden"})


async def _search_uncached(keyword: str, page: int = 1, page_size: int = 30) -> SearchResult:
    await _rate_limit()
    client = _get_client()
    url = f"{settings.ANIME_GARDEN_API_BASE}/resources"
    params = {"page": page, "pageSize": page_size, "search": keyword}
    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("AnimeGarden search failed: %s", e)
        return SearchResult(items=[], total=0, source="anime_garden")

    try:
        data = resp.json()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("AnimeGarden returned non-JSON: %s", e)
        return SearchResult(items=[], total=0, source="anime_garden")

    resources = data.get("resources") or []
    items: list[TorrentItem] = []
    for r in resources:
        title = r.get("title") or ""
        magnet = r.get("magnet") or ""
        info_hash = _extract_info_hash(magnet)
        fansub_obj = r.get("fansub") or {}
        publisher_obj = r.get("publisher") or {}
        size_raw = r.get("size") or 0
        try:
            size_int = int(size_raw)
        except (ValueError, TypeError):
            size_int = 0
        items.append(
            TorrentItem(
                title=title,
                magnet=magnet,
                torrent_url="",  # AnimeGarden doesn't expose direct .torrent
                size=_format_size(size_int),
                date=(r.get("createdAt") or "")[:19].replace("T", " "),
                source="anime_garden",
                info_hash=info_hash,
                fansub=(fansub_obj.get("name") or "").strip() if isinstance(fansub_obj, dict) else "",
                publisher=(publisher_obj.get("name") or "").strip()
                if isinstance(publisher_obj, dict)
                else "",
                detail_url=(r.get("href") or "").strip(),
            )
        )

    return SearchResult(items=items, total=len(items), source="anime_garden")
