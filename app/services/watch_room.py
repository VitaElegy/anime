"""Shared watch room state management."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from app.services import database as db
from app.services import media_library, room_events

logger = logging.getLogger(__name__)

MAX_ROOM_MESSAGE_LENGTH = 1000
ROOM_INTERACTION_PRESENCE_SECONDS = 90
# P3: extend the owned-room grace period from "90 seconds, same as presence"
# to 10 minutes so a brief wifi hiccup or page reload doesn't delete the
# owner's room out from under them. Anonymous rooms keep their 6h grace.
OWNED_ROOM_EMPTY_GRACE_SECONDS = 10 * 60
ANONYMOUS_ROOM_EMPTY_GRACE_SECONDS = 6 * 3600
ROOM_CLEANUP_INTERVAL_SECONDS = 60


def _state_payload(
    *,
    media_id: str = "",
    playback_mode: str = "direct_play",
    playback_url: str = "",
    paused: bool = True,
    position_seconds: float = 0.0,
    playback_rate: float = 1.0,
    updated_by: str = "",
) -> dict:
    return {
        "media_id": media_id,
        "playback_mode": playback_mode,
        "playback_url": playback_url,
        "paused": paused,
        "position_seconds": position_seconds,
        "playback_rate": playback_rate,
        "updated_by": updated_by,
        "updated_at": int(time.time()),
    }


def list_rooms(*, owner_user_id: int | None = None) -> list[dict]:
    cleanup_inactive_rooms()
    return db.list_watch_rooms(owner_user_id=owner_user_id)


def get_room(room_id: str) -> dict | None:
    cleanup_inactive_rooms()
    return db.get_watch_room(room_id)


def cleanup_inactive_rooms() -> list[str]:
    rooms = db.list_watch_rooms()
    if not rooms:
        return []

    now = int(time.time())
    active_room_ids = {
        (item.get("current_room_id") or "").strip()
        for item in db.list_active_user_presence(ROOM_INTERACTION_PRESENCE_SECONDS)
        if (item.get("current_room_id") or "").strip()
    }

    deleted_room_ids: list[str] = []
    for room in rooms:
        room_id = room.get("room_id", "")
        if not room_id or room_id in active_room_ids:
            continue

        owner_user_id = int(room.get("owner_user_id", 0) or 0)
        grace_seconds = (
            OWNED_ROOM_EMPTY_GRACE_SECONDS if owner_user_id > 0 else ANONYMOUS_ROOM_EMPTY_GRACE_SECONDS
        )
        updated_at = int(room.get("updated_at", 0) or 0)
        idle_for = max(0, now - updated_at) if updated_at > 0 else grace_seconds
        if idle_for < grace_seconds:
            continue

        deleted_room_ids.append(room_id)

    if deleted_room_ids:
        deleted_count = db.delete_watch_rooms(deleted_room_ids)
        if deleted_count:
            logger.info("Cleaned up inactive watch rooms: %s", ", ".join(deleted_room_ids))

    return deleted_room_ids


async def run_periodic_room_cleanup():
    while True:
        try:
            cleanup_inactive_rooms()
        except Exception:
            logger.warning("Failed to cleanup inactive watch rooms", exc_info=True)
        await asyncio.sleep(ROOM_CLEANUP_INTERVAL_SECONDS)


def _owner_user_id(room: dict) -> int:
    return int(room.get("owner_user_id", 0) or 0)


def _has_accepted_invitation(room_id: str, user_id: int) -> bool:
    """True when this user accepted a room invitation for the given room."""
    if not user_id or not room_id:
        return False
    try:
        with db.get_conn() as conn:
            row = conn.execute(
                """SELECT 1 FROM room_invitations
                   WHERE room_id = ? AND recipient_user_id = ? AND status = 'accepted'
                   LIMIT 1""",
                (room_id, user_id),
            ).fetchone()
            return row is not None
    except Exception:
        logger.warning(
            "Failed to check room invitation for user %s / room %s", user_id, room_id, exc_info=True
        )
        return False


def _presence_matches_room(user_id: int, room_id: str) -> bool:
    if not user_id or not room_id:
        return False
    presence = db.get_active_user_presence(user_id, ROOM_INTERACTION_PRESENCE_SECONDS)
    return bool(presence and (presence.get("current_room_id") or "") == room_id)


def ensure_user_is_owner(room: dict, user: dict | None) -> None:
    """Only the room owner may mutate playback state or switch the media."""
    owner_id = _owner_user_id(room)
    # Anonymous rooms (created without an authenticated user) keep their old
    # permissive behaviour: anyone with presence in the room can drive them.
    if owner_id == 0:
        ensure_user_can_participate(room, user)
        return
    if not user:
        raise PermissionError("请先登录后再操作房间")
    if int(user["id"]) != owner_id:
        raise PermissionError("只有房主才能调整播放状态或切换片源")


def ensure_user_can_participate(room: dict, user: dict | None) -> None:
    """Looser check used by chat / HLS prep.

    Accepts the owner, users who accepted an invitation, or users with an
    active presence pointing at this room. Callers **must not** use this for
    state mutation — use :func:`ensure_user_is_owner` for that.
    """
    if not user:
        return
    user_id = int(user["id"])
    if _owner_user_id(room) == user_id:
        return
    if _has_accepted_invitation(room.get("room_id", ""), user_id):
        return
    if _presence_matches_room(user_id, room.get("room_id", "")):
        return
    raise PermissionError("请先进入房间后再操作")


# ─── Backwards-compatible alias ──────────────────────────────────────────────
# Older call sites use ``ensure_user_can_interact``. Keep the name as a thin
# wrapper so external code (and the social service) does not break, but route
# it through the new participation check.
def ensure_user_can_interact(room: dict, user: dict | None):
    ensure_user_can_participate(room, user)


def create_room(
    *,
    name: str,
    host_name: str = "",
    media_id: str = "",
    playback_mode: str = "direct_play",
    playback_url: str = "",
    owner_user: dict | None = None,
) -> dict:
    if media_id:
        asset = media_library.get_media_asset(media_id)
        if not asset:
            raise ValueError("Media asset not found")
        if not media_library.is_asset_watchable(asset):
            raise ValueError(media_library.get_asset_block_reason(asset))
        if asset.get("hls_status") == "ready":
            playback_mode = "hls"
            playback_url = media_library.get_playback_url(asset)
        elif asset.get("direct_play_supported"):
            playback_mode = "direct_play"
            playback_url = playback_url or media_library.get_playback_url(asset)
        else:
            playback_mode = "hls"
            playback_url = ""
    room_id = uuid.uuid4().hex[:10]
    resolved_host_name = host_name or (owner_user.get("username", "") if owner_user else "")
    state = _state_payload(
        media_id=media_id,
        playback_mode=playback_mode,
        playback_url=playback_url,
        updated_by=resolved_host_name,
    )
    return db.upsert_watch_room(
        room_id,
        name=name or f"Watch Room {room_id[:4]}",
        host_name=resolved_host_name,
        state=state,
        owner_user_id=int(owner_user["id"]) if owner_user else 0,
        owner_username=owner_user.get("username", "") if owner_user else "",
    )


def update_room_state(
    room_id: str,
    *,
    media_id: str | None = None,
    playback_mode: str | None = None,
    playback_url: str | None = None,
    paused: bool | None = None,
    position_seconds: float | None = None,
    playback_rate: float | None = None,
    updated_by: str | None = None,
    actor_user: dict | None = None,
) -> dict | None:
    room = get_room(room_id)
    if not room:
        return None
    ensure_user_is_owner(room, actor_user)
    current_state = room.get("state", {})
    if media_id:
        asset = media_library.get_media_asset(media_id)
        if not asset:
            raise ValueError("Media asset not found")
        if not media_library.is_asset_watchable(asset):
            raise ValueError(media_library.get_asset_block_reason(asset))
        if asset.get("hls_status") == "ready":
            playback_mode = "hls"
            playback_url = media_library.get_playback_url(asset)
        elif asset.get("direct_play_supported"):
            playback_mode = playback_mode or "direct_play"
            playback_url = playback_url or media_library.get_playback_url(asset)
        else:
            playback_mode = "hls"
            playback_url = ""
    state = _state_payload(
        media_id=media_id if media_id is not None else current_state.get("media_id", ""),
        playback_mode=playback_mode
        if playback_mode is not None
        else current_state.get("playback_mode", "direct_play"),
        playback_url=playback_url if playback_url is not None else current_state.get("playback_url", ""),
        paused=paused if paused is not None else bool(current_state.get("paused", True)),
        position_seconds=position_seconds
        if position_seconds is not None
        else float(current_state.get("position_seconds", 0.0)),
        playback_rate=playback_rate
        if playback_rate is not None
        else float(current_state.get("playback_rate", 1.0)),
        updated_by=updated_by
        if updated_by is not None
        else (actor_user.get("username", "") if actor_user else current_state.get("updated_by", "")),
    )
    updated = db.upsert_watch_room(
        room_id,
        name=room["name"],
        host_name=room.get("host_name", ""),
        state=state,
        owner_user_id=int(room.get("owner_user_id", 0) or 0),
        owner_username=room.get("owner_username", ""),
    )
    if updated:
        room_events.publish_threadsafe(room_id, "room_state", updated)
    return updated


def list_room_messages(room_id: str, *, user: dict | None = None, limit: int = 100) -> list[dict]:
    room = get_room(room_id)
    if not room:
        raise ValueError("Watch room not found")
    current_user_id = int(user["id"]) if user else 0
    return [
        {**item, "is_mine": current_user_id > 0 and int(item["sender_user_id"]) == current_user_id}
        for item in db.list_room_messages(room_id, limit=limit)
    ]


def send_room_message(room_id: str, user: dict, body: str) -> dict:
    room = get_room(room_id)
    if not room:
        raise ValueError("Watch room not found")
    ensure_user_can_interact(room, user)
    text = (body or "").strip()
    if not text:
        raise ValueError("消息内容不能为空")
    if len(text) > MAX_ROOM_MESSAGE_LENGTH:
        raise ValueError(f"消息请控制在 {MAX_ROOM_MESSAGE_LENGTH} 字以内")
    message = db.create_room_message(
        room_id=room_id,
        sender_user_id=int(user["id"]),
        sender_username=user.get("username", ""),
        body=text,
    )
    if message:
        # Broadcast the canonical message (without ``is_mine``) — each
        # subscriber decorates it themselves based on their own identity.
        room_events.publish_threadsafe(room_id, "room_message", dict(message))
    return {**message, "is_mine": True}
