"""Image proxy with local disk cache — accelerates cover/thumbnail loading."""

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response

from app.config import settings
from app.services.http_client import get_client

logger = logging.getLogger(__name__)
router = APIRouter()

# SSRF protection: only allow image proxying from known CDN domains
ALLOWED_IMAGE_DOMAINS = {
    # Bangumi
    "lain.bgm.tv",
    "bangumi.tv",
    "bgm.tv",
    # AniList
    "s4.anilist.co",
    "img.anili.st",
    "anilist.co",
    # Mikan
    "mikanani.me",
    # DMHY
    "share.dmhy.org",
    # AnimeTosho
    "animetosho.org",
    "feed.animetosho.org",
    # Nyaa
    "nyaa.land",
    # SubsPlease
    "subsplease.org",
    # Common CDNs
    "i.imgur.com",
    "cdn.myanimelist.net",
}


def _is_url_allowed(url: str) -> bool:
    """Validate URL against whitelist to prevent SSRF attacks."""
    try:
        parsed = urlparse(url)
        # Must be http or https
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname or ""
        # Block private/internal IPs
        if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            return False
        # Block common internal ranges
        if host.startswith(("10.", "172.16.", "172.17.", "172.18.", "172.19.",
                           "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                           "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                           "172.30.", "172.31.", "192.168.", "169.254.")):
            return False
        # Check domain whitelist
        for allowed in ALLOWED_IMAGE_DOMAINS:
            if host == allowed or host.endswith(f".{allowed}"):
                return True
        return False
    except Exception:
        return False

CACHE_DIR = settings.COVER_CACHE_DIR / "proxy_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_locks: dict[str, asyncio.Lock] = {}
_locks_lock = asyncio.Lock()
_MAX_LOCKS = 500  # Prevent unbounded memory growth


async def _get_url_lock(url: str) -> asyncio.Lock:
    """Per-URL lock to allow parallel downloads of different images."""
    async with _locks_lock:
        # LRU eviction: if too many locks, remove oldest entries
        if len(_locks) > _MAX_LOCKS:
            keys_to_remove = list(_locks.keys())[:_MAX_LOCKS // 2]
            for k in keys_to_remove:
                _locks.pop(k, None)
        if url not in _locks:
            _locks[url] = asyncio.Lock()
        return _locks[url]


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

    if not _is_url_allowed(url):
        logger.warning("SSRF blocked: %s", url[:120])
        return Response(status_code=403, content="URL domain not allowed")

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

        client = get_client("image_proxy")
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
    Limited to 50 URLs per request.
    """
    url_list = [u.strip() for u in urls.split(",") if u.strip()]
    if len(url_list) > 50:
        return Response(status_code=400, content="Maximum 50 URLs per request")

    # Filter out disallowed URLs
    url_list = [u for u in url_list if _is_url_allowed(u)]

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
        client = get_client("image_proxy")
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
