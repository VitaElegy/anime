import axios from 'axios'
import type {
  SearchResult,
  DownloadRequest,
  DownloadTask,
  AnimeMetadata,
  AuthResponse,
  FavoriteItem,
  ImportFavoritesResponse,
  MediaAsset,
  MediaAssetListResponse,
  UserPublic,
  WatchRoom,
  WatchLobbyOverview,
  WatchHistoryItem,
  CreateWatchRoomRequest,
  SyncWatchHistoryRequest,
  UpdateWatchRoomStateRequest,
  PresenceHeartbeatRequest,
  OnlineUser,
  FriendRequest,
  FriendActionResult,
  DirectMessage,
  RoomInvitation,
  RoomMessage,
} from '@/types'

const AUTH_TOKEN_KEY = 'anime_auth_token'

let authToken = ''

function readStoredToken(): string {
  if (typeof window === 'undefined') return ''
  return window.localStorage.getItem(AUTH_TOKEN_KEY) || ''
}

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

api.interceptors.request.use((config) => {
  const token = authToken || readStoredToken()
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export function setApiAuthToken(token: string) {
  authToken = token
}

export function getStoredAuthToken(): string {
  return readStoredToken()
}

export function persistAuthToken(token: string) {
  authToken = token
  if (typeof window !== 'undefined') {
    if (token) {
      window.localStorage.setItem(AUTH_TOKEN_KEY, token)
    } else {
      window.localStorage.removeItem(AUTH_TOKEN_KEY)
    }
  }
}

// Auth
export async function registerAccount(username: string, password: string): Promise<AuthResponse> {
  const { data } = await api.post('/auth/register', { username, password })
  return data
}

export async function loginAccount(username: string, password: string): Promise<AuthResponse> {
  const { data } = await api.post('/auth/login', { username, password })
  return data
}

export async function getCurrentUser(): Promise<UserPublic> {
  const { data } = await api.get('/auth/me')
  return data
}

export async function logoutAccount() {
  const { data } = await api.post('/auth/logout')
  return data
}

export async function importLegacyFavorites(): Promise<ImportFavoritesResponse> {
  const { data } = await api.post('/auth/import-legacy-favorites')
  return data
}

// Search
export async function searchNyaa(q: string, page = 1, filter = 0, category = '1_0'): Promise<SearchResult> {
  const { data } = await api.get('/search/nyaa', { params: { q, page, filter, category } })
  return data
}

export async function searchSubsPlease(q = '', quality = 1080): Promise<SearchResult> {
  const { data } = await api.get('/search/subsplease', { params: { q, quality } })
  return data
}

export async function searchAll(q: string): Promise<SearchResult[]> {
  const { data } = await api.get('/search/all', { params: { q } })
  return data
}

// Download
export async function addDownload(req: DownloadRequest) {
  const { data } = await api.post('/download', req)
  return data
}

export async function addBatchDownload(items: DownloadRequest[]) {
  const { data } = await api.post('/download/batch', { items })
  return data
}

export async function getDownloadProgress(category = ''): Promise<DownloadTask[]> {
  const { data } = await api.get('/download/progress', { params: { category } })
  return data
}

export async function getSingleProgress(hash: string): Promise<DownloadTask> {
  const { data } = await api.get(`/download/progress/${hash}`)
  return data
}

export async function pauseTorrent(hash: string) {
  const { data } = await api.put(`/download/${hash}/pause`)
  return data
}

export async function resumeTorrent(hash: string) {
  const { data } = await api.put(`/download/${hash}/resume`)
  return data
}

export async function deleteTorrent(hash: string, deleteFiles = false) {
  const { data } = await api.delete(`/download/${hash}`, { params: { delete_files: deleteFiles } })
  return data
}

// Metadata
export async function searchMetadata(q: string, limit = 25): Promise<AnimeMetadata[]> {
  const { data } = await api.get('/metadata/search', { params: { q, limit, _t: Date.now() } })
  return data
}

export async function getMetadata(subjectId: number): Promise<AnimeMetadata> {
  const { data } = await api.get(`/metadata/${subjectId}`)
  return data
}

export function getCoverUrl(subjectId: number): string {
  return `/api/metadata/${subjectId}/cover`
}

export function normalizeExternalImageUrl(url: string): string {
  const trimmed = url.trim()
  if (!trimmed) return ''
  if (trimmed.startsWith('//')) return `https:${trimmed}`
  if (trimmed.startsWith('/')) return trimmed

  try {
    const parsed = new URL(trimmed)
    if ((parsed.hostname === 'lain.bgm.tv' || parsed.hostname === 'bgm.tv' || parsed.hostname.endsWith('.bgm.tv')) && parsed.protocol === 'http:') {
      parsed.protocol = 'https:'
    }
    return parsed.toString()
  } catch {
    return trimmed
  }
}

// Health
export async function getHealth(): Promise<{ status: string; qb_connected: boolean }> {
  const { data } = await api.get('/health')
  return data
}

// Favorites
export async function getFavorites(status = ''): Promise<FavoriteItem[]> {
  const { data } = await api.get('/favorites', { params: { status } })
  return data
}

export async function addFavorite(item: { bangumi_id: number; name_cn: string; name: string; cover_url: string; score: number }) {
  const { data } = await api.post('/favorites', item)
  return data
}

export async function removeFavorite(bangumiId: number) {
  const { data } = await api.delete(`/favorites/${bangumiId}`)
  return data
}

export async function updateFavorite(bangumiId: number, updates: Record<string, unknown>) {
  const { data } = await api.put(`/favorites/${bangumiId}`, updates)
  return data
}

// Schedule
export interface WeeklyScheduleItem {
  title: string
  page: string
  day: string
  time: string
  image_url: string
}

export async function getWeeklySchedule(): Promise<Record<string, WeeklyScheduleItem[]>> {
  const { data } = await api.get('/schedule')
  return data
}

export interface CalendarDayEntry {
  day: string
  bangumi_id: number
  title: string
  raw_title: string
  cover_url: string
  time: string
  size: string
  source: string
  date: string
  page: string
}

export interface CalendarTimelineItem {
  bangumi_id: number
  title: string
  raw_title: string
  cover_url: string
  size: string
  source: string
  date: string
}

export interface CalendarOverview {
  week: Record<string, CalendarDayEntry[]>
  timeline: CalendarTimelineItem[]
  generated_at: number
}

export async function getCalendarOverview(forceRefresh = false, quality = 1080): Promise<CalendarOverview> {
  const { data } = await api.get('/calendar', {
    params: {
      quality,
      force_refresh: forceRefresh || undefined,
    },
  })
  return data
}

// Crawl history
export async function getCrawlHistory(limit = 50): Promise<Record<string, unknown>[]> {
  const { data } = await api.get('/crawl/history', { params: { limit } })
  return data
}

// Image proxy cache
export function proxyImageUrl(url: string): string {
  const normalized = normalizeExternalImageUrl(url)
  if (!normalized) return ''
  if (normalized.startsWith('/')) return normalized
  return `/api/image/proxy?url=${encodeURIComponent(normalized)}`
}

export async function prefetchImages(urls: string[]) {
  if (urls.length === 0) return
  const { data } = await api.get('/image/batch_prefetch', { params: { urls: urls.join(',') } })
  return data
}

// Cover resolution
export async function batchResolveCovers(titles: string[]): Promise<{ title: string; title_hash: string; cover_url: string; bangumi_id: number; name_cn: string; name: string }[]> {
  const { data } = await api.post('/covers/batch', { titles })
  return data
}

// AniList (native Chinese/Japanese/English search)
export interface AniListAnime {
  id: number
  title_romaji: string
  title_english: string
  title_native: string
  title_preferred: string
  cover_large: string
  cover_medium: string
  banner: string
  score: number
  episodes: number
  status: string
  season: string
  season_year: number
  description: string
  genres: string[]
  format: string
  airing_at?: number
  next_episode?: number
}

export async function anilistSearch(q: string, page = 1, limit = 20): Promise<{ items: AniListAnime[]; total: number; has_next: boolean }> {
  const { data } = await api.get('/anilist/search', { params: { q, page, limit } })
  return data
}

export async function anilistTrending(season = '', year = 0, limit = 20): Promise<{ items: AniListAnime[]; total: number }> {
  const { data } = await api.get('/anilist/trending', { params: { season, year, limit } })
  return data
}

export async function anilistSchedule(page = 1, limit = 50): Promise<{ items: AniListAnime[]; total: number }> {
  const { data } = await api.get('/anilist/schedule', { params: { page, limit } })
  return data
}

// Media library
export async function listMediaLibrary(refresh = false): Promise<MediaAssetListResponse> {
  const { data } = await api.get('/media/library', { params: { refresh } })
  return data
}

export async function scanMediaLibrary(): Promise<MediaAssetListResponse> {
  const { data } = await api.post('/media/scan')
  return data
}

export async function getMediaAsset(mediaId: string): Promise<MediaAsset> {
  const { data } = await api.get(`/media/${mediaId}`)
  return data
}

export async function prepareMediaHls(mediaId: string, force = false): Promise<MediaAsset> {
  const { data } = await api.post(`/media/${mediaId}/prepare`, null, { params: { force } })
  return data
}

// Watch rooms
export async function listWatchRooms(mineOnly = false): Promise<WatchRoom[]> {
  const { data } = await api.get('/watch/rooms', { params: mineOnly ? { mine: true } : undefined })
  return data
}

export async function createWatchRoom(req: CreateWatchRoomRequest): Promise<WatchRoom> {
  const { data } = await api.post('/watch/rooms', req)
  return data
}

export async function getWatchRoom(roomId: string): Promise<WatchRoom> {
  const { data } = await api.get(`/watch/rooms/${roomId}`)
  return data
}

export async function updateWatchRoomState(roomId: string, req: UpdateWatchRoomStateRequest): Promise<WatchRoom> {
  const { data } = await api.put(`/watch/rooms/${roomId}/state`, req)
  return data
}

export async function getRoomMessages(roomId: string, limit = 80): Promise<RoomMessage[]> {
  const { data } = await api.get(`/watch/rooms/${roomId}/messages`, { params: { limit } })
  return data
}

export async function sendRoomMessage(roomId: string, body: string): Promise<RoomMessage> {
  const { data } = await api.post(`/watch/rooms/${roomId}/messages`, { body })
  return data
}

export async function getWatchLobby(): Promise<WatchLobbyOverview> {
  const { data } = await api.get('/social/lobby')
  return data
}

export async function heartbeatPresence(req: PresenceHeartbeatRequest): Promise<OnlineUser> {
  const { data } = await api.post('/social/presence', req)
  return data
}

export async function sendFriendRequest(username: string): Promise<FriendRequest> {
  const { data } = await api.post('/social/friends/requests', { username })
  return data
}

export async function acceptFriendRequest(requestId: number): Promise<FriendRequest> {
  const { data } = await api.post(`/social/friends/requests/${requestId}/accept`)
  return data
}

export async function rejectFriendRequest(requestId: number): Promise<FriendRequest> {
  const { data } = await api.post(`/social/friends/requests/${requestId}/reject`)
  return data
}

export async function removeFriend(friendUserId: number): Promise<FriendActionResult> {
  const { data } = await api.delete(`/social/friends/${friendUserId}`)
  return data
}

export async function sendRoomInvitation(roomId: string, friendUserId: number, message = ''): Promise<RoomInvitation> {
  const { data } = await api.post(`/social/rooms/${roomId}/invite`, { friend_user_id: friendUserId, message })
  return data
}

export async function acceptRoomInvitation(invitationId: number): Promise<RoomInvitation> {
  const { data } = await api.post(`/social/room-invitations/${invitationId}/accept`)
  return data
}

export async function dismissRoomInvitation(invitationId: number): Promise<RoomInvitation> {
  const { data } = await api.post(`/social/room-invitations/${invitationId}/dismiss`)
  return data
}

export async function getDirectMessages(friendUserId: number, limit = 50): Promise<DirectMessage[]> {
  const { data } = await api.get(`/social/friends/${friendUserId}/messages`, { params: { limit } })
  return data
}

export async function sendDirectMessage(friendUserId: number, body: string): Promise<DirectMessage> {
  const { data } = await api.post(`/social/friends/${friendUserId}/messages`, { body })
  return data
}

export async function listWatchHistory(limit = 8): Promise<WatchHistoryItem[]> {
  const { data } = await api.get('/watch/history', { params: { limit } })
  return data
}

export async function getWatchResume(roomId: string, mediaId = ''): Promise<WatchHistoryItem | null> {
  const { data } = await api.get('/watch/history/resume', { params: { room_id: roomId, media_id: mediaId } })
  return data
}

export async function syncWatchProgress(req: SyncWatchHistoryRequest): Promise<WatchHistoryItem> {
  const { data } = await api.post('/watch/history/progress', req)
  return data
}
