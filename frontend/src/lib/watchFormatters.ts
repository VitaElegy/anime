/**
 * Shared formatters and error helpers used across the Watch Party / Watch
 * Room pages. Extracted in P1-#8 as the first step in thinning those pages
 * down — the identical copies of these functions used to live in both
 * components and drift independently.
 */

import type { MediaAsset } from '@/types'

export function formatDateTime(ts: number): string {
  if (!ts) return '未知'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

export function formatPosition(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

export function formatRelativeTime(ts: number): string {
  if (!ts) return '刚刚'
  const diff = Math.max(0, Math.floor(Date.now() / 1000) - ts)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return `${Math.floor(diff / 86400)} 天前`
}

export function shortError(message: string, maxLength = 300): string {
  if (!message) return ''
  return message.length > maxLength ? `${message.slice(0, maxLength)}...` : message
}

export function extractErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response
    if (response?.data?.detail) return response.data.detail
  }
  if (error instanceof Error && error.message) return error.message
  return '操作失败，请稍后重试'
}

export function extractErrorStatus(error: unknown): number | null {
  if (typeof error === 'object' && error && 'response' in error) {
    const response = (error as { response?: { status?: number } }).response
    if (typeof response?.status === 'number') return response.status
  }
  return null
}

export function isAssetBlocked(asset: MediaAsset | null | undefined): boolean {
  return Boolean(
    asset && (!asset.watch_enabled || asset.recommended_mode === 'blocked' || asset.probe_status === 'failed'),
  )
}

export function getAssetBlockReason(asset: MediaAsset | null | undefined): string {
  if (!asset) return ''
  return shortError(asset.watch_block_reason || asset.probe_error || asset.last_error || '片源暂时不可用')
}

/**
 * Human label for the social presence of a lobby entry / friend / room
 * participant. Kept here because it's used identically in the room and the
 * lobby views.
 */
export function socialStatusText(item: {
  current_room_name?: string
  current_page?: string
  status_text?: string
}): string {
  if (item.current_room_name) return `正在 ${item.current_room_name}`
  if (item.status_text) return item.status_text
  if (item.current_page === 'watch_room') return '正在房间内'
  if (item.current_page === 'watch_lobby') return '正在大厅'
  return '在线'
}
