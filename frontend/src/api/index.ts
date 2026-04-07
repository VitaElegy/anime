import axios from 'axios'
import type { SearchResult, DownloadRequest, DownloadTask, AnimeMetadata } from '@/types'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

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

// Health
export async function getHealth(): Promise<{ status: string; qb_connected: boolean }> {
  const { data } = await api.get('/health')
  return data
}

// Favorites
export async function getFavorites(status = ''): Promise<Record<string, unknown>[]> {
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
export async function getWeeklySchedule(): Promise<Record<string, { title: string; page: string; day: string }[]>> {
  const { data } = await api.get('/schedule')
  return data
}

// Crawl history
export async function getCrawlHistory(limit = 50): Promise<Record<string, unknown>[]> {
  const { data } = await api.get('/crawl/history', { params: { limit } })
  return data
}

// Image proxy cache
export function proxyImageUrl(url: string): string {
  if (!url) return ''
  return `/api/image/proxy?url=${encodeURIComponent(url)}`
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
