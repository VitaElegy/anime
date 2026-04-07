"""Metadata routes — Bangumi anime info and cover images."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.models import AnimeMetadata
from app.services import bangumi

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
