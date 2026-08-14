"""Image proxy cache helpers."""

import asyncio
import hashlib
import logging
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

CACHE_DIR = settings.COVER_CACHE_DIR / "proxy_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_client: httpx.AsyncClient | None = None
_lock = asyncio.Lock()


def get_cache_path(url: str) -> Path:
    """Deterministic cache filename from URL hash."""
    hashed = hashlib.md5(url.encode("utf-8")).hexdigest()
    ext = "jpg"
    for candidate in ("png", "webp", "gif", "jpeg"):
        if f".{candidate}" in url.lower():
            ext = candidate
            break
    return CACHE_DIR / f"{hashed}.{ext}"


def content_type(path: Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "image/jpeg")


def is_cached(url: str) -> bool:
    path = get_cache_path(url)
    return path.exists() and path.stat().st_size > 0


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        kwargs: dict = {
            "timeout": 20,
            "headers": {"User-Agent": "NicoTracker/1.0"},
            "follow_redirects": True,
        }
        if settings.HTTP_PROXY:
            kwargs["proxy"] = settings.HTTP_PROXY
        _client = httpx.AsyncClient(**kwargs)
    return _client


async def cache_image(url: str) -> Path | None:
    if not url:
        return None

    path = get_cache_path(url)
    if path.exists() and path.stat().st_size > 0:
        return path

    async with _lock:
        if path.exists() and path.stat().st_size > 0:
            return path

        client = _get_client()
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to cache image %s: %s", url[:80], exc)
            return None

        media_type = resp.headers.get("content-type", "image/jpeg")
        if "png" in media_type:
            path = path.with_suffix(".png")
        elif "webp" in media_type:
            path = path.with_suffix(".webp")
        elif "gif" in media_type:
            path = path.with_suffix(".gif")

        path.write_bytes(resp.content)
        logger.info("Cached image: %s -> %s (%d bytes)", url[:80], path.name, len(resp.content))
        return path


async def prefetch_images(urls: list[str]):
    for url in urls:
        await cache_image(url)
        await asyncio.sleep(0.05)
