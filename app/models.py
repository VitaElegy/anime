from datetime import datetime

from pydantic import BaseModel, Field


class TorrentItem(BaseModel):
    """A single torrent search result."""

    title: str
    magnet: str = ""
    torrent_url: str = ""
    size: str = ""
    seeders: int = 0
    leechers: int = 0
    date: str = ""
    source: str = ""  # "nyaa" or "subsplease"


class SearchResult(BaseModel):
    """Aggregated search results."""

    items: list[TorrentItem] = Field(default_factory=list)
    total: int = 0
    source: str = ""


class CalendarDayEntry(BaseModel):
    """A merged weekly calendar card entry."""

    day: str
    bangumi_id: int = 0
    title: str
    raw_title: str = ""
    cover_url: str = ""
    time: str = ""
    size: str = ""
    source: str = ""
    date: str = ""
    page: str = ""


class CalendarTimelineItem(BaseModel):
    """A release entry for the calendar timeline."""

    bangumi_id: int = 0
    title: str
    raw_title: str = ""
    cover_url: str = ""
    size: str = ""
    source: str = ""
    date: str = ""


class CalendarOverview(BaseModel):
    """Server-side cached calendar payload for high-frequency access."""

    week: dict[str, list[CalendarDayEntry]] = Field(default_factory=dict)
    timeline: list[CalendarTimelineItem] = Field(default_factory=list)
    generated_at: int = 0


class DownloadRequest(BaseModel):
    """Request body for adding a download."""

    magnet: str = ""
    torrent_url: str = ""
    save_path: str = ""
    category: str = "anime"


class BatchDownloadRequest(BaseModel):
    """Request body for batch downloads."""

    items: list[DownloadRequest]


class DownloadTask(BaseModel):
    """Status of a download task in qBittorrent."""

    hash: str
    name: str = ""
    progress: float = 0.0  # 0.0 ~ 1.0
    speed: int = 0  # bytes/s
    state: str = ""
    size: int = 0
    eta: int = 0  # seconds, -1 = unknown


class AnimeMetadata(BaseModel):
    """Bangumi anime metadata."""

    id: int
    name_cn: str = ""
    name: str = ""
    summary: str = ""
    score: float = 0.0
    cover_url: str = ""
    cover_local: str = ""


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str
    code: str = "error"


class UserPublic(BaseModel):
    """Authenticated user profile."""

    id: int
    username: str
    created_at: int = 0
    updated_at: int = 0
    last_login_at: int = 0


class AuthRequest(BaseModel):
    """Username / password credentials."""

    username: str
    password: str


class AuthResponse(BaseModel):
    """Session token plus authenticated user."""

    user: UserPublic
    token: str
    expires_at: int


class ImportFavoritesResponse(BaseModel):
    """Result of importing legacy shared favorites into a user account."""

    imported: int = 0
    skipped: int = 0
    total: int = 0


class MediaSubtitle(BaseModel):
    """A discoverable subtitle track for a media asset."""

    path: str = ""
    codec: str = ""
    language: str = ""
    title: str = ""
    source: str = ""  # embedded | sidecar


class MediaAsset(BaseModel):
    """A local media file that can be streamed or prepared for HLS playback."""

    media_id: str
    title: str
    relative_path: str
    source_path: str
    size: int = 0
    modified_at: int = 0
    container: str = ""
    duration: float = 0.0
    video_codecs: list[str] = Field(default_factory=list)
    audio_codecs: list[str] = Field(default_factory=list)
    subtitle_codecs: list[str] = Field(default_factory=list)
    subtitles: list[MediaSubtitle] = Field(default_factory=list)
    probe_status: str = "pending"  # pending | ready | failed | unavailable
    probe_error: str = ""
    direct_play_supported: bool = False
    recommended_mode: str = "pretranscode_hls"  # direct_play | pretranscode_hls | blocked
    watch_enabled: bool = True
    watch_block_reason: str = ""
    hls_status: str = "missing"  # missing | preparing | ready | error
    hls_playlist: str = ""
    hls_updated_at: int = 0
    last_error: str = ""


class MediaAssetListResponse(BaseModel):
    """Response for local media library listing."""

    items: list[MediaAsset] = Field(default_factory=list)
    total: int = 0
    refreshed_at: int = 0


class WatchRoomState(BaseModel):
    """Shared state for synchronized playback."""

    media_id: str = ""
    playback_mode: str = "direct_play"  # direct_play | hls
    playback_url: str = ""
    paused: bool = True
    position_seconds: float = 0.0
    playback_rate: float = 1.0
    updated_by: str = ""
    updated_at: int = 0


class WatchRoom(BaseModel):
    """A shared viewing room."""

    room_id: str
    name: str
    host_name: str = ""
    owner_user_id: int = 0
    owner_username: str = ""
    state: WatchRoomState = Field(default_factory=WatchRoomState)
    created_at: int = 0
    updated_at: int = 0


class WatchLobbyRoom(WatchRoom):
    """A watch room annotated for the lobby view."""

    participant_count: int = 0
    participant_usernames: list[str] = Field(default_factory=list)


class CreateWatchRoomRequest(BaseModel):
    """Request body for creating a viewing room."""

    name: str = ""
    host_name: str = ""
    media_id: str = ""
    playback_mode: str = "direct_play"
    playback_url: str = ""


class UpdateWatchRoomStateRequest(BaseModel):
    """Request body for updating room playback state."""

    media_id: str | None = None
    playback_mode: str | None = None
    playback_url: str | None = None
    paused: bool | None = None
    position_seconds: float | None = None
    playback_rate: float | None = None
    updated_by: str | None = None


class WatchHistoryItem(BaseModel):
    """A user's recent personal watch progress."""

    entry_id: int
    user_id: int
    room_id: str = ""
    room_name: str = ""
    media_id: str = ""
    media_title: str = ""
    playback_mode: str = "direct_play"
    position_seconds: float = 0.0
    duration_seconds: float = 0.0
    paused: bool = True
    updated_by: str = ""
    created_at: int = 0
    updated_at: int = 0


class SyncWatchHistoryRequest(BaseModel):
    """Request body for syncing the current user's personal watch progress."""

    room_id: str
    media_id: str | None = None
    playback_mode: str | None = None
    position_seconds: float | None = None
    paused: bool | None = None


class PresenceHeartbeatRequest(BaseModel):
    """Current signed-in user's lobby / room presence heartbeat."""

    room_id: str = ""
    room_name: str = ""
    page: str = ""
    status_text: str = ""


class OnlineUser(BaseModel):
    """An authenticated user currently active in the lobby / watch pages."""

    user_id: int
    username: str
    current_room_id: str = ""
    current_room_name: str = ""
    current_page: str = ""
    status_text: str = ""
    last_seen_at: int = 0
    is_friend: bool = False


class FriendRequestCreateRequest(BaseModel):
    """Send a friend request by username."""

    username: str


class FriendRequest(BaseModel):
    """Pending / accepted / rejected friend request record."""

    request_id: int
    requester_user_id: int
    requester_username: str
    target_user_id: int
    target_username: str
    status: str = "pending"
    created_at: int = 0
    updated_at: int = 0
    direction: str = ""


class FriendSummary(BaseModel):
    """Friend list item enriched with presence and chat summary."""

    user_id: int
    username: str
    created_at: int = 0
    is_online: bool = False
    last_seen_at: int = 0
    current_room_id: str = ""
    current_room_name: str = ""
    current_page: str = ""
    status_text: str = ""
    unread_count: int = 0
    last_message_preview: str = ""
    last_message_at: int = 0


class DirectMessage(BaseModel):
    """Direct message exchanged between friends."""

    message_id: int
    sender_user_id: int
    sender_username: str
    recipient_user_id: int
    recipient_username: str
    body: str
    created_at: int = 0
    read_at: int = 0
    is_mine: bool = False


class SendDirectMessageRequest(BaseModel):
    """Request body for sending a direct message."""

    body: str


class RoomInvitationCreateRequest(BaseModel):
    """Invite a friend into a watch room."""

    friend_user_id: int
    message: str = ""


class RoomInvitation(BaseModel):
    """Pending or handled room invitation between friends."""

    invitation_id: int
    room_id: str
    room_name: str = ""
    sender_user_id: int
    sender_username: str = ""
    recipient_user_id: int
    recipient_username: str = ""
    message: str = ""
    status: str = "pending"
    created_at: int = 0
    updated_at: int = 0
    direction: str = ""


class FriendActionResult(BaseModel):
    """Simple result payload for friend mutations."""

    ok: bool = True
    friend_user_id: int = 0


class RoomMessage(BaseModel):
    """Public chat message inside a watch room."""

    message_id: int
    room_id: str
    sender_user_id: int
    sender_username: str = ""
    body: str
    created_at: int = 0
    is_mine: bool = False


class SendRoomMessageRequest(BaseModel):
    """Request body for sending a watch room chat message."""

    body: str


class WatchLobbyOverview(BaseModel):
    """Aggregated lobby snapshot for rooms, online users, friends, and chat cues."""

    rooms: list[WatchLobbyRoom] = Field(default_factory=list)
    online_users: list[OnlineUser] = Field(default_factory=list)
    friends: list[FriendSummary] = Field(default_factory=list)
    incoming_requests: list[FriendRequest] = Field(default_factory=list)
    outgoing_requests: list[FriendRequest] = Field(default_factory=list)
    incoming_room_invitations: list[RoomInvitation] = Field(default_factory=list)
    outgoing_room_invitations: list[RoomInvitation] = Field(default_factory=list)
    generated_at: int = 0
