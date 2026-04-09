"""SubsPlease schedule scraper — fetches weekly airing schedule."""

import logging
import httpx
from bs4 import BeautifulSoup

from app.services.http_client import get_client

logger = logging.getLogger(__name__)


async def get_schedule() -> dict:
    """
    Fetch SubsPlease schedule page and parse the weekly airing table.
    Returns: {"Monday": [...], "Tuesday": [...], ...}
    """
    client = get_client("schedule")
    try:
        resp = await client.get("https://subsplease.org/schedule/")
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Failed to fetch SubsPlease schedule: %s", e)
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    schedule: dict[str, list[dict]] = {}

    # SubsPlease schedule uses day-of-week divs
    day_map = {
        "Monday": "周一", "Tuesday": "周二", "Wednesday": "周三",
        "Thursday": "周四", "Friday": "周五", "Saturday": "周六", "Sunday": "周日",
    }

    for day_div in soup.select(".day-of-week"):
        day_name = day_div.get_text(strip=True)
        day_cn = day_map.get(day_name, day_name)
        items = []

        # Items follow the day header
        next_el = day_div.find_next_sibling()
        while next_el and not next_el.get("class", [None]) == ["day-of-week"]:
            if hasattr(next_el, "select"):
                for show in next_el.select(".all-shows-link, .schedule-card, a"):
                    title = show.get_text(strip=True)
                    href = show.get("href", "")
                    if title:
                        items.append({
                            "title": title,
                            "page": f"https://subsplease.org{href}" if href.startswith("/") else href,
                            "day": day_cn,
                        })
            next_el = next_el.find_next_sibling()
            if next_el and "day-of-week" in (next_el.get("class") or []):
                break

        if items:
            schedule[day_cn] = items

    return schedule
