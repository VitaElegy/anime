"""Search routes — Nyaa, SubsPlease, aggregated, with Chinese keyword support."""

import asyncio
import re

from fastapi import APIRouter, Query

from app.models import SearchResult, TorrentItem
from app.services import nyaa, subsplease, bangumi
from app.services import database as db

router = APIRouter()


def _has_chinese(text: str) -> bool:
    return bool(re.search(r'[\u4e00-\u9fff]', text))


def _has_japanese(text: str) -> bool:
    return bool(re.search(r'[\u3040-\u309f\u30a0-\u30ff]', text))


async def _translate_keyword(keyword: str) -> list[str]:
    """
    Translate Chinese/Japanese keyword to search-friendly terms.
    Strategy:
    1. Check local SQLite mapping (reverse lookup: name_cn -> cleaned_title)
    2. Search Bangumi for romanized/English alternatives
    3. Return all viable search terms
    """
    alternatives = set()
    alternatives.add(keyword)

    # Strategy 1: Local DB reverse lookup (instant, best quality)
    import sqlite3
    try:
        conn = sqlite3.connect(str(db.DB_PATH))
        conn.row_factory = sqlite3.Row
        # Search name_cn LIKE keyword
        rows = conn.execute(
            "SELECT cleaned_title, name, name_cn FROM title_cover_map WHERE name_cn LIKE ? OR name LIKE ? LIMIT 10",
            (f"%{keyword}%", f"%{keyword}%")
        ).fetchall()
        for row in rows:
            if row["cleaned_title"]:
                alternatives.add(row["cleaned_title"])
            if row["name"]:
                alternatives.add(row["name"])
        conn.close()
    except Exception:
        pass

    # Strategy 2: Bangumi search
    try:
        results = await bangumi.search(keyword, limit=3)
        for r in results:
            if r.name:
                alternatives.add(r.name)
                # Extract English words from name (e.g. "Sousou no Frieren" -> try "Frieren")
                eng_words = re.findall(r'[A-Za-z]{3,}', r.name)
                for w in eng_words:
                    alternatives.add(w)
            if r.name_cn and r.name_cn != keyword:
                alternatives.add(r.name_cn)
    except Exception:
        pass

    # Remove the original if we have better alternatives
    result = list(alternatives)
    return result


@router.get("/nyaa", response_model=SearchResult, summary="Search Nyaa.land")
async def search_nyaa(
    q: str = Query(..., description="Search keyword"),
    page: int = Query(1, ge=1, description="Page number"),
    filter: int = Query(0, ge=0, le=2, alias="filter", description="0=No filter, 1=No remakes, 2=Trusted only"),
    category: str = Query("1_0", description="Category code"),
):
    if _has_chinese(q) or _has_japanese(q):
        alts = await _translate_keyword(q)
        # Prioritize ASCII-only terms for Nyaa
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


@router.get("/all", response_model=list[SearchResult], summary="Aggregated search across all sources")
async def search_all(q: str = Query(..., description="Search keyword")):
    if _has_chinese(q) or _has_japanese(q):
        alts = await _translate_keyword(q)
        ascii_alts = [a for a in alts if not _has_chinese(a) and not _has_japanese(a)]
        nyaa_q = ascii_alts[0] if ascii_alts else q

        async def _search_nyaa():
            try:
                return await nyaa.search_html(nyaa_q)
            except Exception:
                return SearchResult(items=[], total=0, source="nyaa")

        async def _search_sp():
            items: list[TorrentItem] = []
            seen = set()
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

        nyaa_result, sp_result = await asyncio.gather(_search_nyaa(), _search_sp())
        return [nyaa_result, sp_result]

    nyaa_result, sp_result = await asyncio.gather(
        nyaa.search_html(q),
        subsplease.search(keyword=q),
        return_exceptions=True,
    )
    results = []
    for r in (nyaa_result, sp_result):
        if isinstance(r, Exception):
            results.append(SearchResult(items=[], total=0, source="error"))
        else:
            results.append(r)
    return results
