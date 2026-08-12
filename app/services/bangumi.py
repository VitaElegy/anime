"""Bangumi API service — anime metadata, search, cover caching.

Uses Bangumi v0 API endpoints:
- POST /v0/search/subjects   (search, returns rich records incl. name_cn/rating)
- GET  /v0/subjects/{id}     (detail, returns full `infobox` for staff/themes)
"""

import asyncio
import logging
import re
import time
from pathlib import Path

import httpx

from app.config import settings
from app.models import AnimeMetadata, AnimeMetadataFull, StaffMember, ThemeSong
from app.services import response_cache

logger = logging.getLogger(__name__)

_last_request_time: float = 0
_lock = asyncio.Lock()

# In-memory cache: subject_id -> AnimeMetadata
_metadata_cache: dict[int, AnimeMetadata] = {}

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=30,
            headers={
                # Bangumi 官方建议自定义 User-Agent
                "User-Agent": "NicoTracker/1.0 (https://github.com/) anime-downloader",
                "Accept": "application/json",
            },
            follow_redirects=True,
        )
    return _client


async def _rate_limit():
    global _last_request_time
    async with _lock:
        now = time.monotonic()
        wait = settings.BANGUMI_RATE_LIMIT - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time = time.monotonic()


async def search(keyword: str, limit: int = 25, force_refresh: bool = False) -> list[AnimeMetadata]:
    cache_key = response_cache.make_cache_key(
        "bangumi.search_v0",
        keyword=keyword.strip().lower(),
        limit=limit,
    )

    async def producer():
        return [item.model_dump(mode="json") for item in await _search_uncached(keyword, limit=limit)]

    payload = await response_cache.get_or_set_json(
        cache_key=cache_key,
        cache_group="bangumi.search",
        ttl_seconds=21600,
        producer=producer,
        force_refresh=force_refresh,
        allow_stale=True,
    )
    return [AnimeMetadata.model_validate(item) for item in (payload or [])]


async def _search_uncached(keyword: str, limit: int = 25) -> list[AnimeMetadata]:
    """Search Bangumi (v0) for anime by keyword (type=2 = Animation)."""
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    await _rate_limit()
    client = _get_client()
    url = f"{settings.BANGUMI_API_BASE}/v0/search/subjects"
    body = {"keyword": keyword, "filter": {"type": [2]}}

    try:
        resp = await client.post(url, params={"limit": limit}, json=body)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Bangumi v0 search failed, falling back to legacy: %s", e)
        return await _search_uncached_legacy(keyword, limit)

    try:
        data = resp.json()
    except Exception:
        return []

    results: list[AnimeMetadata] = []
    for item in data.get("data", []) or []:
        images = item.get("image") or item.get("images") or {}
        if isinstance(images, str):
            cover_url = images
        else:
            cover_url = (
                images.get("large")
                or images.get("common")
                or images.get("medium")
                or images.get("small")
                or ""
            )
        rating = item.get("rating") or {}
        results.append(
            AnimeMetadata(
                id=item.get("id", 0),
                name_cn=item.get("name_cn", "") or "",
                name=item.get("name", "") or "",
                summary=(item.get("summary", "") or "")[:500],
                score=float(rating.get("score") or 0.0),
                cover_url=cover_url,
            )
        )
    return results


async def _search_uncached_legacy(keyword: str, limit: int = 25) -> list[AnimeMetadata]:
    """Fallback to Bangumi legacy search if v0 is unavailable."""
    await _rate_limit()
    client = _get_client()
    url = f"{settings.BANGUMI_API_BASE}/search/subject/{keyword}"

    try:
        resp = await client.get(url, params={"type": 2, "responseGroup": "small", "max_results": limit})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Bangumi legacy search failed: %s", e)
        return []

    data = resp.json()
    results: list[AnimeMetadata] = []

    for item in data.get("list", []):
        images = item.get("images", {})
        cover_url = images.get("large", "") or images.get("medium", "") or images.get("small", "")
        results.append(
            AnimeMetadata(
                id=item.get("id", 0),
                name_cn=item.get("name_cn", ""),
                name=item.get("name", ""),
                summary=item.get("summary", "")[:500],
                score=item.get("rating", {}).get("score", 0.0) if item.get("rating") else 0.0,
                cover_url=cover_url,
            )
        )

    return results


async def get_detail(subject_id: int, force_refresh: bool = False) -> AnimeMetadata | None:
    """Get detailed metadata for a single anime (lightweight, back-compat)."""
    if subject_id in _metadata_cache and not force_refresh:
        return _metadata_cache[subject_id]

    cache_key = response_cache.make_cache_key("bangumi.detail", subject_id=subject_id)

    async def producer():
        meta = await _get_detail_uncached(subject_id)
        return meta.model_dump(mode="json") if meta else None

    payload = await response_cache.get_or_set_json(
        cache_key=cache_key,
        cache_group="bangumi.detail",
        ttl_seconds=86400,
        producer=producer,
        force_refresh=force_refresh,
        allow_stale=True,
    )
    if payload is None:
        return None

    meta = AnimeMetadata.model_validate(payload)
    _metadata_cache[subject_id] = meta
    return meta


async def _get_detail_uncached(subject_id: int) -> AnimeMetadata | None:
    await _rate_limit()
    client = _get_client()
    url = f"{settings.BANGUMI_API_BASE}/v0/subjects/{subject_id}"

    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Bangumi detail fetch failed for %d: %s", subject_id, e)
        return None

    data = resp.json()
    images = data.get("images", {})
    cover_url = images.get("large", "") or images.get("medium", "") or images.get("small", "")

    return AnimeMetadata(
        id=data.get("id", subject_id),
        name_cn=data.get("name_cn", ""),
        name=data.get("name", ""),
        summary=(data.get("summary", "") or "")[:1000],
        score=data.get("rating", {}).get("score", 0.0) if data.get("rating") else 0.0,
        cover_url=cover_url,
    )


# ---------------------------------------------------------------------------
# Full metadata — v0 subject w/ infobox → structured staff / theme songs / tags
# ---------------------------------------------------------------------------

_STAFF_KEYS = {
    "导演": "导演",
    "原作": "原作",
    "系列构成": "系列构成",
    "脚本": "脚本",
    "人物设定": "人物设定",
    "音乐": "音乐",
    "动画制作": "动画制作",
    "美术监督": "美术监督",
    "音响监督": "音响监督",
    "制片人": "制片人",
    "总作画监督": "总作画监督",
}

_THEME_KEY_RE = re.compile(r"^(op|ed|sp|主题|insert)", re.IGNORECASE)


def _infobox_flatten(entry_value) -> list[str]:
    """Infobox value may be str or list of {v: str} dicts."""
    if isinstance(entry_value, str):
        return [entry_value]
    if isinstance(entry_value, list):
        out = []
        for it in entry_value:
            if isinstance(it, dict):
                v = it.get("v") or it.get("k") or ""
                if v:
                    out.append(str(v))
            elif isinstance(it, str):
                out.append(it)
        return out
    return []


async def get_full_detail(subject_id: int, force_refresh: bool = False) -> AnimeMetadataFull | None:
    """Return the rich metadata object, including infobox-derived staff and OP/ED."""
    cache_key = response_cache.make_cache_key("bangumi.detail_full", subject_id=subject_id)

    async def producer():
        data = await _get_full_detail_uncached(subject_id)
        return data.model_dump(mode="json") if data else None

    payload = await response_cache.get_or_set_json(
        cache_key=cache_key,
        cache_group="bangumi.detail_full",
        ttl_seconds=86400,
        producer=producer,
        force_refresh=force_refresh,
        allow_stale=True,
    )
    if not payload:
        return None
    return AnimeMetadataFull.model_validate(payload)


async def _get_full_detail_uncached(subject_id: int) -> AnimeMetadataFull | None:
    await _rate_limit()
    client = _get_client()
    url = f"{settings.BANGUMI_API_BASE}/v0/subjects/{subject_id}"

    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Bangumi full detail fetch failed for %d: %s", subject_id, e)
        return None

    data = resp.json()
    images = data.get("images") or {}
    cover_url = (
        images.get("large") or images.get("common") or images.get("medium") or images.get("small") or ""
    )
    rating = data.get("rating") or {}

    # Parse infobox
    staff: list[StaffMember] = []
    theme_songs: list[ThemeSong] = []
    aliases: list[str] = []
    official_site = ""
    air_weekday = ""

    for entry in data.get("infobox", []) or []:
        key = str(entry.get("key") or "").strip()
        if not key:
            continue
        values = _infobox_flatten(entry.get("value"))
        if not values:
            continue

        # Staff
        if key in _STAFF_KEYS:
            for v in values:
                staff.append(StaffMember(role=_STAFF_KEYS[key], name=v.strip()))
            continue

        # Aliases
        if key in ("别名", "其他", "英文名", "罗马字"):
            for v in values:
                if v and v not in aliases:
                    aliases.append(v.strip())
            continue

        # Official site
        if key in ("官方网站", "官网", "Website"):
            official_site = values[0].strip()
            continue

        # Broadcast day
        if key in ("放送星期", "播放星期", "放送"):
            air_weekday = values[0].strip()
            continue

        # Theme songs
        if _THEME_KEY_RE.match(key):
            kind = key.upper()
            for v in values:
                # Typical format: "Yuusha" or "Yuusha / YOASOBI"
                title = v.strip()
                artist = ""
                if "/" in title:
                    parts = [p.strip() for p in title.split("/", 1)]
                    title = parts[0]
                    artist = parts[1] if len(parts) > 1 else ""
                theme_songs.append(ThemeSong(kind=kind, title=title, artist=artist))
            continue

    # Tags
    tags = []
    for t in data.get("tags", []) or []:
        name = (t.get("name") if isinstance(t, dict) else str(t) or "").strip()
        if name:
            tags.append(name)

    meta_tags = list(data.get("meta_tags") or [])

    return AnimeMetadataFull(
        id=data.get("id", subject_id),
        name_cn=data.get("name_cn", "") or "",
        name=data.get("name", "") or "",
        summary=(data.get("summary", "") or "").strip(),
        score=float(rating.get("score") or 0.0),
        score_count=int(rating.get("total") or 0),
        rank=int(rating.get("rank") or 0),
        cover_url=cover_url,
        air_date=str(data.get("date") or ""),
        air_weekday=air_weekday,
        total_episodes=int(data.get("total_episodes") or data.get("eps") or 0),
        tags=tags[:30],
        meta_tags=meta_tags,
        staff=staff,
        theme_songs=theme_songs,
        official_site=official_site,
        aliases=aliases,
    )


async def get_cover(subject_id: int) -> Path | None:
    """Download cover image to local cache. Returns local file path.

    If already cached on disk, returns immediately.
    """
    cache_dir = settings.COVER_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Check for existing cached files
    for ext in ("jpg", "png", "webp"):
        cached = cache_dir / f"{subject_id}.{ext}"
        if cached.exists():
            return cached

    # Get cover URL
    meta = await get_detail(subject_id)
    if not meta or not meta.cover_url:
        return None

    # Download
    await _rate_limit()
    client = _get_client()

    try:
        resp = await client.get(meta.cover_url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Failed to download cover for %d: %s", subject_id, e)
        return None

    # Determine extension from content-type
    content_type = resp.headers.get("content-type", "image/jpeg")
    ext = "jpg"
    if "png" in content_type:
        ext = "png"
    elif "webp" in content_type:
        ext = "webp"

    local_path = cache_dir / f"{subject_id}.{ext}"
    local_path.write_bytes(resp.content)

    # Update cache entry
    if subject_id in _metadata_cache:
        _metadata_cache[subject_id].cover_local = str(local_path)

    logger.info("Cached cover for subject %d -> %s", subject_id, local_path)
    return local_path
