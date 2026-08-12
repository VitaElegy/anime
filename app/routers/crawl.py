"""SSE crawl endpoint — real-time crawl with Server-Sent Events."""

import asyncio
import json
import logging
import time
from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.services import bangumi, nyaa, subsplease
from app.services import database as db

logger = logging.getLogger(__name__)
router = APIRouter()


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


async def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _crawl_subsplease(keyword: str, quality: int):
    yield await _sse_event(
        {"ts": _now(), "level": "info", "source": "subsplease", "msg": "开始抓取 SubsPlease RSS..."}
    )
    url = f"https://subsplease.org/rss/?r={quality}"
    yield await _sse_event({"ts": _now(), "level": "info", "source": "subsplease", "msg": f"正在请求: {url}"})

    t0 = time.monotonic()
    try:
        result = await subsplease.search(keyword=keyword, quality=quality)
        elapsed = int((time.monotonic() - t0) * 1000)
        yield await _sse_event(
            {"ts": _now(), "level": "info", "source": "subsplease", "msg": f"响应成功 ({elapsed}ms)"}
        )
        yield await _sse_event(
            {
                "ts": _now(),
                "level": "info",
                "source": "subsplease",
                "msg": f"正在解析 {len(result.items)} 条数据...",
            }
        )

        for i, item in enumerate(result.items[:5]):
            yield await _sse_event(
                {"ts": _now(), "level": "info", "source": "subsplease", "msg": f"  [{i + 1}] {item.title}"}
            )
            await asyncio.sleep(0.05)

        if len(result.items) > 5:
            yield await _sse_event(
                {
                    "ts": _now(),
                    "level": "info",
                    "source": "subsplease",
                    "msg": f"  ... 及其余 {len(result.items) - 5} 条",
                }
            )

        yield await _sse_event(
            {
                "ts": _now(),
                "level": "success",
                "source": "subsplease",
                "msg": f"完成！共 {len(result.items)} 条 ({elapsed}ms)",
            }
        )
        db.add_crawl_record("subsplease", keyword, len(result.items), elapsed)
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        yield await _sse_event({"ts": _now(), "level": "error", "source": "subsplease", "msg": f"失败: {e}"})
        db.add_crawl_record("subsplease", keyword, 0, elapsed, "error", str(e))


async def _crawl_nyaa(keyword: str, page: int = 1):
    """Crawl a single page from Nyaa."""
    # Empty keyword on Nyaa shows the homepage / latest uploads
    display_kw = keyword if keyword else "(最新)"
    yield await _sse_event(
        {
            "ts": _now(),
            "level": "info",
            "source": "nyaa",
            "msg": f"开始抓取 Nyaa.land [关键词={display_kw}, 页={page}]...",
        }
    )

    from urllib.parse import quote

    url = f"https://nyaa.land/?f=0&c=1_0&q={quote(keyword)}&p={page}"
    yield await _sse_event({"ts": _now(), "level": "info", "source": "nyaa", "msg": f"正在请求: {url}"})

    t0 = time.monotonic()
    try:
        result = await nyaa.search_html(keyword, page=page)
        elapsed = int((time.monotonic() - t0) * 1000)
        yield await _sse_event(
            {"ts": _now(), "level": "info", "source": "nyaa", "msg": f"响应成功 ({elapsed}ms)"}
        )
        yield await _sse_event(
            {
                "ts": _now(),
                "level": "info",
                "source": "nyaa",
                "msg": f"HTML 解析中, 发现 {len(result.items)} 条种子...",
            }
        )

        for i, item in enumerate(result.items[:5]):
            yield await _sse_event(
                {
                    "ts": _now(),
                    "level": "info",
                    "source": "nyaa",
                    "msg": f"  [{i + 1}] {item.title} (S:{item.seeders} L:{item.leechers} {item.size})",
                }
            )
            await asyncio.sleep(0.05)

        if len(result.items) > 5:
            yield await _sse_event(
                {
                    "ts": _now(),
                    "level": "info",
                    "source": "nyaa",
                    "msg": f"  ... 及其余 {len(result.items) - 5} 条",
                }
            )

        yield await _sse_event(
            {
                "ts": _now(),
                "level": "success",
                "source": "nyaa",
                "msg": f"完成！共 {len(result.items)} 条 ({elapsed}ms)",
            }
        )
        db.add_crawl_record("nyaa", keyword, len(result.items), elapsed)
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        yield await _sse_event({"ts": _now(), "level": "error", "source": "nyaa", "msg": f"失败: {e}"})
        db.add_crawl_record("nyaa", keyword, 0, elapsed, "error", str(e))


async def _crawl_bangumi(keyword: str):
    # Bangumi API requires non-empty keyword; use sensible defaults
    if not keyword:
        keyword = "2026年4月"
    yield await _sse_event(
        {
            "ts": _now(),
            "level": "info",
            "source": "bangumi",
            "msg": f"开始抓取 Bangumi 元数据 [关键词={keyword}]...",
        }
    )
    url = f"https://api.bgm.tv/search/subject/{keyword}"
    yield await _sse_event({"ts": _now(), "level": "info", "source": "bangumi", "msg": f"正在请求: {url}"})

    t0 = time.monotonic()
    try:
        results = await bangumi.search(keyword)
        elapsed = int((time.monotonic() - t0) * 1000)
        yield await _sse_event(
            {"ts": _now(), "level": "info", "source": "bangumi", "msg": f"响应成功 ({elapsed}ms)"}
        )
        yield await _sse_event(
            {
                "ts": _now(),
                "level": "info",
                "source": "bangumi",
                "msg": f"解析到 {len(results)} 条番剧信息...",
            }
        )

        for i, item in enumerate(results[:5]):
            name = item.name_cn or item.name
            yield await _sse_event(
                {
                    "ts": _now(),
                    "level": "info",
                    "source": "bangumi",
                    "msg": f"  [{i + 1}] {name} (评分:{item.score})",
                }
            )
            await asyncio.sleep(0.05)

        if len(results) > 5:
            yield await _sse_event(
                {
                    "ts": _now(),
                    "level": "info",
                    "source": "bangumi",
                    "msg": f"  ... 及其余 {len(results) - 5} 条",
                }
            )

        yield await _sse_event(
            {
                "ts": _now(),
                "level": "success",
                "source": "bangumi",
                "msg": f"完成！共 {len(results)} 条 ({elapsed}ms)",
            }
        )
        db.add_crawl_record("bangumi", keyword, len(results), elapsed)
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        yield await _sse_event({"ts": _now(), "level": "error", "source": "bangumi", "msg": f"失败: {e}"})
        db.add_crawl_record("bangumi", keyword, 0, elapsed, "error", str(e))


@router.get("/stream", summary="SSE crawl stream")
async def crawl_stream(
    source: str = Query(..., description="Source: subsplease, nyaa, bangumi, all"),
    keyword: str = Query("", description="Search keyword"),
    quality: int = Query(1080, description="SubsPlease quality"),
    page: int = Query(1, ge=1, description="Page number (Nyaa only)"),
):
    async def generate():
        yield await _sse_event(
            {
                "ts": _now(),
                "level": "info",
                "source": "system",
                "msg": f"抓取任务启动 [source={source}, keyword={keyword or '(默认)'}, page={page}]",
            }
        )

        sources_to_crawl = []
        if source in ("subsplease", "all"):
            sources_to_crawl.append("subsplease")
        if source in ("nyaa", "all"):
            sources_to_crawl.append("nyaa")
        if source in ("bangumi", "all"):
            sources_to_crawl.append("bangumi")

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

        yield await _sse_event(
            {"ts": _now(), "level": "success", "source": "system", "msg": "所有抓取任务完成"}
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/history", summary="Get crawl history")
async def crawl_history(limit: int = Query(50, ge=1, le=200)):
    return db.get_crawl_history(limit)
