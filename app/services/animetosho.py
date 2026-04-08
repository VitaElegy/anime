"""AnimeTosho (animetosho.org) — Anime torrent aggregator with JSON API."""

import asyncio
import logging
import time
from urllib.parse import quote

import httpx

from app.config import settings
from app.models import SearchResult, TorrentItem

logger = logging.getLogger(__name__)

TOSHO_API = "https://feed.animetosho.org/json"

_client: httpx.AsyncClient | None = None
_last_request_time: float = 0
_lock = asyncio.Lock()


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        kwargs: dict = {
            "timeout": 30,
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Accept": "application/json",
            },
            "follow_redirects": True,
        }
        if settings.HTTP_PROXY:
            kwargs["proxy"] = settings.HTTP_PROXY
        _client = httpx.AsyncClient(**kwargs)
    return _client


async def _rate_limit():
    global _last_request_time
    async with _lock:
        now = time.monotonic()
        wait = 1.0 - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time = time.monotonic()


def _format_size(total_size: int) -> str:
    if total_size <= 0:
        return ""
    if total_size >= 1024 ** 3:
        return f"{total_size / (1024 ** 3):.2f} GiB"
    elif total_size >= 1024 ** 2:
        return f"{total_size / (1024 ** 2):.1f} MiB"
    else:
        return f"{total_size / 1024:.0f} KiB"


async def search(keyword: str, page: int = 1, show_only: bool = False) -> SearchResult:
    """
    Search AnimeTosho via JSON API.

    AnimeTosho aggregates torrents from Nyaa, TokyoTosho, AniDex, etc.
    It provides a clean JSON API with magnet links and torrent URLs.

    Args:
        keyword: Search query.
        page: Page number (0-indexed internally, 1-indexed for user).
        show_only: If True, only return show/series entries (not individual episodes).
    """
    await _rate_limit()

    params: dict = {
        "q": keyword,
        "offset": (page - 1) * 50,
    }
    if show_only:
        params["show"] = "true"

    client = _get_client()
    try:
        resp = await client.get(TOSHO_API, params=params)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("AnimeTosho search failed: %s", e)
        return SearchResult(items=[], total=0, source="animetosho")

    data = resp.json()
    items: list[TorrentItem] = []

    # API returns a list of entries directly
    entries = data if isinstance(data, list) else data.get("entries", data.get("items", []))

    for entry in entries:
        title = entry.get("title", "")
        magnet = entry.get("magnet_uri", "") or entry.get("magnet", "")
        torrent_url = entry.get("torrent_url", "") or entry.get("link", "")

        # Size
        total_size = entry.get("total_size", 0)
        size = _format_size(total_size)

        # Seeders/leechers
        seeders = entry.get("seeders", 0)
        leechers = entry.get("leechers", 0)

        # Date — timestamp
        date_ts = entry.get("timestamp", 0)
        date = ""
        if date_ts:
            import datetime
            try:
                date = datetime.datetime.fromtimestamp(date_ts).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass

        # Nyaa ID for cross-reference
        nyaa_id = entry.get("nyaa_id", 0)

        if title:
            items.append(
                TorrentItem(
                    title=title,
                    magnet=magnet,
                    torrent_url=torrent_url,
                    size=size,
                    seeders=seeders,
                    leechers=leechers,
                    date=date,
                    source="animetosho",
                )
            )

    return SearchResult(items=items, total=len(items), source="animetosho")
