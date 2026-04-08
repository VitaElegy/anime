"""Title-to-cover matching — deterministic hash + SQLite persistent mapping."""

import hashlib
import logging
import re

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import bangumi
from app.services import anilist
from app.services import database as db

logger = logging.getLogger(__name__)
router = APIRouter()


def _clean_title(raw: str) -> str:
    """Extract clean anime name from torrent title."""
    cleaned = re.sub(r'\[.*?\]', '', raw)
    cleaned = re.sub(r'\(.*?\)', '', cleaned)
    cleaned = re.sub(r'\.(mkv|mp4|avi)$', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b(1080p|720p|480p|HEVC|x264|x265|AVC|AAC|FLAC|WEB-DL|BDRip|BD|CR|DUAL)\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*S\d+E\d+.*$', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*[-–]\s*\d+v?\d*\s*$', '', cleaned)
    cleaned = re.sub(r'\s+S\d+\s*$', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+Season\s*\d+.*$', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*Episode\s*\d+.*$', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*[-–]\s*\d+.*$', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip().strip('-').strip('.').strip()
    return cleaned


def _title_hash(cleaned: str) -> str:
    """Deterministic hash from cleaned title — same anime always gets same hash."""
    return hashlib.md5(cleaned.lower().encode('utf-8')).hexdigest()[:12]


def _generate_search_variants(cleaned: str) -> list[str]:
    """Generate multiple search variants to improve match rate."""
    variants = [cleaned]
    words = cleaned.split()
    if len(words) > 4:
        variants.append(' '.join(words[:4]))
    if len(words) > 2:
        variants.append(' '.join(words[:3]))

    # Remove subtitle after " - " (e.g. "Ghost Concert - missing Songs" -> "Ghost Concert")
    if ' - ' in cleaned:
        main_title = cleaned.split(' - ')[0].strip()
        if main_title and len(main_title) > 2:
            variants.append(main_title)

    shorter = re.sub(r'\s+no\s+\w+$', '', cleaned, flags=re.IGNORECASE)
    if shorter != cleaned and len(shorter) > 3:
        variants.append(shorter)
    no_dot = cleaned.rstrip('.')
    if no_dot != cleaned:
        variants.append(no_dot)
    camel_split = re.sub(r'([a-z])([A-Z])', r'\1 \2', cleaned)
    if camel_split != cleaned:
        variants.append(camel_split)
    no_num = re.sub(r'\s+\d+\s*$', '', cleaned).strip()
    if no_num and no_num != cleaned:
        variants.append(no_num)
        no_num2 = re.sub(r'\s+\d+\s*$', '', no_num).strip()
        if no_num2 and no_num2 != no_num:
            variants.append(no_num2)

    # Remove trailing S6, S2 etc that weren't caught by _clean_title
    no_season = re.sub(r'\s+S\d+\s*$', '', cleaned, flags=re.IGNORECASE).strip()
    if no_season and no_season != cleaned:
        variants.append(no_season)

    # Take first word(s) — handles long Japanese romanized titles
    if len(words) > 1:
        variants.append(words[0])  # e.g. "Haibara-kun" from "Haibara-kun no ..."
    if len(words) > 1:
        variants.append(' '.join(words[:2]))

    # Strip "-kun", "-san", "-sama" suffix and try
    for suffix in ['-kun', '-san', '-sama', '-chan', '-sensei']:
        if cleaned.lower().find(suffix) > 0:
            base = cleaned[:cleaned.lower().find(suffix) + len(suffix)]
            if base != cleaned:
                variants.append(base)

    seen = set()
    unique = []
    for v in variants:
        v = v.strip()
        if v and v not in seen:
            seen.add(v)
            unique.append(v)
    return unique


class CoverRequest(BaseModel):
    titles: list[str]


class CoverResult(BaseModel):
    title: str
    title_hash: str
    cover_url: str
    bangumi_id: int
    name_cn: str = ""
    name: str = ""


@router.post("/batch", response_model=list[CoverResult], summary="Batch resolve titles to covers")
async def batch_resolve_covers(req: CoverRequest):
    """
    Deterministic title → cover mapping.
    1. Clean title → MD5 hash
    2. Check SQLite persistent map (instant, 100% hit after first resolve)
    3. If miss → search Bangumi with variants → persist result to DB
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
                # Return result even without cover — Chinese name is still useful
                results.append(CoverResult(
                    title=raw, title_hash=h,
                    cover_url=row["cover_url"], bangumi_id=row["bangumi_id"],
                    name_cn=row["name_cn"], name=row["name"],
                ))
            # Empty record with no name and no cover — allow re-resolve after 7 days
            elif row.get("bangumi_id", 0) == 0:
                created_at = row.get("created_at", "")
                if created_at:
                    from datetime import datetime, timedelta, timezone
                    try:
                        ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                        if datetime.now(timezone.utc) - ts > timedelta(days=7):
                            to_resolve.append((raw, cleaned, h))
                    except Exception:
                        pass
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
                    # Priority: 1) has cover+name_cn, 2) has cover, 3) has name_cn, 4) first result
                    best = None
                    for sr in search_results:
                        if sr.cover_url and sr.name_cn:
                            best = sr
                            break
                    if not best:
                        for sr in search_results:
                            if sr.cover_url:
                                best = sr
                                break
                    if not best:
                        for sr in search_results:
                            if sr.name_cn:
                                best = sr
                                break
                    if not best:
                        best = search_results[0]

                    if best:
                        # Persist to SQLite — never search again
                        db.upsert_title_cover(h, cleaned, best.id, best.name_cn, best.name, best.cover_url)
                        results.append(CoverResult(
                            title=raw, title_hash=h,
                            cover_url=best.cover_url or "", bangumi_id=best.id,
                            name_cn=best.name_cn, name=best.name,
                        ))
                        found = True
                        logger.info("Cover resolved: '%s' -> %s (bgm:%d)", cleaned, best.name_cn or best.name, best.id)
                        break
            except Exception as e:
                logger.warning("Cover search failed for '%s': %s", variant, e)

        if not found:
            # Fallback: use AniList (supports romaji) to find Japanese/native title,
            # then re-search Bangumi with the native title
            try:
                al_result = await anilist._do_search(cleaned, page=1, per_page=3)
                for al_item in al_result.get("items", []):
                    native_title = al_item.get("title_native", "")
                    romaji_title = al_item.get("title_romaji", "")
                    al_cover = al_item.get("cover_large", "") or al_item.get("cover_medium", "")

                    # Try Bangumi with native (Japanese) title
                    for try_title in [native_title, romaji_title]:
                        if not try_title:
                            continue
                        try:
                            bgm_results = await bangumi.search(try_title, limit=3)
                            if bgm_results:
                                best = bgm_results[0]
                                for sr in bgm_results:
                                    if sr.cover_url and sr.name_cn:
                                        best = sr
                                        break
                                db.upsert_title_cover(h, cleaned, best.id, best.name_cn, best.name, best.cover_url or al_cover)
                                results.append(CoverResult(
                                    title=raw, title_hash=h,
                                    cover_url=best.cover_url or al_cover, bangumi_id=best.id,
                                    name_cn=best.name_cn, name=best.name,
                                ))
                                found = True
                                logger.info("Cover resolved via AniList fallback: '%s' -> %s (bgm:%d)", cleaned, best.name_cn or best.name, best.id)
                                break
                        except Exception:
                            pass
                    if found:
                        break

                    # If Bangumi still fails, use AniList data directly
                    if not found and (native_title or al_cover):
                        name_cn = al_item.get("title_english", "") or native_title
                        name = native_title or romaji_title
                        db.upsert_title_cover(h, cleaned, 0, name_cn, name, al_cover)
                        results.append(CoverResult(
                            title=raw, title_hash=h,
                            cover_url=al_cover, bangumi_id=0,
                            name_cn=name_cn, name=name,
                        ))
                        found = True
                        logger.info("Cover resolved via AniList only: '%s' -> %s", cleaned, name_cn or name)
                        break
            except Exception as e:
                logger.warning("AniList fallback failed for '%s': %s", cleaned, e)

        if not found:
            # Persist miss — won't search again (can be manually updated)
            db.upsert_title_cover(h, cleaned, 0, "", "", "")
            logger.info("Cover miss persisted: '%s' (hash=%s)", cleaned, h)

    return results
