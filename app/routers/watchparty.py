"""WatchParty — synchronized video watching with voice chat via WebRTC."""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("watchparty")

router = APIRouter()


@dataclass
class Peer:
    """A connected user in a room."""
    ws: WebSocket
    user_id: str
    nickname: str
    is_host: bool = False
    joined_at: float = field(default_factory=time.time)


@dataclass
class Room:
    """A watch party room."""
    room_id: str
    name: str
    created_at: float = field(default_factory=time.time)
    peers: dict[str, Peer] = field(default_factory=dict)
    # Video state
    video_url: str = ""
    video_title: str = ""
    is_playing: bool = False
    current_time: float = 0.0
    last_sync_at: float = 0.0
    playback_rate: float = 1.0
    # Chat history (keep last 200)
    chat_history: list[dict] = field(default_factory=list)


# In-memory room store
rooms: dict[str, Room] = {}
MAX_ROOMS = 50
MAX_CHAT_LENGTH = 500


def _room_info(room: Room) -> dict:
    return {
        "room_id": room.room_id,
        "name": room.name,
        "peer_count": len(room.peers),
        "video_url": room.video_url,
        "video_title": room.video_title,
        "is_playing": room.is_playing,
        "current_time": room.current_time,
        "created_at": room.created_at,
    }


def _peer_list(room: Room) -> list[dict]:
    return [
        {
            "user_id": p.user_id,
            "nickname": p.nickname,
            "is_host": p.is_host,
        }
        for p in room.peers.values()
    ]


# ── REST endpoints ──────────────────────────────────────────────

@router.get("/rooms", summary="List active rooms")
async def list_rooms():
    return [_room_info(r) for r in rooms.values()]


@router.post("/rooms", summary="Create a new room")
async def create_room(name: str = "放映室", video_url: str = ""):
    if len(rooms) >= MAX_ROOMS:
        return JSONResponse(status_code=429, content={"detail": f"Maximum {MAX_ROOMS} rooms reached"})
    room_id = uuid.uuid4().hex[:8]
    room = Room(room_id=room_id, name=name, video_url=video_url)
    rooms[room_id] = room
    logger.info("Room created: %s (%s)", room_id, name)
    return _room_info(room)


@router.get("/rooms/{room_id}", summary="Get room info")
async def get_room(room_id: str):
    room = rooms.get(room_id)
    if not room:
        return JSONResponse(status_code=404, content={"detail": "Room not found"})
    info = _room_info(room)
    info["peers"] = _peer_list(room)
    info["chat_history"] = room.chat_history[-50:]
    return info


@router.delete("/rooms/{room_id}", summary="Delete a room")
async def delete_room(room_id: str):
    room = rooms.pop(room_id, None)
    if not room:
        return JSONResponse(status_code=404, content={"detail": "Room not found"})
    # Disconnect all peers
    for peer in list(room.peers.values()):
        try:
            await peer.ws.close()
        except Exception:
            pass
    return {"detail": "Room deleted"}


# ── WebSocket endpoint ──────────────────────────────────────────

async def _broadcast(room: Room, message: dict, exclude_uid: Optional[str] = None):
    """Send message to all peers in room, optionally excluding one."""
    data = json.dumps(message, ensure_ascii=False)
    dead = []
    for uid, peer in room.peers.items():
        if uid == exclude_uid:
            continue
        try:
            await peer.ws.send_text(data)
        except Exception:
            dead.append(uid)
    for uid in dead:
        room.peers.pop(uid, None)


@router.websocket("/ws/{room_id}")
async def ws_room(
    websocket: WebSocket,
    room_id: str,
    nickname: str = Query("匿名用户"),
    user_id: str = Query(""),
):
    room = rooms.get(room_id)
    if not room:
        await websocket.close(code=4004, reason="Room not found")
        return

    await websocket.accept()

    uid = user_id or uuid.uuid4().hex[:12]
    is_host = len(room.peers) == 0
    peer = Peer(ws=websocket, user_id=uid, nickname=nickname, is_host=is_host)
    room.peers[uid] = peer

    logger.info("[%s] %s joined (host=%s)", room_id, nickname, is_host)

    # Send initial state to the new peer
    await websocket.send_text(json.dumps({
        "type": "init",
        "user_id": uid,
        "is_host": is_host,
        "room": _room_info(room),
        "peers": _peer_list(room),
        "chat_history": room.chat_history[-50:],
    }, ensure_ascii=False))

    # Notify others
    await _broadcast(room, {
        "type": "peer_joined",
        "user_id": uid,
        "nickname": nickname,
        "is_host": is_host,
        "peers": _peer_list(room),
    }, exclude_uid=uid)

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            # ── Video sync messages ──
            if msg_type == "video_change":
                room.video_url = msg.get("url", "")
                room.video_title = msg.get("title", "")
                room.current_time = 0
                room.is_playing = False
                await _broadcast(room, {
                    "type": "video_change",
                    "url": room.video_url,
                    "title": room.video_title,
                    "from": uid,
                })

            elif msg_type == "play":
                room.is_playing = True
                room.current_time = msg.get("time", room.current_time)
                room.last_sync_at = time.time()
                await _broadcast(room, {
                    "type": "play",
                    "time": room.current_time,
                    "from": uid,
                }, exclude_uid=uid)

            elif msg_type == "pause":
                room.is_playing = False
                room.current_time = msg.get("time", room.current_time)
                await _broadcast(room, {
                    "type": "pause",
                    "time": room.current_time,
                    "from": uid,
                }, exclude_uid=uid)

            elif msg_type == "seek":
                room.current_time = msg.get("time", 0)
                room.last_sync_at = time.time()
                await _broadcast(room, {
                    "type": "seek",
                    "time": room.current_time,
                    "from": uid,
                }, exclude_uid=uid)

            elif msg_type == "sync_request":
                # New peer asking for current time
                await websocket.send_text(json.dumps({
                    "type": "sync_state",
                    "video_url": room.video_url,
                    "video_title": room.video_title,
                    "is_playing": room.is_playing,
                    "current_time": room.current_time,
                    "playback_rate": room.playback_rate,
                }))

            elif msg_type == "time_update":
                # Periodic time sync from host
                if peer.is_host:
                    room.current_time = msg.get("time", room.current_time)
                    room.last_sync_at = time.time()

            # ── Chat messages ──
            elif msg_type == "chat":
                content = msg.get("content", "")[:MAX_CHAT_LENGTH]
                if not content:
                    continue
                chat_msg = {
                    "type": "chat",
                    "user_id": uid,
                    "nickname": nickname,
                    "content": content,
                    "timestamp": time.time(),
                }
                room.chat_history.append(chat_msg)
                if len(room.chat_history) > 200:
                    room.chat_history = room.chat_history[-200:]
                await _broadcast(room, chat_msg)

            # ── WebRTC signaling for voice chat ──
            elif msg_type == "rtc_offer":
                target = msg.get("target")
                if target and target in room.peers:
                    await room.peers[target].ws.send_text(json.dumps({
                        "type": "rtc_offer",
                        "from": uid,
                        "sdp": msg.get("sdp"),
                    }))

            elif msg_type == "rtc_answer":
                target = msg.get("target")
                if target and target in room.peers:
                    await room.peers[target].ws.send_text(json.dumps({
                        "type": "rtc_answer",
                        "from": uid,
                        "sdp": msg.get("sdp"),
                    }))

            elif msg_type == "rtc_ice_candidate":
                target = msg.get("target")
                if target and target in room.peers:
                    await room.peers[target].ws.send_text(json.dumps({
                        "type": "rtc_ice_candidate",
                        "from": uid,
                        "candidate": msg.get("candidate"),
                    }))

            elif msg_type == "voice_state":
                # User toggled mute/unmute
                await _broadcast(room, {
                    "type": "voice_state",
                    "user_id": uid,
                    "nickname": nickname,
                    "muted": msg.get("muted", True),
                }, exclude_uid=uid)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("[%s] WebSocket error for %s: %s", room_id, nickname, e)
    finally:
        room.peers.pop(uid, None)
        logger.info("[%s] %s left", room_id, nickname)

        # If host left, assign new host
        if peer.is_host and room.peers:
            new_host_uid = next(iter(room.peers))
            room.peers[new_host_uid].is_host = True
            await _broadcast(room, {
                "type": "host_changed",
                "user_id": new_host_uid,
                "nickname": room.peers[new_host_uid].nickname,
            })

        await _broadcast(room, {
            "type": "peer_left",
            "user_id": uid,
            "nickname": nickname,
            "peers": _peer_list(room),
        })

        # Clean up empty rooms
        if not room.peers:
            rooms.pop(room_id, None)
            logger.info("[%s] Room empty, removed", room_id)
