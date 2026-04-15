"""Calendar routes for the high-frequency weekly anime calendar."""

from fastapi import APIRouter, Query

from app.models import CalendarOverview
from app.services.calendar import get_calendar_overview

router = APIRouter()


@router.get("", response_model=CalendarOverview, summary="Get cached calendar overview")
async def calendar_overview(
    quality: int = Query(1080, description="Video quality: 1080, 720, or 480"),
    force_refresh: bool = Query(False, description="Bypass cache and refresh calendar payload"),
):
    return await get_calendar_overview(quality=quality, force_refresh=force_refresh)
