"""Image proxy with local disk cache — accelerates cover/thumbnail loading."""

import asyncio
import logging

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response

from app.services import image_cache

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/proxy", summary="Proxy and cache external image")
async def proxy_image(url: str = Query(..., description="External image URL to proxy")):
    """
    Proxy an external image URL through our server with local disk cache.
    First request downloads and caches; subsequent requests serve from disk instantly.
    """
    if not url:
        return Response(status_code=400, content="Missing url parameter")

    cache_path = image_cache.get_cache_path(url)
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return FileResponse(
            cache_path,
            media_type=image_cache.content_type(cache_path),
            headers={"X-Cache": "HIT", "Cache-Control": "public, max-age=86400"},
        )

    actual_path = await image_cache.cache_image(url)
    if actual_path is None:
        logger.warning("Failed to proxy image %s", url[:80])
        return Response(status_code=502, content="Failed to fetch image")

    return FileResponse(
        actual_path,
        media_type=image_cache.content_type(actual_path),
        headers={"X-Cache": "MISS", "Cache-Control": "public, max-age=86400"},
    )


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
        if image_cache.is_cached(url):
            cached += 1
        else:
            pending += 1

    async def _prefetch():
        await image_cache.prefetch_images(url_list)

    asyncio.create_task(_prefetch())

    return {"total": len(url_list), "cached": cached, "pending": pending}
