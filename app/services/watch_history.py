"""Personal watch history for authenticated users."""

from __future__ import annotations

from app.services import database as db
from app.services import media_library


def _normalize_progress(
    *,
    room: dict,
    media_id: str,
    playback_mode: str | None,
    position_seconds: float | None,
    paused: bool | None,
) -> tuple[str, float, bool, dict | None]:
    state = room.get("state", {})
    asset = media_library.get_media_asset(media_id)
    resolved_mode = playback_mode or state.get("playback_mode", "direct_play")
    resolved_position = float(
        position_seconds if position_seconds is not None else state.get("position_seconds", 0.0) or 0.0
    )
    resolved_paused = bool(paused if paused is not None else state.get("paused", True))
    duration_seconds = float(asset.get("duration", 0) or 0) if asset else 0.0
    if duration_seconds > 0:
        resolved_position = max(0.0, min(resolved_position, duration_seconds))
    else:
        resolved_position = max(0.0, resolved_position)
    return resolved_mode, resolved_position, resolved_paused, asset


def record_progress(
    *,
    user: dict,
    room: dict,
    media_id: str | None = None,
    playback_mode: str | None = None,
    position_seconds: float | None = None,
    paused: bool | None = None,
) -> dict:
    resolved_media_id = media_id or room.get("state", {}).get("media_id", "")
    if not resolved_media_id:
        raise ValueError("当前房间还没有绑定片源")

    resolved_mode, resolved_position, resolved_paused, asset = _normalize_progress(
        room=room,
        media_id=resolved_media_id,
        playback_mode=playback_mode,
        position_seconds=position_seconds,
        paused=paused,
    )
    return db.upsert_user_watch_history(
        int(user["id"]),
        room_id=room.get("room_id", ""),
        room_name=room.get("name", ""),
        media_id=resolved_media_id,
        media_title=asset.get("title", "") if asset else resolved_media_id,
        playback_mode=resolved_mode,
        position_seconds=resolved_position,
        duration_seconds=float(asset.get("duration", 0) or 0) if asset else 0.0,
        paused=resolved_paused,
        updated_by=room.get("state", {}).get("updated_by", "") or user.get("username", ""),
    )


def sync_progress(
    *,
    user: dict,
    room_id: str,
    media_id: str | None = None,
    playback_mode: str | None = None,
    position_seconds: float | None = None,
    paused: bool | None = None,
) -> dict:
    room = db.get_watch_room(room_id)
    if not room:
        raise ValueError("Watch room not found")
    return record_progress(
        user=user,
        room=room,
        media_id=media_id,
        playback_mode=playback_mode,
        position_seconds=position_seconds,
        paused=paused,
    )


def list_history(user_id: int, limit: int = 12) -> list[dict]:
    return db.list_user_watch_history(user_id, limit)


def get_resume(user_id: int, *, room_id: str, media_id: str = "") -> dict | None:
    return db.get_user_watch_history_entry(user_id, room_id, media_id)
