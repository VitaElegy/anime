"""动漫花园 (share.dmhy.org) — Chinese fansub BT resource search via RSS."""

import asyncio
import logging
import time
from urllib.parse import quote

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.models import SearchResult, TorrentItem
from app.services.http_client import get_client

logger = logging.getLogger(__name__)

DMHY_BASE = "https://share.dmhy.org"

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


def _parse_size(raw: str) -> str:
    return raw.strip() if raw else ""


def _parse_int(raw: str) -> int:
    try:
        return int(raw.strip().replace(",", ""))
    except (ValueError, AttributeError):
        return 0


async def search_rss(keyword: str, category: str = "2") -> SearchResult:
    """
    Search DMHY via RSS feed.

    Categories: 2=动画, 3=漫画, 4=音乐, 6=日剧, 7=RAW, 9=合集, 31=完结动画
    """
    await _rate_limit()

    url = f"{DMHY_BASE}/topics/rss/rss.xml?keyword={quote(keyword)}"
    if category:
        url += f"&sort_id={category}"

    client = get_client("dmhy")
    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("DMHY RSS request failed: %s", e)
        return SearchResult(items=[], total=0, source="dmhy")

    feed = feedparser.parse(resp.text)
    items: list[TorrentItem] = []

    for entry in feed.entries:
        title = getattr(entry, "title", "")

        # Extract magnet from enclosures or links
        magnet = ""
        torrent_url = ""
        for enc in getattr(entry, "enclosures", []):
            href = enc.get("href", "")
            if href.startswith("magnet:"):
                magnet = href
            elif ".torrent" in href:
                torrent_url = href

        for link in getattr(entry, "links", []):
            href = link.get("href", "")
            if href.startswith("magnet:") and not magnet:
                magnet = href
            elif ".torrent" in href and not torrent_url:
                torrent_url = href

        items.append(
            TorrentItem(
                title=title,
                magnet=magnet,
                torrent_url=torrent_url,
                size="",
                date=getattr(entry, "published", ""),
                source="dmhy",
            )
        )

    return SearchResult(items=items, total=len(items), source="dmhy")


async def search_html(
    keyword: str,
    page: int = 1,
    category: str = "2",
) -> SearchResult:
    """
    Search DMHY via HTML scraping — more detailed than RSS (has size, team info).

    Falls back to RSS on failure.
    """
    await _rate_limit()

    url = f"{DMHY_BASE}/topics/list/page/{page}?keyword={quote(keyword)}"
    if category:
        url += f"&sort_id={category}"

    client = get_client("dmhy")
    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("DMHY HTML request failed: %s — falling back to RSS", e)
        return await search_rss(keyword, category)

    soup = BeautifulSoup(resp.text, "html.parser")
    items: list[TorrentItem] = []

    table = soup.select_one("#topic_list tbody")
    if not table:
        logger.warning("DMHY: no topic_list table found, falling back to RSS")
        return await search_rss(keyword, category)

    for row in table.select("tr"):
        cols = row.select("td")
        if len(cols) < 5:
            continue

        # Column layout: 0=date, 1=category, 2=title+links, 3=magnet, 4=size, 5=team?, ...
        # Title
        title_link = cols[2].select_one("a.arrow-magnet") or cols[2].select_one("a")
        title = ""
        detail_links = cols[2].select("a")
        for a in detail_links:
            href = a.get("href", "")
            if "/topics/" in href and a.get_text(strip=True):
                title = a.get_text(strip=True)
                break
        if not title:
            title = cols[2].get_text(strip=True)[:200]

        # Magnet
        magnet = ""
        torrent_url = ""
        for a in row.select("a"):
            href = a.get("href", "")
            if href.startswith("magnet:"):
                magnet = href
            elif ".torrent" in href:
                torrent_url = href if href.startswith("http") else f"{DMHY_BASE}{href}"

        # Size
        size = ""
        if len(cols) >= 5:
            size = _parse_size(cols[4].get_text() if len(cols) > 4 else cols[3].get_text())

        # Date
        date = cols[0].get_text(strip=True) if cols else ""

        # Fansub team
        team = ""
        team_tag = cols[2].select_one("span.tag a") or (cols[3].select_one("a") if len(cols) > 3 else None)
        if team_tag:
            team = team_tag.get_text(strip=True)

        if title:
            item_title = f"[{team}] {title}" if team and team not in title else title
            items.append(
                TorrentItem(
                    title=item_title,
                    magnet=magnet,
                    torrent_url=torrent_url,
                    size=size,
                    date=date,
                    source="dmhy",
                )
            )

    return SearchResult(items=items, total=len(items), source="dmhy")
