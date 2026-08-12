"""Personal watch history routes."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies.auth import get_current_user
from app.models import SyncWatchHistoryRequest, WatchHistoryItem
from app.services import watch_history

router = APIRouter()


@router.get("", response_model=list[WatchHistoryItem], summary="List personal watch history")
async def list_watch_history(
    limit: int = Query(8, ge=1, le=50),
    user: dict = Depends(get_current_user),
):
    return watch_history.list_history(int(user["id"]), limit=limit)


@router.get(
    "/resume", response_model=WatchHistoryItem | None, summary="Get personal resume progress for a room"
)
async def get_watch_resume(
    room_id: str = Query(..., min_length=1),
    media_id: str = Query(default=""),
    user: dict = Depends(get_current_user),
):
    return watch_history.get_resume(int(user["id"]), room_id=room_id, media_id=media_id)


@router.post("/progress", response_model=WatchHistoryItem, summary="Sync personal watch progress")
async def sync_watch_history_progress(
    req: SyncWatchHistoryRequest,
    user: dict = Depends(get_current_user),
):
    try:
        return watch_history.sync_progress(
            user=user,
            room_id=req.room_id,
            media_id=req.media_id,
            playback_mode=req.playback_mode,
            position_seconds=req.position_seconds,
            paused=req.paused,
        )
    except ValueError as exc:
        status_code = 404 if str(exc) == "Watch room not found" else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
