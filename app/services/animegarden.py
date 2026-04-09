"""AnimeGarden (animes.garden) — Open API anime BT resource aggregator.

Aggregates resources from DMHY, Moe, ANi and more.
Features: structured fansub info, Bangumi subject IDs, Chinese search, no auth required.
API docs: https://deepwiki.com/yjl9903/AnimeGarden/6-api-and-integration
"""

import asyncio
import logging
import time

import httpx

from app.models import SearchResult, TorrentItem
from app.services.http_client import get_client

logger = logging.getLogger(__name__)

GARDEN_API = "https://api.animes.garden"

_last_request_time: float = 0
_lock = asyncio.Lock()


async def _rate_limit():
    global _last_request_time
    async with _lock:
        now = time.monotonic()
        wait = 0.5 - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time = time.monotonic()


def _format_size(size_kb: int) -> str:
    """Convert size in KB to human-readable string."""
    if size_kb <= 0:
        return ""
    if size_kb >= 1024 * 1024:
        return f"{size_kb / (1024 * 1024):.2f} GiB"
    elif size_kb >= 1024:
        return f"{size_kb / 1024:.1f} MiB"
    else:
        return f"{size_kb} KiB"


async def search(
    keyword: str = "",
    page: int = 1,
    page_size: int = 50,
    resource_type: str = "",
    fansub_id: int = 0,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> SearchResult:
    """
    Search AnimeGarden via REST API.

    Features:
    - Native Chinese keyword search
    - Filter by type (动画/音乐/合集/etc.)
    - Filter by fansub group ID
    - Include/exclude keyword filters
    - Returns structured fansub + publisher info

    Args:
        keyword: Search keyword (supports Chinese/Japanese/English).
        page: Page number (1-indexed).
        page_size: Results per page (max 100).
        resource_type: Resource type filter (动画, 音乐, 合集, etc.)
        fansub_id: Filter by specific fansub group ID.
        include: Keywords that must appear in title.
        exclude: Keywords that must not appear in title.
    """
    await _rate_limit()

    params: dict = {
        "page": page,
        "pageSize": min(page_size, 100),
    }

    if keyword:
        params["search"] = keyword
    if resource_type:
        params["type"] = resource_type
    if fansub_id:
        params["fansub"] = fansub_id

    # Include/exclude filters use array notation
    if include:
        for i, kw in enumerate(include):
            params[f"include[{i}]"] = kw
    if exclude:
        for i, kw in enumerate(exclude):
            params[f"exclude[{i}]"] = kw

    client = get_client("default")
    try:
        resp = await client.get(f"{GARDEN_API}/resources", params=params)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("AnimeGarden search failed: %s", e)
        return SearchResult(items=[], total=0, source="animegarden")

    data = resp.json()
    items: list[TorrentItem] = []

    for entry in data.get("resources", []):
        title = entry.get("title", "")
        magnet = entry.get("magnet", "")

        # Build rich title with fansub info if available
        fansub = entry.get("fansub", {})
        fansub_name = fansub.get("name", "") if fansub else ""

        # Size is in KB
        size_kb = entry.get("size", 0)
        size = _format_size(size_kb)

        # Date
        created = entry.get("createdAt", "")
        date = ""
        if created:
            # ISO 8601 -> "YYYY-MM-DD HH:MM"
            date = created[:16].replace("T", " ")

        # Source detail: include provider + fansub
        source_detail = "animegarden"

        if title:
            items.append(
                TorrentItem(
                    title=title,
                    magnet=magnet,
                    torrent_url=entry.get("href", ""),
                    size=size,
                    date=date,
                    source=source_detail,
                )
            )

    # AnimeGarden doesn't return total count directly; use pagination hint
    total = len(items)
    if not data.get("complete", True):
        total = max(total, page * page_size)  # Estimate: at least this many

    return SearchResult(items=items, total=total, source="animegarden")


async def get_latest(page: int = 1, page_size: int = 50, resource_type: str = "动画") -> SearchResult:
    """Get latest anime resources from AnimeGarden."""
    return await search(keyword="", page=page, page_size=page_size, resource_type=resource_type)


async def search_by_bangumi_id(subject_id: int, page: int = 1, page_size: int = 50) -> SearchResult:
    """
    Search AnimeGarden by Bangumi subject ID.
    This is the FASTEST query path (indexed) and most accurate (no fuzzy matching).
    """
    await _rate_limit()

    params: dict = {
        "page": page,
        "pageSize": min(page_size, 100),
        "subject": subject_id,
    }

    client = get_client("default")
    try:
        resp = await client.get(f"{GARDEN_API}/resources", params=params)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("AnimeGarden subject search failed for %d: %s", subject_id, e)
        return SearchResult(items=[], total=0, source="animegarden")

    data = resp.json()
    items: list[TorrentItem] = []

    for entry in data.get("resources", []):
        title = entry.get("title", "")
        magnet = entry.get("magnet", "")
        size_kb = entry.get("size", 0)
        size = _format_size(size_kb)
        created = entry.get("createdAt", "")
        date = created[:16].replace("T", " ") if created else ""

        if title:
            items.append(
                TorrentItem(
                    title=title,
                    magnet=magnet,
                    torrent_url=entry.get("href", ""),
                    size=size,
                    date=date,
                    source="animegarden",
                )
            )

    total = len(items)
    if not data.get("complete", True):
        total = max(total, page * page_size)

    return SearchResult(items=items, total=total, source="animegarden")
