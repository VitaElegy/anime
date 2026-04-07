export interface TorrentItem {
  title: string
  magnet: string
  torrent_url: string
  size: string
  seeders: number
  leechers: number
  date: string
  source: string
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
