"""Keyword expansion helpers for cross-language anime search.

Centralizes the Chinese/Japanese → English/Romaji expansion that used to live
in the search router so the channel aggregator can reuse it without importing
from the HTTP layer (docs/CHANNEL_ARCHITECTURE.md §1.2).
"""

from __future__ import annotations

import re

from app.services import bangumi
from app.services import database as db


def has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def has_japanese(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text))


async def expand_keywords(keyword: str) -> list[str]:
    """Expand a Chinese/Japanese keyword into search-friendly alternatives.

    Always includes the original keyword; may also return romaji/English names
    from the local title map and Bangumi, which the channel aggregator tries in
    turn so sources that only index English titles still get hits.
    """
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


def normalize_title_key(title: str) -> str:
    """Normalize a title for deduping (strip bracketed tags, non-alnum, lowercase)."""
    t = re.sub(r"[\[\(（][^\]\)）]*[\]\)）]", "", title)
    t = re.sub(r"[^\w\u4e00-\u9fff]+", "", t).lower()
    return t[:80]
