"""Image proxy with local disk cache — accelerates cover/thumbnail loading."""

import asyncio
import hashlib
import logging
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

CACHE_DIR = settings.COVER_CACHE_DIR / "proxy_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_client: httpx.AsyncClient | None = None
_locks: dict[str, asyncio.Lock] = {}
_locks_lock = asyncio.Lock()


async def _get_url_lock(url: str) -> asyncio.Lock:
    """Per-URL lock to allow parallel downloads of different images."""
    async with _locks_lock:
        if url not in _locks:
            _locks[url] = asyncio.Lock()
        return _locks[url]


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Referer": "https://bgm.tv/",
            },
            follow_redirects=True,
        )
    return _client


def _url_to_cache_path(url: str) -> Path:
    """Deterministic cache filename from URL hash."""
    h = hashlib.md5(url.encode()).hexdigest()
    # Keep original extension if possible
    ext = "jpg"
    for e in ("png", "webp", "gif", "jpeg"):
        if f".{e}" in url.lower():
            ext = e
            break
    return CACHE_DIR / f"{h}.{ext}"


def _content_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/jpeg")


@router.get("/proxy", summary="Proxy and cache external image")
async def proxy_image(url: str = Query(..., description="External image URL to proxy")):
    """
    Proxy an external image URL through our server with local disk cache.
    First request downloads and caches; subsequent requests serve from disk instantly.
    """
    if not url:
        return Response(status_code=400, content="Missing url parameter")

    cache_path = _url_to_cache_path(url)

    # Cache hit — serve immediately (check all possible extensions)
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        alt = cache_path.with_suffix(ext)
        if alt.exists() and alt.stat().st_size > 0:
            return FileResponse(
                alt,
                media_type=_content_type(alt),
                headers={"X-Cache": "HIT", "Cache-Control": "public, max-age=86400"},
            )

    # Cache miss — download with per-URL lock
    url_lock = await _get_url_lock(url)
    async with url_lock:
        # Double-check after acquiring lock (also check alternate extensions)
        for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            alt = cache_path.with_suffix(ext)
            if alt.exists() and alt.stat().st_size > 0:
                return FileResponse(
                    alt,
                    media_type=_content_type(alt),
                    headers={"X-Cache": "HIT", "Cache-Control": "public, max-age=86400"},
                )

        client = _get_client()
        try:
            resp = await client.get(url)
            resp.raise_for_status()

            # Determine actual extension from content-type and save with correct suffix
            ct = resp.headers.get("content-type", "image/jpeg")
            if "png" in ct:
                actual_path = cache_path.with_suffix(".png")
            elif "webp" in ct:
                actual_path = cache_path.with_suffix(".webp")
            elif "gif" in ct:
                actual_path = cache_path.with_suffix(".gif")
            else:
                actual_path = cache_path.with_suffix(".jpg")

            actual_path.write_bytes(resp.content)
            logger.info("Cached image: %s -> %s (%d bytes)", url[:80], actual_path.name, len(resp.content))

            return FileResponse(
                actual_path,
                media_type=ct,
                headers={"X-Cache": "MISS", "Cache-Control": "public, max-age=86400"},
            )
        except Exception as e:
            logger.warning("Failed to proxy image %s: %s", url[:80], e)
            return Response(status_code=502, content=f"Failed to fetch image: {e}")


@router.get("/batch_prefetch", summary="Prefetch multiple images in background")
async def batch_prefetch(urls: str = Query(..., description="Comma-separated image URLs")):
    """
    Trigger background prefetch for multiple images.
    Returns immediately with count of cached/pending.
    """
    url_list = [u.strip() for u in urls.split(",") if u.strip()]

    cached = 0
    pending = 0
    for url in url_list:
        cache_path = _url_to_cache_path(url)
        if cache_path.exists() and cache_path.stat().st_size > 0:
            cached += 1
        else:
            pending += 1

    # Fire-and-forget background downloads for uncached
    async def _prefetch():
        client = _get_client()
        for url in url_list:
            cache_path = _url_to_cache_path(url)
            if cache_path.exists() and cache_path.stat().st_size > 0:
                continue
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                cache_path.write_bytes(resp.content)
            except Exception:
                pass
            await asyncio.sleep(0.1)

    asyncio.create_task(_prefetch())

    return {"total": len(url_list), "cached": cached, "pending": pending}
