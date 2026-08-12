import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '@/api'
import WatchPartyPage from '@/pages/WatchPartyPage'
import { useAuth } from '@/contexts/useAuth'
import type { MediaAsset, WatchLobbyOverview } from '@/types'

vi.mock('@/api', () => ({
  acceptFriendRequest: vi.fn(),
  acceptRoomInvitation: vi.fn(),
  createWatchRoom: vi.fn(),
  dismissRoomInvitation: vi.fn(),
  getDirectMessages: vi.fn(),
  getWatchLobby: vi.fn(),
  heartbeatPresence: vi.fn(),
  listMediaLibrary: vi.fn(),
  listWatchHistory: vi.fn(),
  prepareMediaHls: vi.fn(),
  rejectFriendRequest: vi.fn(),
  removeFriend: vi.fn(),
  scanMediaLibrary: vi.fn(),
  sendDirectMessage: vi.fn(),
  sendFriendRequest: vi.fn(),
}))

vi.mock('@/contexts/useAuth', () => ({
  useAuth: vi.fn(),
}))

const sampleAsset: MediaAsset = {
  media_id: 'media-1',
  title: 'Test Anime Episode 1',
  relative_path: 'downloads/Test Anime Episode 1.mkv',
  source_path: '/downloads/Test Anime Episode 1.mkv',
  size: 1024,
  modified_at: 1,
  container: 'mkv',
  duration: 1440,
  video_codecs: ['h264'],
  audio_codecs: ['aac'],
  subtitle_codecs: ['ass'],
  subtitles: [],
  probe_status: 'ready',
  probe_error: '',
  direct_play_supported: true,
  recommended_mode: 'direct_play',
  watch_enabled: true,
  watch_block_reason: '',
  hls_status: 'ready',
  hls_playlist: '/media-1/master.m3u8',
  hls_updated_at: 1,
  hls_progress: 100,
  last_error: '',
}

function createLobbyOverview(): WatchLobbyOverview {
  return {
    rooms: [],
    online_users: [],
    friends: [
      {
        user_id: 8,
        username: 'alice',
        created_at: 1,
        is_online: true,
        last_seen_at: 1,
        current_room_id: 'room-1',
        current_room_name: '一起看',
        current_page: 'watch_room',
        status_text: '正在同看',
        unread_count: 0,
        last_message_preview: '',
        last_message_at: 0,
      },
    ],
    incoming_requests: [],
    outgoing_requests: [],
    incoming_room_invitations: [
      {
        invitation_id: 3,
        room_id: 'room-1',
        room_name: '一起看',
        sender_user_id: 8,
        sender_username: 'alice',
        recipient_user_id: 7,
        recipient_username: 'elegy',
        message: '来一起看吧',
        status: 'pending',
        created_at: 1,
        updated_at: 1,
        direction: 'incoming',
      },
    ],
    outgoing_room_invitations: [],
    generated_at: 1,
  }
}

describe('WatchPartyPage', () => {
  beforeEach(() => {
    vi.mocked(useAuth).mockReturnValue({
      user: { id: 7, username: 'elegy', created_at: 0, updated_at: 0, last_login_at: 0 },
      loading: false,
      isAuthenticated: true,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
      refreshUser: vi.fn(),
    })

    vi.mocked(api.listMediaLibrary).mockResolvedValue({
      items: [],
      total: 0,
      refreshed_at: 1,
    })
    vi.mocked(api.listWatchHistory).mockResolvedValue([])
    vi.mocked(api.getDirectMessages).mockResolvedValue([])
    vi.mocked(api.heartbeatPresence).mockResolvedValue({
      user_id: 7,
      username: 'elegy',
      current_room_id: '',
      current_room_name: '',
      current_page: 'watch_lobby',
      status_text: '在放映大厅',
      last_seen_at: 1,
      is_friend: false,
    })
    vi.mocked(api.getWatchLobby).mockResolvedValue(createLobbyOverview())
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('renders incoming room invitations and friend danger actions', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <WatchPartyPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('收到的房间邀请')).toBeInTheDocument()
    expect(screen.getByText('alice 邀请你进入「一起看」')).toBeInTheDocument()
    expect(screen.getByText('留言：来一起看吧')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '看房间' })).toHaveAttribute('href', '/watch/room-1')

    fireEvent.click(screen.getByRole('button', { name: '好友与聊天' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '删除好友' })).toBeInTheDocument()
    })
  })

  it('keeps lobby content visible when media library loading fails', async () => {
    vi.mocked(api.listMediaLibrary).mockRejectedValue(new Error('library offline'))

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <WatchPartyPage />
      </MemoryRouter>,
    )

    // Lobby tab keeps working even though the media library request failed.
    expect(await screen.findByText('alice 邀请你进入「一起看」')).toBeInTheDocument()
    expect(screen.getByText('收到的房间邀请')).toBeInTheDocument()

    // The media-library error only shows on its own tab, not in the lobby.
    fireEvent.click(screen.getByRole('button', { name: '发起同看' }))
    expect(await screen.findByText('媒体库暂时加载失败：library offline')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试媒体库' })).toBeInTheDocument()
    expect(screen.queryByText(/当前还没有可用片源/)).not.toBeInTheDocument()
  })

  it('keeps media library visible when lobby loading fails', async () => {
    vi.mocked(api.listMediaLibrary).mockResolvedValue({
      items: [sampleAsset],
      total: 1,
      refreshed_at: 1,
    })
    vi.mocked(api.getWatchLobby).mockRejectedValue(new Error('lobby unavailable'))

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <WatchPartyPage />
      </MemoryRouter>,
    )

    // Media library keeps rendering on its own tab even though the lobby failed.
    fireEvent.click(screen.getByRole('button', { name: '发起同看' }))
    expect((await screen.findAllByText('Test Anime Episode 1')).length).toBeGreaterThan(0)
    expect(screen.queryByText('目前还没有登录用户在大厅或房间里在线。')).not.toBeInTheDocument()

    // Lobby tab shows the real error state instead of pretending everything is fine.
    fireEvent.click(screen.getByRole('button', { name: '大厅动态' }))
    expect(await screen.findByText('放映大厅暂时加载失败：lobby unavailable')).toBeInTheDocument()
    expect((await screen.findAllByRole('button', { name: '重试大厅' })).length).toBeGreaterThan(0)
  })
})
