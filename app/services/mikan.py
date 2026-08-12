"""Mikan Project (蜜柑计划) service — Chinese fansub resource aggregation.

Official: https://mikanani.me — 中文动画字幕组 RSS 聚合站
Fallback mirror: https://mikanani.kas.pub (国内直连)

Features:
- `search_html`: full-text search, returns torrent items with Chinese fansub tags
- `get_bangumi_subgroups`: get all fansub groups available for a given bangumi_id
- `search_rss`: RSS-based search by bangumi_id + optional subgroup (fansub filter)

Mikan is the go-to source for Chinese-subbed anime in current season;
resources are indexed by Bangumi ID and grouped by fansub.
"""

import asyncio
import logging
import re
import time
from urllib.parse import quote, urljoin

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.models import SearchResult, TorrentItem
from app.services import response_cache

logger = logging.getLogger(__name__)

_last_request_time: float = 0
_lock = asyncio.Lock()
_client: httpx.AsyncClient | None = None


def _base_candidates() -> list[str]:
    """Try the official domain first, fall back to mirror if it fails."""
    urls = [settings.MIKAN_BASE_URL, settings.MIKAN_MIRROR_URL]
    # Dedupe while keeping order
    seen: set[str] = set()
    result: list[str] = []
    for u in urls:
        u = (u or "").rstrip("/")
        if u and u not in seen:
            seen.add(u)
            result.append(u)
    return result


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        kwargs: dict = {
            "timeout": 30,
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
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
        wait = settings.MIKAN_RATE_LIMIT - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time = time.monotonic()


async def _fetch(path: str) -> tuple[str, str] | tuple[None, None]:
    """Try each base URL until one succeeds; returns (html, base_used)."""
    await _rate_limit()
    client = _get_client()
    last_error: Exception | None = None
    for base in _base_candidates():
        url = urljoin(base + "/", path.lstrip("/"))
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text, base
        except httpx.HTTPError as e:  # noqa: PERF203
            logger.debug("Mikan %s failed: %s", url, e)
            last_error = e
            continue
    if last_error:
        logger.warning("All Mikan endpoints failed: %s", last_error)
    return None, None


_INFO_HASH_RE = re.compile(r"([a-fA-F0-9]{40})")


def _extract_hash(link: str) -> str:
    if not link:
        return ""
    m = _INFO_HASH_RE.search(link)
    return m.group(1).lower() if m else ""


def _magnet_from_hash(info_hash: str, title: str = "") -> str:
    if not info_hash:
        return ""
    base = f"magnet:?xt=urn:btih:{info_hash}"
    if title:
        base += f"&dn={quote(title)}"
    # Add some common trackers for wider swarm discovery
    trackers = [
        "udp://tracker.opentrackr.org:1337/announce",
        "udp://open.stealth.si:80/announce",
        "udp://tracker.torrent.eu.org:451/announce",
    ]
    for tr in trackers:
        base += f"&tr={quote(tr)}"
    return base


# ---------------------------------------------------------------------------
# RSS — preferred structured path (per our field audit)
# ---------------------------------------------------------------------------


async def search_rss(
    bangumi_id: str | int,
    subgroup_id: str | int = "",
    force_refresh: bool = False,
) -> SearchResult:
    cache_key = response_cache.make_cache_key(
        "mikan.search_rss",
        bangumi_id=str(bangumi_id),
        subgroup_id=str(subgroup_id),
    )

    async def producer():
        result = await _search_rss_uncached(bangumi_id, subgroup_id)
        return result.model_dump(mode="json")

    payload = await response_cache.get_or_set_json(
        cache_key=cache_key,
        cache_group="mikan.search_rss",
        ttl_seconds=600,
        producer=producer,
        force_refresh=force_refresh,
        allow_stale=True,
    )
    return SearchResult.model_validate(payload or {"items": [], "total": 0, "source": "mikan"})


async def _search_rss_uncached(bangumi_id: str | int, subgroup_id: str | int = "") -> SearchResult:
    path = f"/RSS/Bangumi?bangumiId={bangumi_id}"
    if subgroup_id:
        path += f"&subgroupid={subgroup_id}"
    xml, _ = await _fetch(path)
    if not xml:
        return SearchResult(items=[], total=0, source="mikan")

    feed = feedparser.parse(xml)
    items: list[TorrentItem] = []
    for entry in feed.entries:
        title = getattr(entry, "title", "") or ""
        # Mikan provides <enclosure url=".torrent"> and <link> to detail page
        torrent_url = ""
        detail_url = getattr(entry, "link", "") or ""
        for link in getattr(entry, "links", []):
            href = (link.get("href") or "").strip()
            if href.endswith(".torrent") or "/Download/" in href:
                torrent_url = href
                break
        if not torrent_url:
            # Fallback to RSS <enclosure>
            enclosures = getattr(entry, "enclosures", []) or []
            for enc in enclosures:
                href = enc.get("url", "") or enc.get("href", "")
                if href:
                    torrent_url = href
                    break

        info_hash = _extract_hash(torrent_url or detail_url)
        magnet = _magnet_from_hash(info_hash, title)

        # pubDate comes either at the item level or under Mikan's <torrent> ns
        pub = getattr(entry, "published", "") or getattr(entry, "updated", "")

        # description usually contains "[xxx MB]"
        desc = getattr(entry, "summary", "") or getattr(entry, "description", "")
        size = ""
        m = re.search(r"\[([^\[\]]+(?:MB|GB|KB|TB))\]", desc, re.IGNORECASE)
        if m:
            size = m.group(1).strip()

        items.append(
            TorrentItem(
                title=title,
                magnet=magnet,
                torrent_url=torrent_url,
                size=size,
                date=pub,
                source="mikan",
                info_hash=info_hash,
                detail_url=detail_url,
            )
        )
    return SearchResult(items=items, total=len(items), source="mikan")


# ---------------------------------------------------------------------------
# Full-text HTML search on the front page
# ---------------------------------------------------------------------------


async def search_html(
    keyword: str,
    force_refresh: bool = False,
) -> SearchResult:
    """Search Mikan by keyword (Chinese/Japanese/romaji all work)."""
    keyword = (keyword or "").strip()
    if not keyword:
        return SearchResult(items=[], total=0, source="mikan")

    cache_key = response_cache.make_cache_key(
        "mikan.search_html",
        keyword=keyword.lower(),
    )

    async def producer():
        result = await _search_html_uncached(keyword)
        return result.model_dump(mode="json")

    payload = await response_cache.get_or_set_json(
        cache_key=cache_key,
        cache_group="mikan.search_html",
        ttl_seconds=600,
        producer=producer,
        force_refresh=force_refresh,
        allow_stale=True,
    )
    return SearchResult.model_validate(payload or {"items": [], "total": 0, "source": "mikan"})


async def _search_html_uncached(keyword: str) -> SearchResult:
    path = f"/Home/Search?searchstr={quote(keyword)}"
    html, base = await _fetch(path)
    if not html:
        return SearchResult(items=[], total=0, source="mikan")

    soup = BeautifulSoup(html, "html.parser")
    items: list[TorrentItem] = []

    # Mikan's search renders episodes as <tr> inside <tbody>, with cells:
    # [0]: subtitle group icon, [1]: title link, [2]: size, [3]: publish time,
    # [4]: magnet link, [5]: torrent download link
    for row in soup.select("tbody tr"):
        cells = row.select("td")
        if len(cells) < 4:
            continue

        title_a = cells[1].select_one("a") if len(cells) > 1 else None
        title = title_a.get_text(strip=True) if title_a else ""
        detail_url = (
            urljoin((base or "") + "/", title_a["href"]) if title_a and title_a.has_attr("href") else ""
        )

        size = cells[2].get_text(strip=True) if len(cells) > 2 else ""
        date = cells[3].get_text(strip=True) if len(cells) > 3 else ""

        torrent_url = ""
        magnet = ""
        for a in row.select("a"):
            href = a.get("href", "")
            if not href:
                continue
            if href.startswith("magnet:"):
                magnet = href
            elif href.endswith(".torrent") or "/Download/" in href:
                torrent_url = urljoin((base or "") + "/", href)

        info_hash = _extract_hash(torrent_url or magnet or detail_url)
        if not magnet:
            magnet = _magnet_from_hash(info_hash, title)

        # fansub icon has alt attribute
        fansub = ""
        img = cells[0].select_one("img") if len(cells) > 0 else None
        if img and img.has_attr("alt"):
            fansub = img["alt"].strip()

        if not title:
            continue
        items.append(
            TorrentItem(
                title=title,
                magnet=magnet,
                torrent_url=torrent_url,
                size=size,
                date=date,
                source="mikan",
                info_hash=info_hash,
                fansub=fansub,
                detail_url=detail_url,
            )
        )

    return SearchResult(items=items, total=len(items), source="mikan")


# ---------------------------------------------------------------------------
# Bangumi detail — enumerate subgroups for a given bangumi_id
# ---------------------------------------------------------------------------


async def get_bangumi_subgroups(bangumi_id: str | int, force_refresh: bool = False) -> list[dict]:
    """Return list of available fansub groups for a Mikan bangumi ID.

    Each entry: {id, subgroup_id, name, last_update}
    """
    cache_key = response_cache.make_cache_key("mikan.subgroups", bangumi_id=str(bangumi_id))

    async def producer():
        return await _get_subgroups_uncached(bangumi_id)

    payload = await response_cache.get_or_set_json(
        cache_key=cache_key,
        cache_group="mikan.subgroups",
        ttl_seconds=3600,
        producer=producer,
        force_refresh=force_refresh,
        allow_stale=True,
    )
    return payload or []


async def _get_subgroups_uncached(bangumi_id: str | int) -> list[dict]:
    html, _ = await _fetch(f"/Home/Bangumi/{bangumi_id}")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    result: list[dict] = []
    for sub in soup.select(".subgroup-text"):
        name_a = sub.select_one("a")
        if not name_a:
            continue
        name = name_a.get_text(strip=True)
        # href pattern: /Home/PublishGroup/{group_id} or similar
        href = name_a.get("href", "")
        group_id = href.rstrip("/").split("/")[-1] if href else ""
        # Subgroup id is usually embedded on the RSS icon link
        sub_id = ""
        rss_a = sub.select_one("a[href*='subgroupid']")
        if rss_a:
            m = re.search(r"subgroupid=(\d+)", rss_a.get("href", ""))
            if m:
                sub_id = m.group(1)
        result.append(
            {
                "id": group_id,
                "subgroup_id": sub_id,
                "name": name,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Front page — current season (per-weekday)
# ---------------------------------------------------------------------------


async def get_current_season_bangumis(force_refresh: bool = False) -> list[dict]:
    """Return the current Mikan home page's bangumi cards grouped by weekday."""
    cache_key = response_cache.make_cache_key("mikan.front_page")

    async def producer():
        return await _get_front_page_uncached()

    payload = await response_cache.get_or_set_json(
        cache_key=cache_key,
        cache_group="mikan.front_page",
        ttl_seconds=1800,
        producer=producer,
        force_refresh=force_refresh,
        allow_stale=True,
    )
    return payload or []


async def _get_front_page_uncached() -> list[dict]:
    html, base = await _fetch("/")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    for card in soup.select("li.an-ul, div.sk-bangumi"):
        link = card.select_one("a[href*='/Home/Bangumi/']")
        if not link:
            continue
        href = link.get("href", "")
        bid = href.rstrip("/").split("/")[-1] if href else ""
        title = link.get("title") or link.get_text(strip=True)
        if not bid or not title:
            continue
        items.append(
            {
                "bangumi_id": bid,
                "title": title,
                "url": urljoin((base or "") + "/", href),
            }
        )
    return items
