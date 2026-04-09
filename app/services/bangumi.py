"""Bangumi API service — anime metadata, search, cover caching."""

import asyncio
import logging
import time
from pathlib import Path

import httpx

from app.config import settings
from app.models import AnimeMetadata
from app.services.http_client import get_client

logger = logging.getLogger(__name__)

_last_request_time: float = 0
_lock = asyncio.Lock()

# In-memory cache: subject_id -> AnimeMetadata (LRU-like, max 2000 entries)
_metadata_cache: dict[int, AnimeMetadata] = {}
_METADATA_CACHE_MAX = 2000


async def _rate_limit():
    global _last_request_time
    async with _lock:
        now = time.monotonic()
        wait = settings.BANGUMI_RATE_LIMIT - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time = time.monotonic()


async def search(keyword: str, limit: int = 25) -> list[AnimeMetadata]:
    """
    Search Bangumi for anime by keyword.

    type=2 means Animation.
    """
    await _rate_limit()
    client = get_client("bangumi")
    url = f"{settings.BANGUMI_API_BASE}/search/subject/{keyword}"

    try:
        resp = await client.get(url, params={"type": 2, "responseGroup": "small", "max_results": limit})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Bangumi search failed: %s", e)
        return []

    data = resp.json()
    results: list[AnimeMetadata] = []

    for item in data.get("list", []):
        images = item.get("images", {})
        cover_url = images.get("large", "") or images.get("medium", "") or images.get("small", "")

        meta = AnimeMetadata(
            id=item.get("id", 0),
            name_cn=item.get("name_cn", ""),
            name=item.get("name", ""),
            summary=item.get("summary", "")[:500],
            score=item.get("rating", {}).get("score", 0.0) if item.get("rating") else 0.0,
            cover_url=cover_url,
        )
        results.append(meta)

    return results


async def get_detail(subject_id: int) -> AnimeMetadata | None:
    """Get detailed metadata for a single anime."""
    # Check cache first
    if subject_id in _metadata_cache:
        return _metadata_cache[subject_id]

    await _rate_limit()
    client = get_client("bangumi")
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

    meta = AnimeMetadata(
        id=data.get("id", subject_id),
        name_cn=data.get("name_cn", ""),
        name=data.get("name", ""),
        summary=(data.get("summary", "") or "")[:1000],
        score=data.get("rating", {}).get("score", 0.0) if data.get("rating") else 0.0,
        cover_url=cover_url,
    )

    # Evict oldest entries if cache is full
    if len(_metadata_cache) >= _METADATA_CACHE_MAX:
        keys_to_remove = list(_metadata_cache.keys())[:_METADATA_CACHE_MAX // 2]
        for k in keys_to_remove:
            _metadata_cache.pop(k, None)

    _metadata_cache[subject_id] = meta
    return meta


async def get_cover(subject_id: int) -> Path | None:
    """
    Download cover image to local cache. Returns local file path.

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
    client = get_client("bangumi")

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
