"""Schedule routes — weekly airing calendar."""

from fastapi import APIRouter

from app.services.schedule import get_schedule

router = APIRouter()


@router.get("", summary="Get weekly airing schedule")
async def weekly_schedule():
    """Fetch SubsPlease weekly schedule, grouped by day."""
    return await get_schedule()
