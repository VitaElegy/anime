"""SubsPlease RSS service."""

import logging

import feedparser
import httpx

from app.config import settings
from app.models import SearchResult, TorrentItem

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": "AnimeDownloader/1.0"},
            follow_redirects=True,
        )
    return _client


async def search(
    keyword: str = "",
    quality: int = 1080,
) -> SearchResult:
    """
    Fetch and filter SubsPlease RSS.

    Args:
        keyword: Filter results by title (case-insensitive substring match). Empty = all.
        quality: Video quality — 1080, 720, or 480.
    """
    url = f"https://subsplease.org/rss/?r={quality}"
    client = _get_client()

    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("SubsPlease RSS fetch failed: %s", e)
        return SearchResult(items=[], total=0, source="subsplease")

    feed = feedparser.parse(resp.text)
    items: list[TorrentItem] = []
    keyword_lower = keyword.lower()

    for entry in feed.entries:
        title = getattr(entry, "title", "")

        # Filter by keyword if provided
        if keyword_lower and keyword_lower not in title.lower():
            continue

        # SubsPlease RSS typically has magnet in link
        link = getattr(entry, "link", "")
        magnet = link if link.startswith("magnet:") else ""
        torrent_url = link if not link.startswith("magnet:") else ""

        # Try to get size from enclosure or content
        size = ""
        for enc in getattr(entry, "enclosures", []):
            length = enc.get("length", "")
            if length:
                try:
                    mb = int(length) / (1024 * 1024)
                    size = f"{mb:.1f} MiB" if mb < 1024 else f"{mb / 1024:.2f} GiB"
                except ValueError:
                    pass

        items.append(
            TorrentItem(
                title=title,
                magnet=magnet,
                torrent_url=torrent_url,
                size=size,
                date=getattr(entry, "published", ""),
                source="subsplease",
            )
        )

    return SearchResult(items=items, total=len(items), source="subsplease")


async def get_current_season() -> SearchResult:
    """Get all entries from the current SubsPlease RSS (i.e. current season shows)."""
    return await search(keyword="", quality=1080)
