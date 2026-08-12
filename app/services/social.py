"""Lobby presence, friendships, and direct chat."""

from __future__ import annotations

import time
from collections import defaultdict

from app.services import auth as auth_service
from app.services import database as db
from app.services import watch_room as watch_room_service

ACTIVE_PRESENCE_SECONDS = 90
STALE_PRESENCE_SECONDS = 3600
MAX_MESSAGE_LENGTH = 800
MAX_INVITATION_MESSAGE_LENGTH = 240


def _message_preview(body: str, limit: int = 42) -> str:
    text = (body or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _room_invitation_payload(item: dict, direction: str) -> dict:
    return {**item, "direction": direction}


def heartbeat(
    user: dict,
    *,
    room_id: str = "",
    room_name: str = "",
    page: str = "",
    status_text: str = "",
) -> dict:
    clean_room_id = (room_id or "").strip()
    clean_page = (page or "").strip()
    clean_room_name = (room_name or "").strip()

    if clean_room_id:
        room = watch_room_service.get_room(clean_room_id)
        if not room:
            raise ValueError("房间不存在")
        clean_room_name = room.get("name", "") or clean_room_name
        if not clean_page:
            clean_page = "watch_room"
    else:
        clean_room_name = ""
        if clean_page == "watch_room":
            raise ValueError("房间号不能为空")

    return db.upsert_user_presence(
        int(user["id"]),
        user.get("username", ""),
        current_room_id=clean_room_id,
        current_room_name=clean_room_name,
        current_page=clean_page,
        status_text=(status_text or "").strip(),
    )


def build_lobby(current_user: dict | None = None) -> dict:
    db.purge_stale_user_presence(STALE_PRESENCE_SECONDS)
    watch_room_service.cleanup_inactive_rooms()

    rooms = db.list_watch_rooms()
    active_presence = db.list_active_user_presence(ACTIVE_PRESENCE_SECONDS)
    current_user_id = int(current_user["id"]) if current_user else 0

    friend_ids: set[int] = set()
    friends: list[dict] = []
    incoming_requests: list[dict] = []
    outgoing_requests: list[dict] = []
    incoming_room_invitations: list[dict] = []
    outgoing_room_invitations: list[dict] = []
    unread_counts: dict[int, int] = {}
    latest_messages: dict[int, dict] = {}

    if current_user:
        friend_rows = db.list_friends(current_user_id)
        friend_ids = {int(item["user_id"]) for item in friend_rows}
        unread_counts = db.get_unread_direct_message_counts(current_user_id)
        latest_messages = db.get_latest_direct_message_map(current_user_id)
        presence_map = {int(item["user_id"]): item for item in active_presence}

        for item in friend_rows:
            friend_id = int(item["user_id"])
            presence = presence_map.get(friend_id)
            latest = latest_messages.get(friend_id)
            friends.append(
                {
                    "user_id": friend_id,
                    "username": item["username"],
                    "created_at": int(item.get("created_at", 0) or 0),
                    "is_online": presence is not None,
                    "last_seen_at": int((presence or {}).get("last_seen_at", 0) or 0),
                    "current_room_id": (presence or {}).get("current_room_id", ""),
                    "current_room_name": (presence or {}).get("current_room_name", ""),
                    "current_page": (presence or {}).get("current_page", ""),
                    "status_text": (presence or {}).get("status_text", ""),
                    "unread_count": int(unread_counts.get(friend_id, 0) or 0),
                    "last_message_preview": _message_preview((latest or {}).get("body", "")),
                    "last_message_at": int((latest or {}).get("created_at", 0) or 0),
                }
            )

        incoming_requests = [
            {**item, "direction": "incoming"}
            for item in db.list_incoming_friend_requests(current_user_id, status="pending")
        ]
        outgoing_requests = [
            {**item, "direction": "outgoing"}
            for item in db.list_outgoing_friend_requests(current_user_id, status="pending")
        ]
        incoming_room_invitations = [
            _room_invitation_payload(item, "incoming")
            for item in db.list_incoming_room_invitations(current_user_id, status="pending")
        ]
        outgoing_room_invitations = [
            _room_invitation_payload(item, "outgoing")
            for item in db.list_outgoing_room_invitations(current_user_id, status="pending")
        ]

        friends.sort(
            key=lambda item: (
                0 if item["is_online"] else 1,
                -int(item["unread_count"]),
                -int(item["last_message_at"]),
                item["username"].lower(),
            )
        )

    room_participants: dict[str, list[str]] = defaultdict(list)
    online_users: list[dict] = []
    for item in active_presence:
        room_id = item.get("current_room_id", "")
        if room_id:
            room_participants[room_id].append(item["username"])
        online_users.append(
            {
                "user_id": int(item["user_id"]),
                "username": item["username"],
                "current_room_id": room_id,
                "current_room_name": item.get("current_room_name", ""),
                "current_page": item.get("current_page", ""),
                "status_text": item.get("status_text", ""),
                "last_seen_at": int(item.get("last_seen_at", 0) or 0),
                "is_friend": int(item["user_id"]) in friend_ids if current_user else False,
            }
        )

    online_users.sort(
        key=lambda item: (
            0 if item["user_id"] == current_user_id and current_user_id else 1,
            0 if item["is_friend"] else 1,
            0 if item["current_room_id"] else 1,
            -int(item["last_seen_at"]),
            item["username"].lower(),
        )
    )

    lobby_rooms = []
    for room in rooms:
        participant_names = room_participants.get(room["room_id"], [])
        lobby_rooms.append(
            {
                **room,
                "participant_count": len(participant_names),
                "participant_usernames": participant_names[:8],
            }
        )

    lobby_rooms.sort(
        key=lambda item: (
            -int(item["participant_count"]),
            -int(item["updated_at"]),
            item["name"].lower(),
        )
    )

    return {
        "rooms": lobby_rooms,
        "online_users": online_users,
        "friends": friends,
        "incoming_requests": incoming_requests,
        "outgoing_requests": outgoing_requests,
        "incoming_room_invitations": incoming_room_invitations,
        "outgoing_room_invitations": outgoing_room_invitations,
        "generated_at": int(time.time()),
    }


def send_friend_request(user: dict, username: str) -> dict:
    normalized = auth_service.normalize_username(username)
    if not normalized:
        raise ValueError("请输入要添加的用户名")

    requester_user_id = int(user["id"])
    target = db.get_user_by_username(normalized)
    if not target:
        raise ValueError("没有找到这个用户")

    target_user_id = int(target["id"])
    if requester_user_id == target_user_id:
        raise ValueError("不能把自己加为好友")
    if db.are_friends(requester_user_id, target_user_id):
        raise ValueError("你们已经是好友了")

    existing_outgoing = db.get_friend_request_between(requester_user_id, target_user_id, status="pending")
    if existing_outgoing:
        return {**existing_outgoing, "direction": "outgoing"}

    existing_incoming = db.get_friend_request_between(target_user_id, requester_user_id, status="pending")
    if existing_incoming:
        db.add_friendship_pair(requester_user_id, target_user_id)
        accepted = (
            db.update_friend_request_status(existing_incoming["request_id"], "accepted") or existing_incoming
        )
        return {**accepted, "direction": "incoming"}

    created = db.create_friend_request(
        requester_user_id=requester_user_id,
        requester_username=user.get("username", ""),
        target_user_id=target_user_id,
        target_username=target.get("username", ""),
    )
    return {**created, "direction": "outgoing"}


def accept_friend_request(user: dict, request_id: int) -> dict:
    request = db.get_friend_request(request_id)
    if not request:
        raise ValueError("好友申请不存在")
    if int(request["target_user_id"]) != int(user["id"]):
        raise ValueError("这条好友申请不属于你")
    if request["status"] == "accepted":
        return {**request, "direction": "incoming"}
    if request["status"] != "pending":
        raise ValueError("这条好友申请已经处理过了")

    db.add_friendship_pair(int(request["requester_user_id"]), int(request["target_user_id"]))
    updated = db.update_friend_request_status(request_id, "accepted") or request
    return {**updated, "direction": "incoming"}


def reject_friend_request(user: dict, request_id: int) -> dict:
    request = db.get_friend_request(request_id)
    if not request:
        raise ValueError("好友申请不存在")
    if int(request["target_user_id"]) != int(user["id"]):
        raise ValueError("这条好友申请不属于你")
    if request["status"] != "pending":
        return {**request, "direction": "incoming"}

    updated = db.update_friend_request_status(request_id, "rejected") or request
    return {**updated, "direction": "incoming"}


def remove_friend(user: dict, friend_user_id: int) -> dict:
    user_id = int(user["id"])
    if user_id == friend_user_id:
        raise ValueError("不能删除自己")
    if not db.are_friends(user_id, friend_user_id):
        raise ValueError("对方当前不是你的好友")
    db.remove_friendship_pair(user_id, friend_user_id)
    db.cancel_pending_room_invitations_between_users(user_id, friend_user_id)
    return {"ok": True, "friend_user_id": int(friend_user_id)}


def send_room_invitation(user: dict, room_id: str, friend_user_id: int, message: str = "") -> dict:
    sender_user_id = int(user["id"])
    clean_room_id = (room_id or "").strip()
    clean_message = (message or "").strip()
    if not clean_room_id:
        raise ValueError("房间号不能为空")
    if sender_user_id == int(friend_user_id):
        raise ValueError("不能邀请自己")
    if len(clean_message) > MAX_INVITATION_MESSAGE_LENGTH:
        raise ValueError(f"邀请留言请控制在 {MAX_INVITATION_MESSAGE_LENGTH} 字以内")
    if not db.are_friends(sender_user_id, int(friend_user_id)):
        raise ValueError("只能邀请好友进入房间")

    room = db.get_watch_room(clean_room_id)
    if not room:
        raise ValueError("房间不存在")
    watch_room_service.ensure_user_can_interact(room, user)

    recipient = db.get_user_by_id(int(friend_user_id))
    if not recipient:
        raise ValueError("好友不存在")
    active_presence = db.get_active_user_presence_map(ACTIVE_PRESENCE_SECONDS).get(int(recipient["id"]))
    if active_presence and (active_presence.get("current_room_id") or "") == room["room_id"]:
        raise ValueError("好友已经在这个房间里")

    invitation = db.create_room_invitation(
        room_id=room["room_id"],
        room_name=room.get("name", ""),
        sender_user_id=sender_user_id,
        sender_username=user.get("username", ""),
        recipient_user_id=int(recipient["id"]),
        recipient_username=recipient.get("username", ""),
        message=clean_message,
    )
    return _room_invitation_payload(invitation, "outgoing")


def accept_room_invitation(user: dict, invitation_id: int) -> dict:
    invitation = db.get_room_invitation(invitation_id)
    if not invitation:
        raise ValueError("房间邀请不存在")
    if int(invitation["recipient_user_id"]) != int(user["id"]):
        raise ValueError("这条邀请不属于你")
    if invitation["status"] == "accepted":
        return _room_invitation_payload(invitation, "incoming")
    if invitation["status"] != "pending":
        raise ValueError("这条邀请已经处理过了")
    updated = db.update_room_invitation_status(invitation_id, "accepted") or invitation
    return _room_invitation_payload(updated, "incoming")


def dismiss_room_invitation(user: dict, invitation_id: int) -> dict:
    invitation = db.get_room_invitation(invitation_id)
    if not invitation:
        raise ValueError("房间邀请不存在")
    if int(invitation["recipient_user_id"]) != int(user["id"]):
        raise ValueError("这条邀请不属于你")
    if invitation["status"] != "pending":
        return _room_invitation_payload(invitation, "incoming")
    updated = db.update_room_invitation_status(invitation_id, "dismissed") or invitation
    return _room_invitation_payload(updated, "incoming")


def list_direct_messages(user: dict, friend_user_id: int, *, limit: int = 50) -> list[dict]:
    user_id = int(user["id"])
    if not db.are_friends(user_id, friend_user_id):
        raise ValueError("只有好友之间才能查看私聊")
    db.mark_direct_messages_read(user_id, friend_user_id)
    return [
        {**item, "is_mine": int(item["sender_user_id"]) == user_id}
        for item in db.list_direct_messages(user_id, friend_user_id, limit=limit)
    ]


def send_direct_message(user: dict, friend_user_id: int, body: str) -> dict:
    user_id = int(user["id"])
    text = (body or "").strip()
    if not text:
        raise ValueError("消息内容不能为空")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"消息请控制在 {MAX_MESSAGE_LENGTH} 字以内")
    if not db.are_friends(user_id, friend_user_id):
        raise ValueError("只有好友之间才能私聊")

    recipient = db.get_user_by_id(friend_user_id)
    if not recipient:
        raise ValueError("好友不存在")

    message = db.create_direct_message(
        sender_user_id=user_id,
        sender_username=user.get("username", ""),
        recipient_user_id=int(recipient["id"]),
        recipient_username=recipient.get("username", ""),
        body=text,
    )
    return {**message, "is_mine": True}
