"""Schedule routes — weekly airing calendar + show episodes."""

from fastapi import APIRouter, Query

from app.services.schedule import get_schedule, get_show_episodes

router = APIRouter()


@router.get("", summary="Get weekly airing schedule")
async def weekly_schedule():
    """Fetch SubsPlease weekly schedule via JSON API. Includes time + cover image."""
    return await get_schedule()


@router.get("/show/{sid}", summary="Get all episodes for a show")
async def show_episodes(sid: int):
    """Fetch all episodes for a SubsPlease show by SID. Returns download links for each resolution."""
    return await get_show_episodes(sid)
