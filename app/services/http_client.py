"""Shared httpx AsyncClient factory — replaces per-module _get_client() singletons.

Usage:
    from app.services.http_client import get_client
    client = get_client("nyaa")  # or "bangumi", "anilist", etc.

All clients are tracked and closed on app shutdown via `close_all_clients()`.
"""

import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_clients: dict[str, httpx.AsyncClient] = {}
_lock = asyncio.Lock()

# Default client configurations per service
_CLIENT_CONFIGS: dict[str, dict] = {
    "default": {
        "timeout": 30,
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        },
        "follow_redirects": True,
    },
    "bangumi": {
        "timeout": 30,
        "headers": {
            "User-Agent": "NicoTracker/1.0",
            "Accept": "application/json",
        },
        "follow_redirects": True,
    },
    "anilist": {
        "timeout": 15,
        "headers": {
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    },
    "image_proxy": {
        "timeout": 20,
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Referer": "https://bgm.tv/",
        },
        "follow_redirects": True,
    },
}

# Services that need proxy support
_PROXY_SERVICES = {"nyaa", "dmhy", "mikan", "animetosho", "schedule"}


def get_client(name: str = "default") -> httpx.AsyncClient:
    """Get or create a named httpx AsyncClient. Thread-safe via lazy init."""
    existing = _clients.get(name)
    if existing is not None and not existing.is_closed:
        return existing

    config = _CLIENT_CONFIGS.get(name, _CLIENT_CONFIGS["default"]).copy()

    # Apply proxy for relevant services
    if name in _PROXY_SERVICES and settings.HTTP_PROXY:
        config["proxy"] = settings.HTTP_PROXY

    client = httpx.AsyncClient(**config)
    _clients[name] = client
    return client


async def close_all_clients():
    """Close all managed clients. Call during app shutdown."""
    for name, client in list(_clients.items()):
        if not client.is_closed:
            try:
                await client.aclose()
                logger.info("Closed httpx client: %s", name)
            except Exception as e:
                logger.warning("Failed to close client %s: %s", name, e)
    _clients.clear()
