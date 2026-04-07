"""AniList routes — anime search, trending, airing schedule."""

from fastapi import APIRouter, Query

from app.services import anilist

router = APIRouter()


@router.get("/search", summary="Search anime on AniList (supports Chinese/Japanese/English)")
async def anilist_search(
    q: str = Query(..., description="Search keyword (Chinese, Japanese, or English)"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    return await anilist.search(q, page=page, per_page=limit)


@router.get("/trending", summary="Get trending anime this season")
async def anilist_trending(
    season: str = Query("", description="WINTER, SPRING, SUMMER, FALL"),
    year: int = Query(0, description="Season year, e.g. 2026"),
    limit: int = Query(20, ge=1, le=50),
):
    return await anilist.get_trending(season=season, year=year, per_page=limit)


@router.get("/schedule", summary="Get upcoming airing schedule")
async def anilist_schedule(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=50),
):
    return await anilist.get_airing_schedule(page=page, per_page=limit)
