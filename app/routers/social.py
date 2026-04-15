"""Lobby, online presence, friendships, and direct chat routes."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies.auth import get_current_user, get_optional_user
from app.models import (
    DirectMessage,
    FriendActionResult,
    FriendRequest,
    FriendRequestCreateRequest,
    OnlineUser,
    PresenceHeartbeatRequest,
    RoomInvitation,
    RoomInvitationCreateRequest,
    SendDirectMessageRequest,
    WatchLobbyOverview,
)
from app.services import social

router = APIRouter()


@router.get("/lobby", response_model=WatchLobbyOverview, summary="Get watch lobby overview")
async def get_watch_lobby(user: dict | None = Depends(get_optional_user)):
    return social.build_lobby(user)


@router.post("/presence", response_model=OnlineUser, summary="Heartbeat current user's watch presence")
async def heartbeat_presence(req: PresenceHeartbeatRequest, user: dict = Depends(get_current_user)):
    try:
        return social.heartbeat(
            user,
            room_id=req.room_id,
            room_name=req.room_name,
            page=req.page,
            status_text=req.status_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/friends/requests", response_model=FriendRequest, summary="Send friend request")
async def create_friend_request(req: FriendRequestCreateRequest, user: dict = Depends(get_current_user)):
    try:
        return social.send_friend_request(user, req.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/friends/requests/{request_id}/accept", response_model=FriendRequest, summary="Accept friend request")
async def accept_request(request_id: int, user: dict = Depends(get_current_user)):
    try:
        return social.accept_friend_request(user, request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/friends/requests/{request_id}/reject", response_model=FriendRequest, summary="Reject friend request")
async def reject_request(request_id: int, user: dict = Depends(get_current_user)):
    try:
        return social.reject_friend_request(user, request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/friends/{friend_user_id}", response_model=FriendActionResult, summary="Remove a friend")
async def delete_friend(friend_user_id: int, user: dict = Depends(get_current_user)):
    try:
        return social.remove_friend(user, friend_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/rooms/{room_id}/invite", response_model=RoomInvitation, summary="Invite a friend to a room")
async def invite_friend_to_room(
    room_id: str,
    req: RoomInvitationCreateRequest,
    user: dict = Depends(get_current_user),
):
    try:
        return social.send_room_invitation(user, room_id, req.friend_user_id, req.message)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/room-invitations/{invitation_id}/accept", response_model=RoomInvitation, summary="Accept a room invitation")
async def accept_room_invitation(invitation_id: int, user: dict = Depends(get_current_user)):
    try:
        return social.accept_room_invitation(user, invitation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/room-invitations/{invitation_id}/dismiss", response_model=RoomInvitation, summary="Dismiss a room invitation")
async def dismiss_room_invitation(invitation_id: int, user: dict = Depends(get_current_user)):
    try:
        return social.dismiss_room_invitation(user, invitation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/friends/{friend_user_id}/messages", response_model=list[DirectMessage], summary="List direct messages with a friend")
async def list_friend_messages(
    friend_user_id: int,
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    try:
        return social.list_direct_messages(user, friend_user_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/friends/{friend_user_id}/messages", response_model=DirectMessage, summary="Send direct message to a friend")
async def send_friend_message(
    friend_user_id: int,
    req: SendDirectMessageRequest,
    user: dict = Depends(get_current_user),
):
    try:
        return social.send_direct_message(user, friend_user_id, req.body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
