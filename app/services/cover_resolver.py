"""Resolve torrent titles to Bangumi covers with persistent SQLite mapping."""

import hashlib
import logging
import re
import time
from datetime import UTC, datetime

from app.services import anilist, bangumi
from app.services import database as db

logger = logging.getLogger(__name__)
MISS_RETRY_SECONDS = 12 * 60 * 60


def clean_title(raw: str) -> str:
    """Extract clean anime name from torrent title."""
    cleaned = re.sub(r"\[.*?\]", "", raw)
    cleaned = re.sub(r"\(.*?\)", "", cleaned)
    cleaned = re.sub(r"\.(mkv|mp4|avi)$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(1080p|720p|480p|HEVC|x264|x265|AVC|AAC|FLAC|WEB-DL|BDRip|BD|CR|DUAL)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s*S\d+E\d+.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*[-–]\s*\d+v?\d*\s*$", "", cleaned)
    cleaned = re.sub(r"\s+S\d+\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+Season\s*\d+.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*Episode\s*\d+.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*[-–]\s*\d+.*$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip("-").strip(".").strip()
    return cleaned


def title_hash(cleaned: str) -> str:
    """Deterministic hash from cleaned title."""
    return hashlib.md5(cleaned.lower().encode("utf-8")).hexdigest()[:12]


def _generate_search_variants(cleaned: str) -> list[str]:
    variants = [cleaned]
    words = cleaned.split()
    if len(words) > 4:
        variants.append(" ".join(words[:4]))
    if len(words) > 2:
        variants.append(" ".join(words[:3]))

    if " - " in cleaned:
        main_title = cleaned.split(" - ")[0].strip()
        if main_title and len(main_title) > 2:
            variants.append(main_title)

    shorter = re.sub(r"\s+no\s+\w+$", "", cleaned, flags=re.IGNORECASE)
    if shorter != cleaned and len(shorter) > 3:
        variants.append(shorter)

    no_dot = cleaned.rstrip(".")
    if no_dot != cleaned:
        variants.append(no_dot)

    camel_split = re.sub(r"([a-z])([A-Z])", r"\1 \2", cleaned)
    if camel_split != cleaned:
        variants.append(camel_split)

    no_num = re.sub(r"\s+\d+\s*$", "", cleaned).strip()
    if no_num and no_num != cleaned:
        variants.append(no_num)
        no_num2 = re.sub(r"\s+\d+\s*$", "", no_num).strip()
        if no_num2 and no_num2 != no_num:
            variants.append(no_num2)

    no_season = re.sub(r"\s+S\d+\s*$", "", cleaned, flags=re.IGNORECASE).strip()
    if no_season and no_season != cleaned:
        variants.append(no_season)

    if len(words) > 1:
        variants.append(words[0])
        variants.append(" ".join(words[:2]))

    for suffix in ["-kun", "-san", "-sama", "-chan", "-sensei"]:
        idx = cleaned.lower().find(suffix)
        if idx > 0:
            base = cleaned[: idx + len(suffix)]
            if base != cleaned:
                variants.append(base)

    seen = set()
    ordered = []
    for variant in variants:
        variant = variant.strip()
        if variant and variant not in seen:
            seen.add(variant)
            ordered.append(variant)
    return ordered


def _created_at_epoch(row: dict | None) -> int:
    if not row:
        return 0
    value = row.get("created_at")
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return 0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp())
    return 0


def _should_retry_miss(row: dict | None, force_refresh: bool = False) -> bool:
    if row is None:
        return True
    if row.get("cover_url"):
        return False
    if force_refresh:
        return True
    created_at = _created_at_epoch(row)
    if created_at <= 0:
        return True
    return (time.time() - created_at) >= MISS_RETRY_SECONDS


def _bangumi_payload(raw: str, hashed: str, meta) -> dict:
    return {
        "title": raw,
        "title_hash": hashed,
        "cover_url": meta.cover_url,
        "bangumi_id": meta.id,
        "name_cn": meta.name_cn,
        "name": meta.name,
    }


def _pick_bangumi_best(search_results: list) -> object | None:
    for item in search_results:
        if item.cover_url:
            return item
    return None


async def _resolve_with_bangumi_variants(cleaned: str, force_refresh: bool = False):
    for variant in _generate_search_variants(cleaned):
        try:
            search_results = await bangumi.search(variant, limit=3, force_refresh=force_refresh)
        except Exception as exc:
            logger.warning("Cover search failed for '%s': %s", variant, exc)
            continue

        best = _pick_bangumi_best(search_results)
        if best is not None:
            return best

    return None


async def _resolve_with_anilist_bridge(cleaned: str, force_refresh: bool = False) -> dict | None:
    try:
        result = await anilist.search(cleaned, page=1, per_page=5, force_refresh=force_refresh)
    except Exception as exc:
        logger.warning("AniList bridge search failed for '%s': %s", cleaned, exc)
        return None

    items = result.get("items", [])
    if not items:
        return None

    preferred = next(
        (item for item in items if item.get("cover_large") or item.get("cover_medium")), items[0]
    )
    bridge_terms: list[str] = []
    for key in ("title_native", "title_english", "title_romaji", "title_preferred"):
        value = (preferred.get(key) or "").strip()
        if value and value not in bridge_terms:
            bridge_terms.append(value)

    for term in bridge_terms:
        try:
            bangumi_results = await bangumi.search(term, limit=3, force_refresh=force_refresh)
        except Exception as exc:
            logger.warning("AniList->Bangumi bridge failed for '%s': %s", term, exc)
            continue

        best = _pick_bangumi_best(bangumi_results)
        if best is not None:
            return {
                "bangumi_id": best.id,
                "name_cn": best.name_cn,
                "name": best.name,
                "cover_url": best.cover_url,
            }

    cover_url = preferred.get("cover_large") or preferred.get("cover_medium") or ""
    if not cover_url:
        return None

    return {
        "bangumi_id": 0,
        "name_cn": "",
        "name": preferred.get("title_preferred") or preferred.get("title_romaji") or cleaned,
        "cover_url": cover_url,
    }


async def resolve_titles(titles: list[str], limit: int = 30, force_refresh: bool = False) -> list[dict]:
    results: list[dict] = []
    to_resolve: list[tuple[str, str, str]] = []
    title_info: list[tuple[str, str, str]] = []

    for raw in titles[:limit]:
        cleaned = clean_title(raw)
        if not cleaned:
            continue
        hashed = title_hash(cleaned)
        title_info.append((raw, cleaned, hashed))

    cached = db.get_title_covers_batch([hashed for _, _, hashed in title_info])
    for raw, cleaned, hashed in title_info:
        row = cached.get(hashed)
        if _should_retry_miss(row, force_refresh=force_refresh):
            to_resolve.append((raw, cleaned, hashed))
            continue
        if row["cover_url"]:
            results.append(
                {
                    "title": raw,
                    "title_hash": hashed,
                    "cover_url": row["cover_url"],
                    "bangumi_id": row["bangumi_id"],
                    "name_cn": row["name_cn"],
                    "name": row["name"],
                }
            )

    for raw, cleaned, hashed in to_resolve:
        best = await _resolve_with_bangumi_variants(cleaned, force_refresh=force_refresh)
        if best is not None:
            db.upsert_title_cover(hashed, cleaned, best.id, best.name_cn, best.name, best.cover_url)
            results.append(_bangumi_payload(raw, hashed, best))
            logger.info("Cover resolved: '%s' -> %s (bgm:%d)", cleaned, best.name_cn or best.name, best.id)
            continue

        bridged = await _resolve_with_anilist_bridge(cleaned, force_refresh=force_refresh)
        if bridged is not None:
            db.upsert_title_cover(
                hashed,
                cleaned,
                bridged["bangumi_id"],
                bridged["name_cn"],
                bridged["name"],
                bridged["cover_url"],
            )
            results.append(
                {
                    "title": raw,
                    "title_hash": hashed,
                    "cover_url": bridged["cover_url"],
                    "bangumi_id": bridged["bangumi_id"],
                    "name_cn": bridged["name_cn"],
                    "name": bridged["name"],
                }
            )
            logger.info(
                "Cover resolved via AniList bridge: '%s' -> %s",
                cleaned,
                bridged["name_cn"] or bridged["name"],
            )
            continue

        if not bridged:
            db.upsert_title_cover(hashed, cleaned, 0, "", "", "")
            logger.info("Cover miss persisted: '%s' (hash=%s)", cleaned, hashed)

    return results
