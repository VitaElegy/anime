"""蜜柑计划 (mikanani.me) — Chinese anime RSS subscription and fansub aggregator."""

import asyncio
import logging
import re
import time
from urllib.parse import quote

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.models import SearchResult, TorrentItem
from app.services.http_client import get_client

logger = logging.getLogger(__name__)

MIKAN_BASE = "https://mikanani.me"

_last_request_time: float = 0
_lock = asyncio.Lock()


async def _rate_limit():
    global _last_request_time
    async with _lock:
        now = time.monotonic()
        wait = 1.0 - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time = time.monotonic()


async def search_rss(keyword: str) -> SearchResult:
    """
    Search Mikan via RSS. Mikan's RSS supports keyword search.
    URL pattern: /RSS/Search?searchstr=KEYWORD
    """
    await _rate_limit()

    url = f"{MIKAN_BASE}/RSS/Search?searchstr={quote(keyword)}"
    client = get_client("mikan")

    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Mikan RSS request failed: %s", e)
        return SearchResult(items=[], total=0, source="mikan")

    feed = feedparser.parse(resp.text)
    items: list[TorrentItem] = []

    for entry in feed.entries:
        title = getattr(entry, "title", "")

        magnet = ""
        torrent_url = ""
        for link in getattr(entry, "links", []):
            href = link.get("href", "")
            if href.startswith("magnet:"):
                magnet = href
            elif ".torrent" in href:
                torrent_url = href if href.startswith("http") else f"{MIKAN_BASE}{href}"

        # Also check enclosures
        for enc in getattr(entry, "enclosures", []):
            href = enc.get("href", "")
            if ".torrent" in href and not torrent_url:
                torrent_url = href if href.startswith("http") else f"{MIKAN_BASE}{href}"

        # Try to extract size from description
        size = ""
        desc = getattr(entry, "summary", "") or getattr(entry, "description", "")
        size_match = re.search(r'(\d+\.?\d*\s*(?:GB|GiB|MB|MiB|TB|TiB))', desc, re.IGNORECASE)
        if size_match:
            size = size_match.group(1)

        items.append(
            TorrentItem(
                title=title,
                magnet=magnet,
                torrent_url=torrent_url,
                size=size,
                date=getattr(entry, "published", ""),
                source="mikan",
            )
        )

    return SearchResult(items=items, total=len(items), source="mikan")


async def get_current_season_rss() -> SearchResult:
    """
    Get Mikan's main RSS feed — current season all releases.
    URL: /RSS/Classic
    """
    await _rate_limit()

    url = f"{MIKAN_BASE}/RSS/Classic"
    client = get_client("mikan")

    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Mikan season RSS failed: %s", e)
        return SearchResult(items=[], total=0, source="mikan")

    feed = feedparser.parse(resp.text)
    items: list[TorrentItem] = []

    for entry in feed.entries:
        title = getattr(entry, "title", "")
        magnet = ""
        torrent_url = ""

        for link in getattr(entry, "links", []):
            href = link.get("href", "")
            if href.startswith("magnet:"):
                magnet = href
            elif ".torrent" in href:
                torrent_url = href if href.startswith("http") else f"{MIKAN_BASE}{href}"

        for enc in getattr(entry, "enclosures", []):
            href = enc.get("href", "")
            if ".torrent" in href and not torrent_url:
                torrent_url = href if href.startswith("http") else f"{MIKAN_BASE}{href}"

        items.append(
            TorrentItem(
                title=title,
                magnet=magnet,
                torrent_url=torrent_url,
                size="",
                date=getattr(entry, "published", ""),
                source="mikan",
            )
        )

    return SearchResult(items=items, total=len(items), source="mikan")
