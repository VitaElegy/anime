"""SubsPlease schedule & show API — JSON endpoints (replaces HTML scraping)."""

import logging

import httpx

from app.services.http_client import get_client

logger = logging.getLogger(__name__)

SP_API = "https://subsplease.org/api/"

DAY_MAP = {
    "Monday": "周一", "Tuesday": "周二", "Wednesday": "周三",
    "Thursday": "周四", "Friday": "周五", "Saturday": "周六", "Sunday": "周日",
}


async def get_schedule() -> dict:
    """
    Fetch SubsPlease weekly schedule via JSON API.
    Returns: {"周一": [{"title": ..., "page": ..., "day": ..., "time": ..., "image_url": ...}], ...}

    Uses: GET /api/?f=schedule&tz=Asia/Shanghai
    """
    client = get_client("default")
    try:
        resp = await client.get(SP_API, params={"f": "schedule", "tz": "Asia/Shanghai"})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("SubsPlease schedule API failed: %s", e)
        return {}

    data = resp.json()
    schedule: dict[str, list[dict]] = {}

    raw_schedule = data.get("schedule", data)
    if not isinstance(raw_schedule, dict):
        logger.warning("SubsPlease schedule returned non-dict: %s", type(raw_schedule).__name__)
        return {}

    for eng_day, shows in raw_schedule.items():
        day_cn = DAY_MAP.get(eng_day, eng_day)
        if not isinstance(shows, list):
            continue
        items = []
        for show in shows:
            title = show.get("title", "")
            if not title:
                continue
            page = show.get("page", "")
            image = show.get("image_url", "")
            time_str = show.get("time", "")
            items.append({
                "title": title,
                "page": f"https://subsplease.org/shows/{page}" if page and not page.startswith("http") else page,
                "day": day_cn,
                "time": time_str,
                "image_url": f"https://subsplease.org{image}" if image and image.startswith("/") else image,
            })
        if items:
            schedule[day_cn] = items

    return schedule


async def get_show_episodes(sid: int) -> dict:
    """
    Fetch all episodes for a specific show via JSON API.
    Returns: {"show": "...", "episodes": [{"episode": "01", "date": "...", "downloads": [...]}]}

    Uses: GET /api/?f=show&sid=NNN&tz=Asia/Shanghai
    """
    client = get_client("default")
    try:
        resp = await client.get(SP_API, params={"f": "show", "sid": sid, "tz": "Asia/Shanghai"})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("SubsPlease show API failed for sid=%d: %s", sid, e)
        return {}

    data = resp.json()
    show_name = data.get("show", "")
    episodes_raw = data.get("episode", {})
    batch = data.get("batch", {})

    episodes = []
    for key, ep_data in episodes_raw.items():
        downloads = []
        for dl in ep_data.get("downloads", []):
            downloads.append({
                "res": dl.get("res", ""),
                "magnet": dl.get("magnet", ""),
                "torrent": dl.get("torrent", ""),
            })
        episodes.append({
            "episode": ep_data.get("episode", ""),
            "date": ep_data.get("release_date", ""),
            "time": ep_data.get("time", ""),
            "downloads": downloads,
        })

    # Sort by episode number
    episodes.sort(key=lambda e: e.get("episode", ""), reverse=True)

    return {
        "show": show_name,
        "episodes": episodes,
        "batch": batch,
    }
