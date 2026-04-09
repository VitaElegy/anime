"""Nyaa.land search service — HTML scraping with RSS fallback."""

import asyncio
import logging
import time
from urllib.parse import quote, urljoin

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.models import SearchResult, TorrentItem
from app.services.http_client import get_client

logger = logging.getLogger(__name__)

_last_request_time: float = 0
_lock = asyncio.Lock()


async def _rate_limit():
    """Enforce minimum interval between Nyaa requests."""
    global _last_request_time
    async with _lock:
        now = time.monotonic()
        wait = settings.NYAA_RATE_LIMIT - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time = time.monotonic()


def _parse_size(raw: str) -> str:
    """Normalize size string."""
    return raw.strip() if raw else ""


def _parse_int(raw: str) -> int:
    try:
        return int(raw.strip().replace(",", ""))
    except (ValueError, AttributeError):
        return 0


async def search_html(
    keyword: str,
    page: int = 1,
    filter_: int = 0,
    category: str = "1_0",
) -> SearchResult:
    """
    Search Nyaa via HTML scraping.

    Args:
        keyword: Search query.
        page: Page number (1-indexed).
        filter_: 0=No filter, 1=No remakes, 2=Trusted only.
        category: Nyaa category code (1_0=Anime, 1_2=English, 1_3=Non-English, 1_4=Raw).
    """
    await _rate_limit()

    url = f"{settings.NYAA_BASE_URL}/?f={filter_}&c={category}&q={quote(keyword)}&p={page}"
    client = get_client("nyaa")

    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Nyaa HTML request failed: %s — falling back to RSS", e)
        return await search_rss(keyword, category)

    soup = BeautifulSoup(resp.text, "html.parser")
    items: list[TorrentItem] = []

    table = soup.select_one("table.torrent-list tbody")
    if not table:
        logger.warning("No torrent table found on page, trying RSS fallback")
        return await search_rss(keyword, category)

    for row in table.select("tr"):
        cols = row.select("td")
        if len(cols) < 8:
            continue

        # Column indices: 0=category, 1=name, 2=links, 3=size, 4=date, 5=seeders, 6=leechers, 7=downloads
        title_link = cols[1].select_one("a:last-of-type")
        title = title_link.get_text(strip=True) if title_link else ""
        detail_href = title_link["href"] if title_link and title_link.has_attr("href") else ""

        # Magnet and torrent links
        magnet = ""
        torrent_url = ""
        for a in cols[2].select("a"):
            href = a.get("href", "")
            if href.startswith("magnet:"):
                magnet = href
            elif href.endswith(".torrent") or "/download/" in href:
                torrent_url = urljoin(settings.NYAA_BASE_URL, href)

        items.append(
            TorrentItem(
                title=title,
                magnet=magnet,
                torrent_url=torrent_url,
                size=_parse_size(cols[3].get_text()),
                seeders=_parse_int(cols[5].get_text()),
                leechers=_parse_int(cols[6].get_text()),
                date=cols[4].get_text(strip=True),
                source="nyaa",
            )
        )

    # Try to get total from pagination info
    pagination = soup.select_one("ul.pagination")
    total = len(items)
    if pagination:
        # Rough estimate — Nyaa shows 75 per page
        last_page_link = pagination.select("a")
        if last_page_link:
            total = max(total, len(items))  # can't easily get exact total

    return SearchResult(items=items, total=len(items), source="nyaa")


async def search_rss(
    keyword: str,
    category: str = "1_0",
) -> SearchResult:
    """Search Nyaa via RSS feed (fallback)."""
    await _rate_limit()

    url = f"{settings.NYAA_BASE_URL}/?page=rss&c={category}&q={quote(keyword)}"
    client = get_client("nyaa")

    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Nyaa RSS request also failed: %s", e)
        return SearchResult(items=[], total=0, source="nyaa")

    feed = feedparser.parse(resp.text)
    items: list[TorrentItem] = []

    for entry in feed.entries:
        # feedparser fields from nyaa RSS
        magnet = ""
        torrent_url = ""
        for link in getattr(entry, "links", []):
            href = link.get("href", "")
            if href.startswith("magnet:"):
                magnet = href
            elif href.endswith(".torrent") or "/download/" in href:
                torrent_url = href

        # nyaa RSS uses nyaa:seeders, nyaa:leechers, nyaa:size as namespaced elements
        seeders = _parse_int(getattr(entry, "nyaa_seeders", "0"))
        leechers = _parse_int(getattr(entry, "nyaa_leechers", "0"))
        size = getattr(entry, "nyaa_size", "")

        items.append(
            TorrentItem(
                title=getattr(entry, "title", ""),
                magnet=magnet,
                torrent_url=torrent_url or getattr(entry, "link", ""),
                size=size,
                seeders=seeders,
                leechers=leechers,
                date=getattr(entry, "published", ""),
                source="nyaa",
            )
        )

    return SearchResult(items=items, total=len(items), source="nyaa")
