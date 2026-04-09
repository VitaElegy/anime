"""Comicat (漫猫动漫 comicat.org) — Chinese fansub BT resource RSS site."""

import asyncio
import logging
import re
import time
from urllib.parse import quote

import feedparser
import httpx

from app.models import SearchResult, TorrentItem
from app.services.http_client import get_client

logger = logging.getLogger(__name__)

COMICAT_BASE = "https://comicat.org"

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


async def search_rss(keyword: str = "") -> SearchResult:
    """
    Search Comicat via RSS feed.

    Comicat RSS URL pattern:
    - Latest: /rss.xml
    - Search: /search.php?keyword=KEYWORD (HTML) — we use RSS + client-side filter

    Since Comicat doesn't have a search RSS endpoint,
    we fetch the main RSS and filter client-side by keyword.
    For keyword search, we use the HTML search page.
    """
    await _rate_limit()

    if keyword:
        # Comicat has no search RSS; use HTML search and parse
        return await _search_html(keyword)

    # No keyword: fetch latest RSS
    url = f"{COMICAT_BASE}/rss.xml"
    client = get_client("default")

    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Comicat RSS fetch failed: %s", e)
        return SearchResult(items=[], total=0, source="comicat")

    feed = feedparser.parse(resp.text)
    items: list[TorrentItem] = []

    for entry in feed.entries:
        title = getattr(entry, "title", "")
        link = getattr(entry, "link", "")

        # Extract magnet from enclosures
        magnet = ""
        torrent_url = ""
        for enc in getattr(entry, "enclosures", []):
            href = enc.get("href", "")
            if href.startswith("magnet:"):
                magnet = href
            elif ".torrent" in href:
                torrent_url = href

        # Also check links
        for lnk in getattr(entry, "links", []):
            href = lnk.get("href", "")
            if href.startswith("magnet:") and not magnet:
                magnet = href
            elif ".torrent" in href and not torrent_url:
                torrent_url = href if href.startswith("http") else f"{COMICAT_BASE}{href}"

        # Size from description
        size = ""
        desc = getattr(entry, "summary", "") or getattr(entry, "description", "")
        size_match = re.search(r'(\d+\.?\d*\s*(?:GB|GiB|MB|MiB|TB|TiB))', desc, re.IGNORECASE)
        if size_match:
            size = size_match.group(1)

        if title:
            items.append(
                TorrentItem(
                    title=title,
                    magnet=magnet,
                    torrent_url=torrent_url or link,
                    size=size,
                    date=getattr(entry, "published", ""),
                    source="comicat",
                )
            )

    return SearchResult(items=items, total=len(items), source="comicat")


async def _search_html(keyword: str) -> SearchResult:
    """Search Comicat via HTML search page and parse results."""
    await _rate_limit()

    url = f"{COMICAT_BASE}/search.php?keyword={quote(keyword)}"
    client = get_client("default")

    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Comicat HTML search failed: %s — falling back to RSS filter", e)
        return await _rss_filter(keyword)

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    items: list[TorrentItem] = []

    # Comicat search results are in table rows
    for row in soup.select("tr"):
        cells = row.select("td")
        if len(cells) < 3:
            continue

        # Find title link
        title_link = None
        for a in row.select("a"):
            href = a.get("href", "")
            if "/show-" in href and a.get_text(strip=True):
                title_link = a
                break

        if not title_link:
            continue

        title = title_link.get_text(strip=True)
        detail_url = title_link.get("href", "")
        if detail_url and not detail_url.startswith("http"):
            detail_url = f"{COMICAT_BASE}/{detail_url}"

        # Find magnet/torrent links
        magnet = ""
        torrent_url = ""
        for a in row.select("a"):
            href = a.get("href", "")
            if href.startswith("magnet:"):
                magnet = href
            elif ".torrent" in href:
                torrent_url = href if href.startswith("http") else f"{COMICAT_BASE}/{href}"

        # Size and date from cells
        size = ""
        date = ""
        for cell in cells:
            text = cell.get_text(strip=True)
            if re.match(r'\d+\.\d+\s*(GB|MB|GiB|MiB)', text, re.IGNORECASE):
                size = text
            elif re.match(r'\d{4}[-/]\d{2}[-/]\d{2}', text):
                date = text

        if title:
            items.append(
                TorrentItem(
                    title=title,
                    magnet=magnet,
                    torrent_url=torrent_url or detail_url,
                    size=size,
                    date=date,
                    source="comicat",
                )
            )

    return SearchResult(items=items, total=len(items), source="comicat")


async def _rss_filter(keyword: str) -> SearchResult:
    """Fallback: fetch RSS and filter by keyword client-side."""
    result = await search_rss("")
    keyword_lower = keyword.lower()
    filtered = [item for item in result.items if keyword_lower in item.title.lower()]
    return SearchResult(items=filtered, total=len(filtered), source="comicat")
