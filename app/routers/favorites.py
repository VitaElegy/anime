"""Favorites & tracking routes."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services import database as db

router = APIRouter()


class FavoriteRequest(BaseModel):
    bangumi_id: int
    name_cn: str = ""
    name: str = ""
    cover_url: str = ""
    score: float = 0


class FavoriteUpdate(BaseModel):
    status: str | None = None
    episode_progress: int | None = None
    total_episodes: int | None = None
    tags: str | None = None
    notes: str | None = None


@router.get("", summary="List all favorites")
async def list_favorites(status: str = Query("", description="Filter by status: watching, completed, dropped, planned")):
    return db.get_favorites(status)


@router.post("", summary="Add to favorites")
async def add_favorite(req: FavoriteRequest):
    return db.add_favorite(
        bangumi_id=req.bangumi_id,
        name_cn=req.name_cn,
        name=req.name,
        cover_url=req.cover_url,
        score=req.score,
    )


@router.get("/{bangumi_id}", summary="Get favorite detail")
async def get_favorite(bangumi_id: int):
    fav = db.get_favorite(bangumi_id)
    if not fav:
        raise HTTPException(status_code=404, detail="Not in favorites")
    return fav


@router.put("/{bangumi_id}", summary="Update favorite status/progress")
async def update_favorite(bangumi_id: int, req: FavoriteUpdate):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    result = db.update_favorite(bangumi_id, **updates)
    if not result:
        raise HTTPException(status_code=404, detail="Not in favorites")
    return result


@router.delete("/{bangumi_id}", summary="Remove from favorites")
async def remove_favorite(bangumi_id: int):
    ok = db.remove_favorite(bangumi_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Not in favorites")
    return {"status": "ok"}
