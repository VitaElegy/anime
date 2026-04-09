"""SSE crawl endpoint — real-time crawl with Server-Sent Events."""

import asyncio
import json
import time
import logging
from datetime import datetime
from typing import Any, Callable, Awaitable

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.services import nyaa, subsplease, bangumi, dmhy, mikan, animetosho, animegarden, comicat
from app.services import database as db

logger = logging.getLogger(__name__)
router = APIRouter()


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


async def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _format_item(item: Any, source: str) -> str:
    """Format a single result item for SSE log display."""
    title = getattr(item, "title", str(item))[:80]
    parts = [title]
    if hasattr(item, "seeders") and item.seeders:
        parts.append(f"S:{item.seeders}")
    if hasattr(item, "leechers") and item.leechers:
        parts.append(f"L:{item.leechers}")
    if hasattr(item, "size") and item.size:
        parts.append(item.size)
    if hasattr(item, "score") and item.score:
        parts.append(f"评分:{item.score}")
    if hasattr(item, "name_cn") and item.name_cn:
        return f"{item.name_cn or getattr(item, 'name', title)} ({', '.join(parts[1:])})" if len(parts) > 1 else item.name_cn or getattr(item, "name", title)
    return " ".join(parts)


async def _crawl_generic(
    source: str,
    label: str,
    keyword: str,
    url: str,
    fetch_fn: Callable[[], Awaitable[Any]],
    extract_items: Callable[[Any], list] = lambda r: r.items if hasattr(r, "items") else r,
    extract_count: Callable[[Any], int] = lambda r: len(r.items) if hasattr(r, "items") else len(r),
):
    """Generic SSE crawl generator — eliminates per-source duplication."""
    display_kw = keyword if keyword else "(默认)"
    yield await _sse_event({"ts": _now(), "level": "info", "source": source, "msg": f"开始抓取 {label} [关键词={display_kw}]..."})
    yield await _sse_event({"ts": _now(), "level": "info", "source": source, "msg": f"正在请求: {url}"})

    t0 = time.monotonic()
    try:
        result = await fetch_fn()
        elapsed = int((time.monotonic() - t0) * 1000)
        items = extract_items(result)
        count = extract_count(result)

        yield await _sse_event({"ts": _now(), "level": "info", "source": source, "msg": f"响应成功 ({elapsed}ms)"})
        yield await _sse_event({"ts": _now(), "level": "info", "source": source, "msg": f"解析到 {count} 条数据..."})

        for i, item in enumerate(items[:5]):
            yield await _sse_event({"ts": _now(), "level": "info", "source": source, "msg": f"  [{i+1}] {_format_item(item, source)}"})
            await asyncio.sleep(0.05)

        if count > 5:
            yield await _sse_event({"ts": _now(), "level": "info", "source": source, "msg": f"  ... 及其余 {count - 5} 条"})

        yield await _sse_event({"ts": _now(), "level": "success", "source": source, "msg": f"完成！共 {count} 条 ({elapsed}ms)"})
        db.add_crawl_record(source, keyword, count, elapsed)
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        yield await _sse_event({"ts": _now(), "level": "error", "source": source, "msg": f"失败: {e}"})
        db.add_crawl_record(source, keyword, 0, elapsed, "error", str(e))


def _crawl_subsplease(keyword: str, quality: int):
    url = f"https://subsplease.org/rss/?r={quality}"
    return _crawl_generic("subsplease", "SubsPlease", keyword, url,
                          lambda: subsplease.search(keyword=keyword, quality=quality))


def _crawl_nyaa(keyword: str, page: int = 1):
    from urllib.parse import quote
    url = f"https://nyaa.land/?f=0&c=1_0&q={quote(keyword)}&p={page}"
    return _crawl_generic("nyaa", "Nyaa.land", keyword, url,
                          lambda: nyaa.search_html(keyword, page=page))


def _crawl_bangumi(keyword: str):
    kw = keyword or "2026年4月"
    url = f"https://api.bgm.tv/search/subject/{kw}"
    return _crawl_generic("bangumi", "Bangumi", kw, url,
                          lambda: bangumi.search(kw),
                          extract_items=lambda r: r,
                          extract_count=lambda r: len(r))


def _crawl_dmhy(keyword: str, page: int = 1):
    from urllib.parse import quote
    url = f"https://share.dmhy.org/topics/list/page/{page}?keyword={quote(keyword)}&sort_id=2"
    return _crawl_generic("dmhy", "动漫花园", keyword, url,
                          lambda: dmhy.search_html(keyword, page=page))


def _crawl_mikan(keyword: str):
    url = f"https://mikanani.me/RSS/Search?searchstr={keyword}" if keyword else "https://mikanani.me/RSS/Classic"
    async def fetch():
        if keyword:
            return await mikan.search_rss(keyword)
        return await mikan.get_current_season_rss()
    return _crawl_generic("mikan", "蜜柑计划", keyword, url, fetch)


def _crawl_animetosho(keyword: str):
    kw = keyword or "2026"
    url = f"https://feed.animetosho.org/json?q={kw}"
    return _crawl_generic("animetosho", "AnimeTosho", kw, url,
                          lambda: animetosho.search(kw))


def _crawl_animegarden(keyword: str):
    url = f"https://api.animes.garden/resources?search={keyword}" if keyword else "https://api.animes.garden/resources?type=动画"
    return _crawl_generic("animegarden", "AnimeGarden", keyword, url,
                          lambda: animegarden.search(keyword, resource_type="动画" if not keyword else ""))


def _crawl_comicat(keyword: str):
    url = f"https://comicat.org/search.php?keyword={keyword}" if keyword else "https://comicat.org/rss.xml"
    return _crawl_generic("comicat", "漫猫动漫", keyword, url,
                          lambda: comicat.search_rss(keyword))


@router.get("/stream", summary="SSE crawl stream")
async def crawl_stream(
    source: str = Query(..., description="Source: subsplease, nyaa, bangumi, dmhy, mikan, animetosho, animegarden, comicat, all"),
    keyword: str = Query("", description="Search keyword"),
    quality: int = Query(1080, description="SubsPlease quality"),
    page: int = Query(1, ge=1, description="Page number (Nyaa/DMHY only)"),
):
    async def generate():
        yield await _sse_event({"ts": _now(), "level": "info", "source": "system", "msg": f"抓取任务启动 [source={source}, keyword={keyword or '(默认)'}, page={page}]"})

        sources_to_crawl = []
        if source in ("subsplease", "all"):
            sources_to_crawl.append("subsplease")
        if source in ("nyaa", "all"):
            sources_to_crawl.append("nyaa")
        if source in ("bangumi", "all"):
            sources_to_crawl.append("bangumi")
        if source in ("dmhy", "all"):
            sources_to_crawl.append("dmhy")
        if source in ("mikan", "all"):
            sources_to_crawl.append("mikan")
        if source in ("animetosho", "all"):
            sources_to_crawl.append("animetosho")
        if source in ("animegarden", "all"):
            sources_to_crawl.append("animegarden")
        if source in ("comicat", "all"):
            sources_to_crawl.append("comicat")

        for src in sources_to_crawl:
            if src == "subsplease":
                async for event in _crawl_subsplease(keyword, quality):
                    yield event
            elif src == "nyaa":
                async for event in _crawl_nyaa(keyword, page):
                    yield event
            elif src == "bangumi":
                async for event in _crawl_bangumi(keyword):
                    yield event
            elif src == "dmhy":
                async for event in _crawl_dmhy(keyword, page):
                    yield event
            elif src == "mikan":
                async for event in _crawl_mikan(keyword):
                    yield event
            elif src == "animetosho":
                async for event in _crawl_animetosho(keyword):
                    yield event
            elif src == "animegarden":
                async for event in _crawl_animegarden(keyword):
                    yield event
            elif src == "comicat":
                async for event in _crawl_comicat(keyword):
                    yield event

        yield await _sse_event({"ts": _now(), "level": "success", "source": "system", "msg": "所有抓取任务完成"})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/history", summary="Get crawl history")
async def crawl_history(limit: int = Query(50, ge=1, le=200)):
    return db.get_crawl_history(limit)
