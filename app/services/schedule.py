"""SubsPlease schedule service backed by the official JSON endpoint."""

import logging

import httpx

from app.services import response_cache

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": "NicoTracker/1.0"},
            follow_redirects=True,
        )
    return _client


BASE_URL = "https://subsplease.org"


async def get_schedule(tz: str = "Asia/Shanghai", force_refresh: bool = False) -> dict:
    cache_key = response_cache.make_cache_key("subsplease.schedule", scope="weekly", tz=tz)

    async def producer():
        data = await _get_schedule_uncached(tz=tz)
        return data or None

    payload = await response_cache.get_or_set_json(
        cache_key=cache_key,
        cache_group="subsplease.schedule",
        ttl_seconds=1800,
        producer=producer,
        force_refresh=force_refresh,
        allow_stale=True,
    )
    return payload or {}


def _absolute_url(path: str) -> str:
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{BASE_URL}{path}" if path.startswith("/") else f"{BASE_URL}/{path.lstrip('/')}"


async def _get_schedule_uncached(tz: str = "Asia/Shanghai") -> dict:
    """Fetch SubsPlease weekly schedule from the official JSON API."""
    client = _get_client()
    try:
        resp = await client.get(
            f"{BASE_URL}/api/",
            params={"f": "schedule", "tz": tz},
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Failed to fetch SubsPlease schedule: %s", e)
        return {}

    try:
        payload = resp.json()
    except ValueError as e:
        logger.error("Failed to decode SubsPlease schedule JSON: %s", e)
        return {}

    raw_schedule = payload.get("schedule")
    if not isinstance(raw_schedule, dict):
        logger.warning("Unexpected SubsPlease schedule payload shape")
        return {}

    schedule: dict[str, list[dict]] = {}

    day_map = {
        "Monday": "周一", "Tuesday": "周二", "Wednesday": "周三",
        "Thursday": "周四", "Friday": "周五", "Saturday": "周六", "Sunday": "周日",
    }

    for day_name, items in raw_schedule.items():
        if not isinstance(items, list):
            continue
        day_cn = day_map.get(day_name, day_name)
        normalized_items = []
        for item in items:
            title = (item or {}).get("title", "").strip()
            if not title:
                continue
            page_slug = (item or {}).get("page", "").strip()
            image_url = (item or {}).get("image_url", "").strip()
            normalized_items.append(
                {
                    "title": title,
                    "page": f"{BASE_URL}/shows/{page_slug}" if page_slug else "",
                    "day": day_cn,
                    "time": (item or {}).get("time", ""),
                    "image_url": _absolute_url(image_url),
                }
            )

        if normalized_items:
            schedule[day_cn] = normalized_items

    return schedule
