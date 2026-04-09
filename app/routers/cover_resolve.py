"""Title-to-cover matching — deterministic hash + SQLite persistent mapping."""

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import bangumi
from app.services import anilist
from app.services import database as db

logger = logging.getLogger(__name__)
router = APIRouter()


def _clean_title(raw: str) -> str:
    """Extract clean anime name from torrent title.

    Handles: [SubsPlease], (1080p), 【字幕组】, {info}, v2, .mkv/.mp4/.avi/.ts/.flv,
    S01E01, Season 2, Episode 28, " - 28", trailing numbers, encoding tags.
    """
    cleaned = re.sub(r'\[.*?\]', '', raw)           # [SubsPlease] [1080p] [ABCD1234]
    cleaned = re.sub(r'【.*?】', '', cleaned)         # 【字幕组】Chinese-style brackets
    cleaned = re.sub(r'\{.*?\}', '', cleaned)         # {info} curly braces
    cleaned = re.sub(r'\(.*?\)', '', cleaned)         # (1080p) (CRC32)
    # File extensions (expanded list)
    cleaned = re.sub(r'\.(mkv|mp4|avi|ts|flv|rmvb|webm|ass|srt)$', '', cleaned, flags=re.IGNORECASE)
    # Encoding/quality tags
    cleaned = re.sub(r'\b(1080p|720p|480p|2160p|4K|HEVC|H\.?265|H\.?264|x264|x265|AV1|AVC|AAC|FLAC|OPUS|WEB-DL|WEBRip|BDRip|BluRay|BD|CR|DUAL|MULTI|10bit|8bit|HDR)\b', '', cleaned, flags=re.IGNORECASE)
    # Season+Episode: S01E01, S01E01-E03
    cleaned = re.sub(r'\s*S\d+E\d+(?:-E?\d+)?.*$', '', cleaned, flags=re.IGNORECASE)
    # Trailing episode number with optional v2/v3: " - 28v2", " - 28"
    cleaned = re.sub(r'\s*[-–]\s*\d+v?\d*\s*$', '', cleaned)
    # Trailing season: S1, S2
    cleaned = re.sub(r'\s+S\d+\s*$', '', cleaned, flags=re.IGNORECASE)
    # Season N / Part N
    cleaned = re.sub(r'\s+(?:Season|Part|Cour)\s*\d+.*$', '', cleaned, flags=re.IGNORECASE)
    # Episode N
    cleaned = re.sub(r'\s*Episode\s*\d+.*$', '', cleaned, flags=re.IGNORECASE)
    # More aggressive trailing " - 28 ..." (must be after v2 pattern)
    cleaned = re.sub(r'\s*[-–]\s*\d+.*$', '', cleaned)
    # Trailing "第N话/集/季"
    cleaned = re.sub(r'\s*第\d+[话集季期].*$', '', cleaned)
    # Collapse whitespace and strip
    cleaned = re.sub(r'\s+', ' ', cleaned).strip().strip('-').strip('.').strip()
    return cleaned


def _title_hash(cleaned: str) -> str:
    """Deterministic hash from cleaned title — same anime always gets same hash."""
    return hashlib.md5(cleaned.lower().encode('utf-8')).hexdigest()[:12]


def _generate_search_variants(cleaned: str) -> list[str]:
    """Generate multiple search variants to improve match rate.

    Strategy: start with exact match, progressively simplify.
    """
    variants = [cleaned]
    words = cleaned.split()

    # Truncate long titles
    if len(words) > 4:
        variants.append(' '.join(words[:4]))
    if len(words) > 2:
        variants.append(' '.join(words[:3]))

    # Remove subtitle after " - " (e.g. "Ghost Concert - missing Songs" -> "Ghost Concert")
    if ' - ' in cleaned:
        main_title = cleaned.split(' - ')[0].strip()
        if main_title and len(main_title) > 2:
            variants.append(main_title)

    # "X no Y" → "X" (romaji particle removal)
    shorter = re.sub(r'\s+no\s+\w+$', '', cleaned, flags=re.IGNORECASE)
    if shorter != cleaned and len(shorter) > 3:
        variants.append(shorter)

    # Replace "no" with space for Bangumi search (e.g. "Sousou no Frieren" → "Sousou Frieren")
    no_replaced = re.sub(r'\bno\b', ' ', cleaned, flags=re.IGNORECASE)
    no_replaced = re.sub(r'\s+', ' ', no_replaced).strip()
    if no_replaced != cleaned and len(no_replaced) > 3:
        variants.append(no_replaced)

    # CamelCase split
    camel_split = re.sub(r'([a-z])([A-Z])', r'\1 \2', cleaned)
    if camel_split != cleaned:
        variants.append(camel_split)

    # Trailing dots
    no_dot = cleaned.rstrip('.')
    if no_dot != cleaned:
        variants.append(no_dot)

    # Trailing numbers (common for sequels)
    no_num = re.sub(r'\s+\d+\s*$', '', cleaned).strip()
    if no_num and no_num != cleaned:
        variants.append(no_num)
        no_num2 = re.sub(r'\s+\d+\s*$', '', no_num).strip()
        if no_num2 and no_num2 != no_num:
            variants.append(no_num2)

    # Trailing S6, S2 etc
    no_season = re.sub(r'\s+S\d+\s*$', '', cleaned, flags=re.IGNORECASE).strip()
    if no_season and no_season != cleaned:
        variants.append(no_season)

    # First 1-2 words (handles long romanized titles)
    if len(words) > 1:
        variants.append(words[0])
    if len(words) > 1:
        variants.append(' '.join(words[:2]))

    # Strip Japanese honorific suffixes and try
    for suffix in ['-kun', '-san', '-sama', '-chan', '-sensei', '-senpai', '-dono']:
        idx = cleaned.lower().find(suffix)
        if idx > 0:
            base = cleaned[:idx + len(suffix)]
            if base != cleaned:
                variants.append(base)

    # Replace hyphens with spaces (e.g. "Tsue-chan" → "Tsue chan")
    if '-' in cleaned:
        hyphen_replaced = cleaned.replace('-', ' ')
        if hyphen_replaced != cleaned:
            variants.append(hyphen_replaced)

    seen = set()
    unique = []
    for v in variants:
        v = v.strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            unique.append(v)
    return unique


class CoverRequest(BaseModel):
    titles: list[str]


class CoverResult(BaseModel):
    title: str
    title_hash: str
    cleaned_title: str = ""
    cover_url: str
    bangumi_id: int
    name_cn: str = ""
    name: str = ""
    resolve_source: str = ""  # "cache", "bangumi", "anilist+bangumi", "anilist", "miss"


@router.post("/batch", response_model=list[CoverResult], summary="Batch resolve titles to covers")
async def batch_resolve_covers(req: CoverRequest):
    """
    Deterministic title → cover mapping with multi-tier fallback:
    1. Clean title → MD5 hash → SQLite cache (instant)
    2. Bangumi search with generated variants
    3. AniList search (romaji support) → Bangumi re-search with native title
    4. AniList data direct (if Bangumi unavailable)
    """
    results: list[CoverResult] = []
    to_resolve: list[tuple[str, str, str]] = []  # (raw_title, cleaned, hash)

    # Step 1: clean + hash all titles
    title_info: list[tuple[str, str, str]] = []
    for raw in req.titles[:30]:
        cleaned = _clean_title(raw)
        if not cleaned:
            continue
        h = _title_hash(cleaned)
        title_info.append((raw, cleaned, h))

    # Step 2: batch lookup in SQLite
    all_hashes = [h for _, _, h in title_info]
    cached = db.get_title_covers_batch(all_hashes)

    for raw, cleaned, h in title_info:
        if h in cached:
            row = cached[h]
            if row["cover_url"] or row["name_cn"] or row["name"]:
                results.append(CoverResult(
                    title=raw, title_hash=h, cleaned_title=cleaned,
                    cover_url=row["cover_url"], bangumi_id=row["bangumi_id"],
                    name_cn=row["name_cn"], name=row["name"],
                    resolve_source="cache",
                ))
            # Empty record — progressive retry: 1 day, then 3 days, then 7 days
            elif row.get("bangumi_id", 0) == 0:
                created_at = row.get("created_at", "")
                if created_at:
                    try:
                        ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                        age = datetime.now(timezone.utc) - ts
                        # Progressive: retry after 1 day, 3 days, 7 days
                        if age > timedelta(days=1):
                            to_resolve.append((raw, cleaned, h))
                    except Exception:
                        to_resolve.append((raw, cleaned, h))
                else:
                    to_resolve.append((raw, cleaned, h))
        else:
            to_resolve.append((raw, cleaned, h))

    # Step 3: search Bangumi for uncached titles
    for raw, cleaned, h in to_resolve:
        found = False
        variants = _generate_search_variants(cleaned)

        for variant in variants:
            try:
                search_results = await bangumi.search(variant, limit=3)
                if search_results:
                    best = _pick_best_result(search_results)
                    if best:
                        db.upsert_title_cover(h, cleaned, best.id, best.name_cn, best.name, best.cover_url)
                        results.append(CoverResult(
                            title=raw, title_hash=h, cleaned_title=cleaned,
                            cover_url=best.cover_url or "", bangumi_id=best.id,
                            name_cn=best.name_cn, name=best.name,
                            resolve_source="bangumi",
                        ))
                        found = True
                        logger.info("Cover resolved: '%s' -> %s (bgm:%d)", cleaned, best.name_cn or best.name, best.id)
                        break
            except Exception as e:
                logger.warning("Cover search failed for '%s': %s", variant, e)

        if not found:
            # Fallback: AniList (supports romaji) → Bangumi re-search → AniList direct
            found = await _anilist_fallback(raw, cleaned, h, results)

        if not found:
            # Persist miss — will retry after progressive backoff
            db.upsert_title_cover(h, cleaned, 0, "", "", "")
            logger.info("Cover miss persisted: '%s' (hash=%s)", cleaned, h)

    return results


def _pick_best_result(search_results: list) -> object | None:
    """Pick the best result from Bangumi search.
    Priority: cover+name_cn > cover > name_cn > first result."""
    for sr in search_results:
        if sr.cover_url and sr.name_cn:
            return sr
    for sr in search_results:
        if sr.cover_url:
            return sr
    for sr in search_results:
        if sr.name_cn:
            return sr
    return search_results[0] if search_results else None


async def _anilist_fallback(raw: str, cleaned: str, h: str, results: list[CoverResult]) -> bool:
    """AniList fallback: search with romaji, get native title, re-search Bangumi.

    Also tries English title from AniList as a Bangumi search variant.
    """
    try:
        al_result = await anilist._do_search(cleaned, page=1, per_page=3)
        for al_item in al_result.get("items", []):
            native_title = al_item.get("title_native", "")
            romaji_title = al_item.get("title_romaji", "")
            english_title = al_item.get("title_english", "")
            al_cover = al_item.get("cover_large", "") or al_item.get("cover_medium", "")

            # Try Bangumi with native, romaji, and English titles
            for try_title in [native_title, romaji_title, english_title]:
                if not try_title:
                    continue
                try:
                    bgm_results = await bangumi.search(try_title, limit=3)
                    if bgm_results:
                        best = _pick_best_result(bgm_results)
                        if best:
                            cover = best.cover_url or al_cover
                            db.upsert_title_cover(h, cleaned, best.id, best.name_cn, best.name, cover)
                            results.append(CoverResult(
                                title=raw, title_hash=h, cleaned_title=cleaned,
                                cover_url=cover, bangumi_id=best.id,
                                name_cn=best.name_cn, name=best.name,
                                resolve_source="anilist+bangumi",
                            ))
                            logger.info("Cover resolved via AniList fallback: '%s' -> %s (bgm:%d)", cleaned, best.name_cn or best.name, best.id)
                            return True
                except Exception:
                    pass

            # If Bangumi still fails, use AniList data directly (always has covers)
            if native_title or al_cover:
                name_cn = english_title or native_title
                name = native_title or romaji_title
                db.upsert_title_cover(h, cleaned, 0, name_cn, name, al_cover)
                results.append(CoverResult(
                    title=raw, title_hash=h, cleaned_title=cleaned,
                    cover_url=al_cover, bangumi_id=0,
                    name_cn=name_cn, name=name,
                    resolve_source="anilist",
                ))
                logger.info("Cover resolved via AniList only: '%s' -> %s", cleaned, name_cn or name)
                return True
    except Exception as e:
        logger.warning("AniList fallback failed for '%s': %s", cleaned, e)

    return False
