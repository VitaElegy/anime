"""Search routes — multi-source aggregation with Chinese keyword support.

Sources (all run in parallel via asyncio.gather):
- Nyaa (英日资源主站)
- SubsPlease (SubsPlease 英字)
- Mikan (蜜柑计划 — 中文字幕组聚合)
- AnimeGarden (动漫花园 + moe 聚合 JSON API)

Deduplication strategy:
  1. If info_hash is present (40-char BT hash), it's the primary dedup key.
  2. Otherwise fall back to a normalized-title key.

Ranking:
  seeders DESC, then fansub priority (中文字幕组优先), then publish-date DESC.
"""

import asyncio
import logging
import re

from fastapi import APIRouter, Query

from app.models import SearchResult, TorrentItem
from app.services import anime_garden, bangumi, mikan, nyaa, subsplease
from app.services import database as db

router = APIRouter()

logger = logging.getLogger(__name__)

# Fansubs that usually ship Chinese subtitles — boosted when user types Chinese.
_CHINESE_FANSUB_HINTS = {
    "喵萌奶茶屋",
    "LoliHouse",
    "拨雪寻春",
    "桜都字幕组",
    "DBD",
    "ANi",
    "云光字幕组",
    "北宇治字幕组",
    "爱恋",
    "霜庭云花",
    "漫猫",
    "Prejudice-Studio",
    "Fatum Fatalis",
    "Skymoon-Raws",
    "豌豆",
    "天月動漫",
    "晚街与灯",
    "VCB-Studio",
    "Kirara",
    "沸羊羊",
}


def _has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _has_japanese(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text))


async def _translate_keyword(keyword: str) -> list[str]:
    """Translate Chinese/Japanese keyword to search-friendly terms."""
    alternatives: set[str] = set()
    alternatives.add(keyword)

    # Strategy 1: Local DB reverse lookup (instant, best quality)
    try:
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT cleaned_title, name, name_cn FROM title_cover_map WHERE name_cn LIKE ? OR name LIKE ? LIMIT 10",
                (f"%{keyword}%", f"%{keyword}%"),
            ).fetchall()
            for row in rows:
                if row["cleaned_title"]:
                    alternatives.add(row["cleaned_title"])
                if row["name"]:
                    alternatives.add(row["name"])
    except Exception:
        pass

    # Strategy 2: Bangumi search
    try:
        results = await bangumi.search(keyword, limit=3)
        for r in results:
            if r.name:
                alternatives.add(r.name)
                eng_words = re.findall(r"[A-Za-z]{3,}", r.name)
                for w in eng_words:
                    alternatives.add(w)
            if r.name_cn and r.name_cn != keyword:
                alternatives.add(r.name_cn)
    except Exception:
        pass

    return list(alternatives)


def _normalize_title_key(title: str) -> str:
    """Normalize a torrent title for title-based deduping when info_hash is missing."""
    # Strip bracketed tags like [GROUP], [1080p], etc and whitespace
    t = re.sub(r"[\[\(（][^\]\)）]*[\]\)）]", "", title)
    t = re.sub(r"[^\w\u4e00-\u9fff]+", "", t).lower()
    return t[:80]


def _score_fansub(name: str) -> int:
    if not name:
        return 0
    for hint in _CHINESE_FANSUB_HINTS:
        if hint in name:
            return 1
    return 0


def _merge_and_rank(results: list[SearchResult], prefer_chinese: bool) -> list[TorrentItem]:
    """Merge items across sources, dedupe by info_hash then title, rank by seeders."""
    seen_hashes: set[str] = set()
    seen_titles: set[str] = set()
    merged: list[TorrentItem] = []

    # Source priority when dedupe conflicts: prefer Chinese sources when the user
    # searched Chinese, else keep existing order.
    source_priority_cn = {"mikan": 0, "anime_garden": 1, "nyaa": 2, "subsplease": 3}
    source_priority_en = {"nyaa": 0, "subsplease": 1, "mikan": 2, "anime_garden": 3}
    prio = source_priority_cn if prefer_chinese else source_priority_en

    # Flatten
    flat: list[TorrentItem] = []
    for r in results:
        flat.extend(r.items)

    # Sort so preferred source wins dedupe
    flat.sort(key=lambda it: prio.get(it.source, 99))

    for it in flat:
        h = (it.info_hash or "").lower()
        tk = _normalize_title_key(it.title)
        if h and h in seen_hashes:
            continue
        if not h and tk and tk in seen_titles:
            continue
        if h:
            seen_hashes.add(h)
        if tk:
            seen_titles.add(tk)
        merged.append(it)

    # Final ranking: seeders DESC, then Chinese fansub boost, then date DESC
    def _rank(it: TorrentItem):
        return (
            -(it.seeders or 0),
            -_score_fansub(it.fansub) if prefer_chinese else 0,
            it.date or "",
        )

    merged.sort(key=_rank)
    return merged


# ---------------------------------------------------------------------------
# Single-source endpoints (back-compat)
# ---------------------------------------------------------------------------


@router.get("/nyaa", response_model=SearchResult, summary="Search Nyaa.land")
async def search_nyaa(
    q: str = Query(..., description="Search keyword"),
    page: int = Query(1, ge=1, description="Page number"),
    filter: int = Query(
        0, ge=0, le=2, alias="filter", description="0=No filter, 1=No remakes, 2=Trusted only"
    ),
    category: str = Query("1_0", description="Category code"),
):
    if _has_chinese(q) or _has_japanese(q):
        alts = await _translate_keyword(q)
        ascii_alts = [a for a in alts if not _has_chinese(a) and not _has_japanese(a)]
        non_ascii = [a for a in alts if a not in ascii_alts]
        search_terms = (ascii_alts + non_ascii)[:4]

        all_items: list[TorrentItem] = []
        seen = set()
        for term in search_terms:
            try:
                result = await nyaa.search_html(term, page=page, filter_=filter, category=category)
                for item in result.items:
                    if item.title not in seen:
                        seen.add(item.title)
                        all_items.append(item)
            except Exception:
                pass
        return SearchResult(items=all_items, total=len(all_items), source="nyaa")

    return await nyaa.search_html(q, page=page, filter_=filter, category=category)


@router.get("/subsplease", response_model=SearchResult, summary="Search SubsPlease RSS")
async def search_subsplease(
    q: str = Query("", description="Filter keyword (empty = all)"),
    quality: int = Query(1080, description="Video quality: 1080, 720, or 480"),
):
    if q and (_has_chinese(q) or _has_japanese(q)):
        alts = await _translate_keyword(q)
        all_items: list[TorrentItem] = []
        seen = set()
        for alt in alts[:5]:
            try:
                result = await subsplease.search(keyword=alt, quality=quality)
                for item in result.items:
                    if item.title not in seen:
                        seen.add(item.title)
                        all_items.append(item)
            except Exception:
                pass
        return SearchResult(items=all_items, total=len(all_items), source="subsplease")

    return await subsplease.search(keyword=q, quality=quality)


@router.get("/mikan", response_model=SearchResult, summary="Search Mikan Project (中文字幕组)")
async def search_mikan(q: str = Query(..., description="Search keyword")):
    return await mikan.search_html(q)


@router.get("/anime_garden", response_model=SearchResult, summary="Search AnimeGarden aggregator")
async def search_anime_garden(
    q: str = Query(..., description="Search keyword"),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
):
    return await anime_garden.search(q, page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# Unified multi-source aggregated endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/all",
    response_model=list[SearchResult],
    summary="Aggregated search across Nyaa / SubsPlease / Mikan / AnimeGarden",
)
async def search_all(q: str = Query(..., description="Search keyword")):
    if not q.strip():
        return []

    is_cn_jp = _has_chinese(q) or _has_japanese(q)

    # Build keyword variants for Nyaa/SubsPlease (they prefer ASCII)
    ascii_alts: list[str] = []
    if is_cn_jp:
        alts = await _translate_keyword(q)
        ascii_alts = [a for a in alts if not _has_chinese(a) and not _has_japanese(a)]
    nyaa_q = ascii_alts[0] if ascii_alts else q

    async def _search_nyaa() -> SearchResult:
        try:
            return await nyaa.search_html(nyaa_q)
        except Exception:
            return SearchResult(items=[], total=0, source="nyaa")

    async def _search_sp() -> SearchResult:
        if is_cn_jp:
            items: list[TorrentItem] = []
            seen: set[str] = set()
            alts = [nyaa_q] + ascii_alts + [q]
            for alt in alts[:4]:
                try:
                    r = await subsplease.search(keyword=alt)
                    for item in r.items:
                        if item.title not in seen:
                            seen.add(item.title)
                            items.append(item)
                except Exception:
                    pass
            return SearchResult(items=items, total=len(items), source="subsplease")
        try:
            return await subsplease.search(keyword=q)
        except Exception:
            return SearchResult(items=[], total=0, source="subsplease")

    async def _search_mikan() -> SearchResult:
        try:
            return await mikan.search_html(q)
        except Exception:
            return SearchResult(items=[], total=0, source="mikan")

    async def _search_garden() -> SearchResult:
        try:
            return await anime_garden.search(q, page_size=30)
        except Exception:
            return SearchResult(items=[], total=0, source="anime_garden")

    nyaa_r, sp_r, mikan_r, garden_r = await asyncio.gather(
        _search_nyaa(),
        _search_sp(),
        _search_mikan(),
        _search_garden(),
    )

    return [nyaa_r, sp_r, mikan_r, garden_r]


@router.get(
    "/unified",
    response_model=SearchResult,
    summary="Unified search — multi-source aggregated, deduped, and ranked",
)
async def search_unified(
    q: str = Query(..., description="Search keyword"),
    limit: int = Query(80, ge=1, le=200),
):
    """Returns a single merged result list from all sources (dedup + ranked)."""
    results = await search_all(q=q)  # reuse, already SearchResult[]
    prefer_cn = _has_chinese(q) or _has_japanese(q)
    merged = _merge_and_rank(results, prefer_chinese=prefer_cn)[:limit]
    return SearchResult(items=merged, total=len(merged), source="unified")


# ---------------------------------------------------------------------------
# Frontend-friendly endpoints (SearchPage v2)
#
# These two endpoints return JSON shaped exactly like the new SearchPage.tsx
# expects, so the frontend does not need to do any remapping:
#
#   GET /api/search/anime?q=…     -> { anime: [ {id,title,coverImage,...} ] }
#   GET /api/search/torrents?q=…  -> { torrents: [ {title,size,seeders,...} ] }
#
# Both endpoints accept the raw Chinese/Japanese keyword untouched.
# ---------------------------------------------------------------------------


@router.get("/anime", summary="Anime metadata search (Bangumi, frontend-shaped)")
async def search_anime_for_frontend(
    q: str = Query(..., description="Chinese / Japanese / romaji keyword, passed verbatim"),
    limit: int = Query(12, ge=1, le=30),
):
    """Return AnimeResult[] shaped for SearchPage.tsx."""
    q = (q or "").strip()
    if not q:
        return {"anime": []}

    try:
        meta_list = await bangumi.search(q, limit=limit)
    except Exception as e:  # noqa: BLE001
        logger.warning("bangumi search failed for %r: %s", q, e)
        return {"anime": [], "error": "bangumi_unavailable"}

    out: list[dict] = []
    for m in meta_list:
        out.append(
            {
                "id": str(m.id),
                "title": m.name_cn or m.name or q,
                "titleOriginal": m.name if (m.name and m.name != m.name_cn) else "",
                "coverImage": getattr(m, "cover_url", "") or "",
                "description": (getattr(m, "summary", "") or "")[:200],
                "year": "",
                "score": float(getattr(m, "score", 0) or 0) or None,
                "source": "Bangumi",
            }
        )
    return {"anime": out, "total": len(out)}


@router.get("/torrents", summary="Torrent aggregated search (frontend-shaped)")
async def search_torrents_for_frontend(
    q: str = Query(..., description="Chinese / Japanese / romaji keyword, passed verbatim"),
    limit: int = Query(80, ge=1, le=200),
):
    """Multi-source aggregated torrent search shaped for SearchPage.tsx.

    Each returned torrent has: title, size, seeders, source, fansub, link,
    pubDate, info_hash — matching TorrentResult in the frontend.
    """
    q = (q or "").strip()
    if not q:
        return {"torrents": []}

    results = await search_all(q=q)
    prefer_cn = _has_chinese(q) or _has_japanese(q)
    merged = _merge_and_rank(results, prefer_chinese=prefer_cn)[:limit]

    # Map raw source code → friendly label
    source_label = {
        "mikan": "Mikan",
        "anime_garden": "AnimeGarden",
        "nyaa": "Nyaa",
        "subsplease": "SubsPlease",
    }

    out: list[dict] = []
    for it in merged:
        link = it.magnet or it.torrent_url or it.detail_url or ""
        out.append(
            {
                "info_hash": it.info_hash or "",
                "title": it.title,
                "size": it.size or "",
                "seeders": int(it.seeders or 0),
                "source": source_label.get(it.source, it.source or "Unknown"),
                "fansub": it.fansub or "",
                "link": link,
                "pubDate": it.date or "",
            }
        )
    return {"torrents": out, "total": len(out)}
