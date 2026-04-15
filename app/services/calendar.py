"""Server-side cached calendar overview for the high-traffic calendar page."""

import asyncio
import time
from datetime import datetime
from email.utils import parsedate_to_datetime

from app.models import CalendarDayEntry, CalendarOverview, CalendarTimelineItem, TorrentItem
from app.services import cover_resolver, response_cache, schedule, subsplease

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _parse_datetime(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None

    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        pass

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _day_name_from_date(value: str) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return ""
    idx = parsed.weekday()
    return WEEKDAYS[idx] if 0 <= idx < len(WEEKDAYS) else ""


def _display_for(
    title: str,
    cover_map: dict[str, dict[str, str | int]],
    fallback_cover: str = "",
) -> tuple[str, str, str, int]:
    cleaned = cover_resolver.clean_title(title)
    info = cover_map.get(title) or (cover_map.get(cleaned) if cleaned else None) or {}
    name = info.get("name_cn") or info.get("name") or cleaned or title
    cover_url = info.get("cover_url") or fallback_cover or ""
    bangumi_id = int(info.get("bangumi_id") or 0)
    return name.casefold(), name, cover_url, bangumi_id


def _remember_title(representative_titles: dict[str, str], raw_title: str):
    cleaned = cover_resolver.clean_title(raw_title)
    if cleaned and cleaned not in representative_titles:
        representative_titles[cleaned] = raw_title


def _propagate_cover_aliases(cover_map: dict[str, dict[str, str | int]], titles: list[str]):
    for raw_title in titles:
        cleaned = cover_resolver.clean_title(raw_title)
        info = cover_map.get(raw_title) or (cover_map.get(cleaned) if cleaned else None)
        if not info:
            continue
        cover_map[raw_title] = info
        if cleaned:
            cover_map[cleaned] = info


def _sort_timestamp(item: TorrentItem) -> float:
    parsed = _parse_datetime(item.date)
    return parsed.timestamp() if parsed is not None else 0.0


async def get_calendar_overview(quality: int = 1080, force_refresh: bool = False) -> CalendarOverview:
    cache_key = response_cache.make_cache_key("calendar.overview", quality=quality)

    async def producer():
        return (await _build_calendar_overview(quality=quality, force_refresh=force_refresh)).model_dump(mode="json")

    payload = await response_cache.get_or_set_json(
        cache_key=cache_key,
        cache_group="calendar.overview",
        ttl_seconds=300,
        producer=producer,
        force_refresh=force_refresh,
        allow_stale=True,
    )
    return CalendarOverview.model_validate(payload or {"week": {}, "timeline": [], "generated_at": int(time.time())})


async def _build_calendar_overview(quality: int = 1080, force_refresh: bool = False) -> CalendarOverview:
    rss_result, weekly_schedule = await asyncio.gather(
        subsplease.search("", quality, force_refresh=force_refresh),
        schedule.get_schedule(force_refresh=force_refresh),
    )

    representative_titles: dict[str, str] = {}
    schedule_titles: list[str] = []
    for day_items in weekly_schedule.values():
        for show in day_items:
            raw_title = (show or {}).get("title", "").strip()
            if not raw_title:
                continue
            schedule_titles.append(raw_title)
            _remember_title(representative_titles, raw_title)

    rss_titles: list[str] = []
    for item in rss_result.items:
        if not item.title:
            continue
        rss_titles.append(item.title)
        _remember_title(representative_titles, item.title)

    cover_map: dict[str, dict[str, str | int]] = {}
    unique_titles = list(representative_titles.values())
    if unique_titles:
        resolved_covers = await cover_resolver.resolve_titles(unique_titles, limit=len(unique_titles), force_refresh=force_refresh)
        for resolved in resolved_covers:
            if not resolved.get("cover_url"):
                continue
            info = {
                "bangumi_id": int(resolved.get("bangumi_id") or 0),
                "cover_url": resolved.get("cover_url", ""),
                "name_cn": resolved.get("name_cn", ""),
                "name": resolved.get("name", ""),
            }
            raw_title = resolved.get("title", "")
            cleaned = cover_resolver.clean_title(raw_title)
            cover_map[raw_title] = info
            if cleaned:
                cover_map[cleaned] = info

    _propagate_cover_aliases(cover_map, schedule_titles)
    _propagate_cover_aliases(cover_map, rss_titles)

    rss_grouped: dict[str, list[TorrentItem]] = {day: [] for day in WEEKDAYS}
    for item in rss_result.items:
        day_name = _day_name_from_date(item.date)
        if day_name:
            rss_grouped[day_name].append(item)

    week: dict[str, list[CalendarDayEntry]] = {}
    for day_name in WEEKDAYS:
        day_entries: list[CalendarDayEntry] = []
        seen: dict[str, CalendarDayEntry] = {}

        for show in weekly_schedule.get(day_name, []):
            raw_title = show.get("title", "")
            key, name, cover_url, bangumi_id = _display_for(raw_title, cover_map, show.get("image_url", ""))
            entry = CalendarDayEntry(
                day=day_name,
                bangumi_id=bangumi_id,
                title=name,
                raw_title=raw_title,
                cover_url=cover_url,
                time=show.get("time", ""),
                page=show.get("page", ""),
                source="subsplease.schedule",
            )
            if key not in seen:
                seen[key] = entry
                day_entries.append(entry)

        for item in rss_grouped.get(day_name, []):
            key, name, cover_url, bangumi_id = _display_for(item.title, cover_map)
            existing = seen.get(key)
            if existing is not None:
                if not existing.bangumi_id and bangumi_id:
                    existing.bangumi_id = bangumi_id
                if not existing.cover_url and cover_url:
                    existing.cover_url = cover_url
                if not existing.size and item.size:
                    existing.size = item.size
                if not existing.source:
                    existing.source = item.source
                if not existing.date and item.date:
                    existing.date = item.date
                continue

            entry = CalendarDayEntry(
                day=day_name,
                bangumi_id=bangumi_id,
                title=name,
                raw_title=item.title,
                cover_url=cover_url,
                size=item.size,
                source=item.source,
                date=item.date,
            )
            seen[key] = entry
            day_entries.append(entry)

        week[day_name] = day_entries

    timeline: list[CalendarTimelineItem] = []
    for item in sorted(rss_result.items, key=_sort_timestamp, reverse=True):
        _, display_title, cover_url, bangumi_id = _display_for(item.title, cover_map)
        timeline.append(
            CalendarTimelineItem(
                bangumi_id=bangumi_id,
                title=display_title,
                raw_title=item.title,
                cover_url=cover_url,
                size=item.size,
                source=item.source,
                date=item.date,
            )
        )

    return CalendarOverview(
        week=week,
        timeline=timeline,
        generated_at=int(time.time()),
    )
