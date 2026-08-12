export interface TorrentItem {
  title: string
  magnet: string
  torrent_url: string
  size: string
  seeders: number
  leechers: number
  date: string
  source: string
  info_hash?: string
  fansub?: string
  publisher?: string
  detail_url?: string
}

export interface SearchResult {
  items: TorrentItem[]
  total: number
  source: string
}

export interface DownloadRequest {
  magnet?: string
  torrent_url?: string
  save_path?: string
  category?: string
}

export interface DownloadTask {
  hash: string
  name: string
  progress: number
  speed: number
  state: string
  size: number
  eta: number
}

export interface AnimeMetadata {
  id: number
  name_cn: string
  name: string
  summary: string
  score: number
  cover_url: string
  cover_local: string
}

export interface StaffMember {
  role: string
  name: string
}

export interface ThemeSong {
  kind: string
  title: string
  artist: string
  episodes?: string
}

export interface StreamingLink {
  platform: string
  title: string
  url: string
  season_id: string
  cover_url: string
  score: number
  total_episodes: number
  is_finished: boolean
  is_paid: boolean
  paid_note: string
}

export interface AnimeMetadataFull {
  id: number
  name_cn: string
  name: string
  summary: string
  score: number
  score_count: number
  rank: number
  cover_url: string
  air_date: string
  air_weekday: string
  total_episodes: number
  tags: string[]
  meta_tags: string[]
  staff: StaffMember[]
  theme_songs: ThemeSong[]
  streaming_links: StreamingLink[]
  official_site: string
  aliases: string[]
}

export interface UserPublic {
  id: number
  username: string
  created_at: number
  updated_at: number
  last_login_at: number
}

export interface AuthResponse {
  user: UserPublic
  token: string
  expires_at: number
}

export interface ImportFavoritesResponse {
  imported: number
  skipped: number
  total: number
}

export interface FavoriteItem {
  bangumi_id: number
  name_cn: string
  name: string
  cover_url: string
  score: number
  status: string
  episode_progress: number
  total_episodes: number
}

export interface CrawlLogEntry {
  timestamp: string
  level: 'info' | 'warn' | 'error' | 'success'
  source: string
  message: string
  url?: string
}

export interface ScheduleItem {
  title: string
  time: string
  day: string
  page?: string
  image_url?: string
}

export interface MediaSubtitle {
  path: string
  codec: string
  language: string
  title: string
  source: string
}

export interface MediaAsset {
  media_id: string
  title: string
  relative_path: string
  source_path: string
  size: number
  modified_at: number
  container: string
  duration: number
  video_codecs: string[]
  audio_codecs: string[]
  subtitle_codecs: string[]
  subtitles: MediaSubtitle[]
  probe_status: 'pending' | 'ready' | 'failed' | 'unavailable'
  probe_error: string
  direct_play_supported: boolean
  recommended_mode: 'direct_play' | 'pretranscode_hls' | 'blocked'
  watch_enabled: boolean
  watch_block_reason: string
  hls_status: 'missing' | 'queued' | 'preparing' | 'ready' | 'error'
  hls_playlist: string
  hls_updated_at: number
  hls_progress: number
  last_error: string
}

export interface MediaAssetListResponse {
  items: MediaAsset[]
  total: number
  refreshed_at: number
}

export interface WatchRoomState {
  media_id: string
  playback_mode: 'direct_play' | 'hls'
  playback_url: string
  paused: boolean
  position_seconds: number
  playback_rate: number
  updated_by: string
  updated_at: number
}

export interface WatchRoom {
  room_id: string
  name: string
  host_name: string
  owner_user_id: number
  owner_username: string
  state: WatchRoomState
  created_at: number
  updated_at: number
}

export interface WatchLobbyRoom extends WatchRoom {
  participant_count: number
  participant_usernames: string[]
}

export interface CreateWatchRoomRequest {
  name?: string
  host_name?: string
  media_id?: string
  playback_mode?: 'direct_play' | 'hls'
  playback_url?: string
}

export interface UpdateWatchRoomStateRequest {
  media_id?: string
  playback_mode?: 'direct_play' | 'hls'
  playback_url?: string
  paused?: boolean
  position_seconds?: number
  playback_rate?: number
  updated_by?: string
}

export interface WatchHistoryItem {
  entry_id: number
  user_id: number
  room_id: string
  room_name: string
  media_id: string
  media_title: string
  playback_mode: 'direct_play' | 'hls'
  position_seconds: number
  duration_seconds: number
  paused: boolean
  updated_by: string
  created_at: number
  updated_at: number
}

export interface SyncWatchHistoryRequest {
  room_id: string
  media_id?: string
  playback_mode?: 'direct_play' | 'hls'
  position_seconds?: number
  paused?: boolean
}

export interface PresenceHeartbeatRequest {
  room_id?: string
  room_name?: string
  page?: string
  status_text?: string
}

export interface OnlineUser {
  user_id: number
  username: string
  current_room_id: string
  current_room_name: string
  current_page: string
  status_text: string
  last_seen_at: number
  is_friend: boolean
}

export interface FriendRequest {
  request_id: number
  requester_user_id: number
  requester_username: string
  target_user_id: number
  target_username: string
  status: string
  created_at: number
  updated_at: number
  direction: 'incoming' | 'outgoing' | ''
}

export interface FriendSummary {
  user_id: number
  username: string
  created_at: number
  is_online: boolean
  last_seen_at: number
  current_room_id: string
  current_room_name: string
  current_page: string
  status_text: string
  unread_count: number
  last_message_preview: string
  last_message_at: number
}

export interface DirectMessage {
  message_id: number
  sender_user_id: number
  sender_username: string
  recipient_user_id: number
  recipient_username: string
  body: string
  created_at: number
  read_at: number
  is_mine: boolean
}

export interface RoomInvitation {
  invitation_id: number
  room_id: string
  room_name: string
  sender_user_id: number
  sender_username: string
  recipient_user_id: number
  recipient_username: string
  message: string
  status: string
  created_at: number
  updated_at: number
  direction: 'incoming' | 'outgoing' | ''
}

export interface FriendActionResult {
  ok: boolean
  friend_user_id: number
}

export interface RoomMessage {
  message_id: number
  room_id: string
  sender_user_id: number
  sender_username: string
  body: string
  created_at: number
  is_mine: boolean
}

export interface WatchLobbyOverview {
  rooms: WatchLobbyRoom[]
  online_users: OnlineUser[]
  friends: FriendSummary[]
  incoming_requests: FriendRequest[]
  outgoing_requests: FriendRequest[]
  incoming_room_invitations: RoomInvitation[]
  outgoing_room_invitations: RoomInvitation[]
  generated_at: number
}

// ---------------------------------------------------------------------------
// Online watch channels — mirror of app/models.py (docs/CHANNEL_ARCHITECTURE.md)
// ---------------------------------------------------------------------------

export interface ChannelInfo {
  id: string
  name: string
  enabled: boolean
  healthy: boolean
  supports_search: boolean
  supports_detail: boolean
  supports_streams: boolean
  language: string
  description: string
  external: boolean
}

export interface ChannelSearchResult {
  channel: string
  title: string
  title_original: string
  cover_url: string
  description: string
  year: string
  detail_ref: string
  extra: Record<string, unknown>
}

export interface ChannelEpisode {
  title: string
  episode_ref: string
  extra: Record<string, unknown>
}

export interface ChannelEpisodeGroup {
  title: string
  episodes: ChannelEpisode[]
}

export interface ChannelDetail {
  channel: string
  title: string
  cover_url: string
  description: string
  groups: ChannelEpisodeGroup[]
}

export interface ChannelStream {
  type: string
  url: string
  quality: string
  format: string
  headers: Record<string, string>
  expires_in: number
  note: string
}
