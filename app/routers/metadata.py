"""Metadata routes — Bangumi anime info, cover images, streaming platform links."""

import asyncio

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.models import AnimeMetadata, AnimeMetadataFull, StreamingLink
from app.services import bangumi, bilibili

router = APIRouter()


@router.get("/search", response_model=list[AnimeMetadata], summary="Search anime on Bangumi")
async def search_metadata(
    q: str = Query(..., description="Anime title to search"),
    limit: int = Query(25, ge=1, le=50, description="Max results"),
):
    return await bangumi.search(q, limit=limit)


@router.get("/{subject_id}", response_model=AnimeMetadata, summary="Get anime detail from Bangumi")
async def get_metadata(subject_id: int):
    meta = await bangumi.get_detail(subject_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return meta


@router.get(
    "/{subject_id}/full",
    response_model=AnimeMetadataFull,
    summary="Get rich anime metadata — staff, OP/ED, tags, aliases (Bangumi v0 infobox)",
)
async def get_metadata_full(subject_id: int):
    meta = await bangumi.get_full_detail(subject_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return meta


@router.get(
    "/{subject_id}/streaming",
    response_model=list[StreamingLink],
    summary="Get legal streaming platform links for the subject (Bilibili first).",
)
async def get_streaming_links(subject_id: int):
    """Aggregate streaming entries by searching platforms with the subject's Chinese/Japanese name."""
    meta = await bangumi.get_detail(subject_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Subject not found")

    # Prefer Chinese name when hunting B 站; fall back to the original name.
    candidates: list[str] = []
    for name in (meta.name_cn, meta.name):
        if name and name not in candidates:
            candidates.append(name)

    links: list[StreamingLink] = []
    for name in candidates:
        try:
            found = await bilibili.search_bangumi(name, limit=2)
            for item in found:
                if item.season_id and not any(
                    link.season_id == item.season_id and link.platform == item.platform for link in links
                ):
                    links.append(item)
            if links:
                break  # first name that yields hits is good enough
        except Exception:  # noqa: BLE001
            continue

    # Enrich each B 站 link with detailed season info when available.
    async def _enrich(link: StreamingLink) -> StreamingLink:
        if link.platform != "bilibili" or not link.season_id:
            return link
        try:
            detail = await bilibili.get_season_detail(link.season_id)
        except Exception:
            detail = None
        if not detail:
            return link
        return StreamingLink(
            platform=link.platform,
            title=detail.get("title") or link.title,
            url=detail.get("share_url") or link.url,
            season_id=detail.get("season_id") or link.season_id,
            cover_url=detail.get("cover") or link.cover_url,
            score=float(detail.get("score") or 0.0),
            total_episodes=int(detail.get("total_episodes") or link.total_episodes or 0),
            is_finished=bool(detail.get("is_finish", False)),
            is_paid=link.is_paid,
            paid_note=link.paid_note,
        )

    if links:
        links = list(await asyncio.gather(*[_enrich(link) for link in links]))

    return links


@router.get("/{subject_id}/cover", summary="Get anime cover image")
async def get_cover(subject_id: int):
    """Download and cache cover image, then return as file."""
    path = await bangumi.get_cover(subject_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Cover not available")

    media_type = "image/jpeg"
    if path.suffix == ".png":
        media_type = "image/png"
    elif path.suffix == ".webp":
        media_type = "image/webp"

    return FileResponse(path, media_type=media_type)
