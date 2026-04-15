"""Watch room routes for synchronized playback state."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies.auth import get_current_user, get_optional_user

from app.models import CreateWatchRoomRequest, RoomMessage, SendRoomMessageRequest, UpdateWatchRoomStateRequest, WatchRoom
from app.services import watch_history, watch_room

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("", response_model=list[WatchRoom], summary="List watch rooms")
async def list_watch_rooms(
    mine: bool = False,
    user: dict | None = Depends(get_optional_user),
):
    if mine and not user:
        return []
    return watch_room.list_rooms(owner_user_id=int(user["id"]) if mine and user else None)


@router.post("", response_model=WatchRoom, summary="Create a watch room")
async def create_watch_room(req: CreateWatchRoomRequest, user: dict | None = Depends(get_optional_user)):
    try:
        room = watch_room.create_room(
            name=req.name,
            host_name=req.host_name or (user.get("username", "") if user else ""),
            media_id=req.media_id,
            playback_mode=req.playback_mode,
            playback_url=req.playback_url,
            owner_user=user,
        )
        if user and room.get("state", {}).get("media_id"):
            try:
                watch_history.record_progress(user=user, room=room)
            except Exception:
                logger.warning("Failed to record watch history after room creation", exc_info=True)
        return room
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{room_id}", response_model=WatchRoom, summary="Get a watch room")
async def get_watch_room(room_id: str):
    room = watch_room.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Watch room not found")
    return room


@router.put("/{room_id}/state", response_model=WatchRoom, summary="Update watch room playback state")
async def update_watch_room_state(
    room_id: str,
    req: UpdateWatchRoomStateRequest,
    user: dict | None = Depends(get_optional_user),
):
    try:
        effective_updated_by = req.updated_by
        if user and (not effective_updated_by or effective_updated_by == "web"):
            effective_updated_by = user.get("username", "")
        room = watch_room.update_room_state(
            room_id,
            media_id=req.media_id,
            playback_mode=req.playback_mode,
            playback_url=req.playback_url,
            paused=req.paused,
            position_seconds=req.position_seconds,
            playback_rate=req.playback_rate,
            updated_by=effective_updated_by,
            actor_user=user,
        )
        if user and room and room.get("state", {}).get("media_id"):
            try:
                watch_history.record_progress(
                    user=user,
                    room=room,
                    media_id=req.media_id,
                    playback_mode=req.playback_mode,
                    position_seconds=req.position_seconds,
                    paused=req.paused,
                )
            except Exception:
                logger.warning("Failed to record watch history after room sync", exc_info=True)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not room:
        raise HTTPException(status_code=404, detail="Watch room not found")
    return room


@router.get("/{room_id}/messages", response_model=list[RoomMessage], summary="List watch room chat messages")
async def list_watch_room_messages(
    room_id: str,
    limit: int = Query(80, ge=1, le=200),
    user: dict | None = Depends(get_optional_user),
):
    try:
        return watch_room.list_room_messages(room_id, user=user, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{room_id}/messages", response_model=RoomMessage, summary="Send a watch room chat message")
async def create_watch_room_message(
    room_id: str,
    req: SendRoomMessageRequest,
    user: dict = Depends(get_current_user),
):
    try:
        return watch_room.send_room_message(room_id, user, req.body)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        status_code = 404 if str(exc) == "Watch room not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
