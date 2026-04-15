"""Background warmers for fixed pages and common cached queries."""

import asyncio
import logging

from app.services import anilist, calendar as calendar_service, database as db, image_cache, nyaa, schedule, subsplease

logger = logging.getLogger(__name__)

CORE_REFRESH_INTERVAL = 15 * 60
FAVORITE_REFRESH_INTERVAL = 45 * 60


def _favorite_keywords(limit: int = 6) -> list[str]:
    favorites = db.get_all_favorites(status="watching") or db.get_all_favorites()
    keywords = []
    seen = set()
    for item in favorites[:limit]:
        for candidate in (item.get("name"), item.get("name_cn")):
            keyword = (candidate or "").strip()
            if keyword and keyword not in seen:
                seen.add(keyword)
                keywords.append(keyword)
    return keywords


async def warm_core_caches():
    try:
        latest = await subsplease.search("", 1080, force_refresh=True)
        await schedule.get_schedule(force_refresh=True)
        await anilist.get_trending(per_page=24, force_refresh=True)
        await anilist.get_airing_schedule(page=1, per_page=50, force_refresh=True)
        calendar_payload = await calendar_service.get_calendar_overview(force_refresh=True)

        cover_urls = []
        seen_cover_urls = set()
        for items in calendar_payload.week.values():
            for item in items:
                cover_url = (item.cover_url or "").strip()
                if not cover_url or cover_url in seen_cover_urls:
                    continue
                seen_cover_urls.add(cover_url)
                cover_urls.append(cover_url)

        if cover_urls:
            await image_cache.prefetch_images(cover_urls[:24])

        day_entry_count = sum(len(items) for items in calendar_payload.week.values())
        logger.info("Core caches warmed: latest=%d calendar_entries=%d covers=%d", len(latest.items), day_entry_count, len(cover_urls))
    except Exception as exc:
        logger.warning("Failed to warm core caches: %s", exc)


async def warm_favorite_queries():
    keywords = _favorite_keywords()
    if not keywords:
        return

    for keyword in keywords:
        try:
            await anilist.search(keyword, page=1, per_page=12, force_refresh=True)
            await subsplease.search(keyword, 1080, force_refresh=True)
            await nyaa.search_html(keyword, page=1, force_refresh=True)
        except Exception as exc:
            logger.warning("Failed to warm favorite query '%s': %s", keyword, exc)
        await asyncio.sleep(0.2)

    logger.info("Favorite query caches warmed: %d keywords", len(keywords))


async def run_periodic_warmer():
    favorite_tick = 0
    while True:
        await warm_core_caches()
        favorite_tick += CORE_REFRESH_INTERVAL
        if favorite_tick >= FAVORITE_REFRESH_INTERVAL:
            favorite_tick = 0
            await warm_favorite_queries()
        await asyncio.sleep(CORE_REFRESH_INTERVAL)
