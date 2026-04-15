import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '@/api'
import WatchRoomPage from '@/pages/WatchRoomPage'
import { useAuth } from '@/contexts/useAuth'
import type { MediaAsset, WatchRoom } from '@/types'

vi.mock('@/api', () => ({
  getMediaAsset: vi.fn(),
  getRoomMessages: vi.fn(),
  getWatchLobby: vi.fn(),
  getWatchResume: vi.fn(),
  getWatchRoom: vi.fn(),
  heartbeatPresence: vi.fn(),
  listMediaLibrary: vi.fn(),
  prepareMediaHls: vi.fn(),
  scanMediaLibrary: vi.fn(),
  sendRoomInvitation: vi.fn(),
  sendRoomMessage: vi.fn(),
  syncWatchProgress: vi.fn(),
  updateWatchRoomState: vi.fn(),
}))

vi.mock('@/contexts/useAuth', () => ({
  useAuth: vi.fn(),
}))

const sampleRoom: WatchRoom = {
  room_id: 'room-1',
  name: '测试房间',
  host_name: 'elegy',
  owner_user_id: 7,
  owner_username: 'elegy',
  state: {
    media_id: '',
    playback_mode: 'direct_play',
    playback_url: '',
    paused: true,
    position_seconds: 0,
    playback_rate: 1,
    updated_by: 'elegy',
    updated_at: 1,
  },
  created_at: 1,
  updated_at: 1,
}

const sampleAsset: MediaAsset = {
  media_id: 'media-1',
  title: '房间片源测试',
  relative_path: 'downloads/room-test.mkv',
  source_path: '/downloads/room-test.mkv',
  size: 2048,
  modified_at: 1,
  container: 'mkv',
  duration: 1500,
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
  hls_playlist: '/room-test/master.m3u8',
  hls_updated_at: 1,
  last_error: '',
}

function createDeferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('WatchRoomPage', () => {
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

    vi.mocked(api.getWatchRoom).mockResolvedValue(sampleRoom)
    vi.mocked(api.getMediaAsset).mockResolvedValue(sampleAsset)
    vi.mocked(api.getWatchResume).mockResolvedValue(null)
    vi.mocked(api.listMediaLibrary).mockResolvedValue({
      items: [],
      total: 0,
      refreshed_at: 1,
    })
    vi.mocked(api.getWatchLobby).mockResolvedValue({
      rooms: [],
      online_users: [
        {
          user_id: 9,
          username: 'alice',
          current_room_id: 'room-1',
          current_room_name: '测试房间',
          current_page: 'watch_room',
          status_text: '正在同看',
          last_seen_at: 1,
          is_friend: true,
        },
      ],
      friends: [
        {
          user_id: 9,
          username: 'alice',
          created_at: 1,
          is_online: true,
          last_seen_at: 1,
          current_room_id: '',
          current_room_name: '',
          current_page: 'watch_lobby',
          status_text: '正在大厅',
          unread_count: 0,
          last_message_preview: '',
          last_message_at: 0,
        },
      ],
      incoming_requests: [],
      outgoing_requests: [],
      incoming_room_invitations: [],
      outgoing_room_invitations: [
        {
          invitation_id: 5,
          room_id: 'room-1',
          room_name: '测试房间',
          sender_user_id: 7,
          sender_username: 'elegy',
          recipient_user_id: 9,
          recipient_username: 'alice',
          message: '',
          status: 'pending',
          created_at: 1,
          updated_at: 1,
          direction: 'outgoing',
        },
      ],
      generated_at: 1,
    })
    vi.mocked(api.getRoomMessages).mockResolvedValue([
      {
        message_id: 1,
        room_id: 'room-1',
        sender_user_id: 9,
        sender_username: 'alice',
        body: '房间消息',
        created_at: 1,
        is_mine: false,
      },
    ])
    vi.mocked(api.heartbeatPresence).mockResolvedValue({
      user_id: 7,
      username: 'elegy',
      current_room_id: 'room-1',
      current_room_name: '测试房间',
      current_page: 'watch_room',
      status_text: '在房间待机',
      last_seen_at: 1,
      is_friend: false,
    })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('renders room collaboration panels with invite and room chat state', async () => {
    render(
      <MemoryRouter
        initialEntries={['/watch/room-1']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/watch/:roomId" element={<WatchRoomPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('房间成员与邀请')).toBeInTheDocument()
    expect(screen.getByText('当前在线成员')).toBeInTheDocument()
    expect(screen.getByText('你已向 1 位好友发出待处理邀请')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '已在房间' })).toBeDisabled()

    expect(screen.getByText('房间聊天')).toBeInTheDocument()
    expect(screen.getByText('房间消息')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled()
  })

  it('keeps the room visible when media details fail to load', async () => {
    vi.mocked(api.getWatchRoom).mockResolvedValue({
      ...sampleRoom,
      state: {
        ...sampleRoom.state,
        media_id: 'media-1',
        playback_url: '/api/watch/media-1/direct',
      },
    })
    vi.mocked(api.getMediaAsset).mockRejectedValue(new Error('asset down'))

    render(
      <MemoryRouter
        initialEntries={['/watch/room-1']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/watch/:roomId" element={<WatchRoomPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('测试房间')).toBeInTheDocument()
    expect(screen.getByText('当前房间已绑定片源，但片源详情加载失败：asset down')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重读片源详情' })).toBeInTheDocument()
    expect(screen.queryByText('房间不存在。')).not.toBeInTheDocument()
  })

  it('shows a real error state when room chat fails before the first snapshot loads', async () => {
    vi.mocked(api.getRoomMessages).mockRejectedValue(new Error('chat down'))

    render(
      <MemoryRouter
        initialEntries={['/watch/room-1']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/watch/:roomId" element={<WatchRoomPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('房间聊天暂时加载失败：chat down')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试聊天' })).toBeInTheDocument()
    expect(screen.queryByText('房间里还没有聊天记录，先发第一条消息吧。')).not.toBeInTheDocument()
  })

  it('shows a real error state when social context fails before the first snapshot loads', async () => {
    vi.mocked(api.getWatchLobby).mockRejectedValue(new Error('lobby down'))

    render(
      <MemoryRouter
        initialEntries={['/watch/room-1']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/watch/:roomId" element={<WatchRoomPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('房间成员与邀请暂时加载失败：lobby down')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试成员状态' })).toBeInTheDocument()
    expect(screen.queryByText('目前还没有登录用户在这个房间里心跳在线。')).not.toBeInTheDocument()
  })

  it('locks room actions for logged-in non-owners until the first room heartbeat succeeds', async () => {
    const heartbeat = createDeferred<{
      user_id: number
      username: string
      current_room_id: string
      current_room_name: string
      current_page: string
      status_text: string
      last_seen_at: number
      is_friend: boolean
    }>()

    vi.mocked(useAuth).mockReturnValue({
      user: { id: 8, username: 'guest', created_at: 0, updated_at: 0, last_login_at: 0 },
      loading: false,
      isAuthenticated: true,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
      refreshUser: vi.fn(),
    })
    vi.mocked(api.getWatchRoom).mockResolvedValue({
      ...sampleRoom,
      state: {
        ...sampleRoom.state,
        media_id: 'media-1',
        playback_url: '/api/watch/media-1/direct',
      },
    })
    vi.mocked(api.listMediaLibrary).mockResolvedValue({
      items: [sampleAsset],
      total: 1,
      refreshed_at: 1,
    })
    vi.mocked(api.heartbeatPresence).mockImplementation(() => heartbeat.promise)

    render(
      <MemoryRouter
        initialEntries={['/watch/room-1']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/watch/:roomId" element={<WatchRoomPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('正在确认你已进入这个房间。')).toBeInTheDocument()

    const playButton = screen.getByRole('button', { name: '写入播放状态' })
    const chatInput = screen.getByPlaceholderText('正在确认进入房间，暂时不能发消息')
    const switchButton = screen.getByRole('button', { name: '当前片源' })

    expect(playButton).toBeDisabled()
    expect(chatInput).toBeDisabled()
    expect(switchButton).toBeDisabled()

    heartbeat.resolve({
      user_id: 8,
      username: 'guest',
      current_room_id: 'room-1',
      current_room_name: '测试房间',
      current_page: 'watch_room',
      status_text: '在房间待机',
      last_seen_at: 1,
      is_friend: false,
    })

    await waitFor(() => expect(screen.queryByText('正在确认你已进入这个房间。')).not.toBeInTheDocument())
    await waitFor(() => expect(playButton).toBeEnabled())
    await waitFor(() => expect(chatInput).toBeEnabled())

    fireEvent.change(chatInput, { target: { value: '现在可以说话了' } })
    expect(screen.getByRole('button', { name: '发送' })).toBeEnabled()
  })
})
