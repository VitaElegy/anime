import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '@/api'
import AnimeDetailPage from '@/pages/AnimeDetailPage'
import type { ChannelDetail, ChannelInfo, ChannelSearchResult, ChannelStream } from '@/types'

vi.mock('@/api', () => ({
  addFavorite: vi.fn(),
  anilistSearch: vi.fn(),
  getCoverUrl: vi.fn(() => 'https://example.com/cover.jpg'),
  getFavorites: vi.fn(),
  getMetadata: vi.fn(),
  getMetadataFull: vi.fn(),
  getStreamingLinks: vi.fn(),
  normalizeExternalImageUrl: vi.fn((url: string) => url),
  proxyImageUrl: vi.fn((url: string) => url),
  removeFavorite: vi.fn(),
  searchMetadata: vi.fn(),
  watchChannels: vi.fn(),
  watchDetail: vi.fn(),
  watchExternal: vi.fn(),
  watchSearch: vi.fn(),
  watchStreams: vi.fn(),
}))

vi.mock('@/contexts/useAuth', () => ({
  useAuth: () => ({ isAuthenticated: false }),
}))

// Renderer is tested separately (ChannelPlayer.test.tsx); here we only assert
// the journey reaches the player with the right stream payload.
vi.mock('@/components/ChannelPlayer', () => ({
  default: ({ title, streams, onClose }: { title: string; streams: ChannelStream[]; onClose: () => void }) => (
    <div data-testid="channel-player">
      <span>{title}</span>
      <span data-testid="player-streams">{streams.map((s) => s.url).join(',')}</span>
      <button onClick={onClose}>close-player</button>
    </div>
  ),
}))

const channelInfo: ChannelInfo = {
  id: 'animeheaven',
  name: 'AnimeHeaven',
  enabled: true,
  healthy: true,
  supports_search: true,
  supports_detail: true,
  supports_streams: true,
  language: 'zh',
  description: 'backup',
  external: false,
}

const channelHit: ChannelSearchResult = {
  channel: 'animeheaven',
  title: 'Sousou no Frieren',
  title_original: 'Sousou no Frieren',
  cover_url: '',
  description: '',
  year: '2023',
  detail_ref: 'frieren::ref',
  extra: {},
}

const channelDetail: ChannelDetail = {
  channel: 'animeheaven',
  title: 'Sousou no Frieren',
  cover_url: '',
  description: '',
  groups: [
    {
      title: '字幕',
      episodes: [{ title: '第 1 集', episode_ref: 'frieren::1', extra: {} }],
    },
  ],
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/anime/0?title=%E8%91%AC%E9%80%81%E7%9A%84%E8%8A%99%E8%8E%89%E8%8E%B2&rawTitle=Sousou%20no%20Frieren']}>
      <Routes>
        <Route path="/anime/:subjectId" element={<AnimeDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('AnimeDetailPage 在线渠道旅程', () => {
  beforeEach(() => {
    vi.mocked(api.getFavorites).mockResolvedValue([])
    vi.mocked(api.searchMetadata).mockResolvedValue([])
    vi.mocked(api.anilistSearch).mockResolvedValue({ items: [], total: 0, has_next: false })
    vi.mocked(api.watchChannels).mockResolvedValue([channelInfo])
    vi.mocked(api.watchSearch).mockResolvedValue([channelHit])
    vi.mocked(api.watchDetail).mockResolvedValue(channelDetail)
    vi.mocked(api.watchStreams).mockResolvedValue([
      {
        type: 'hls',
        url: 'https://cdn.example.com/master.m3u8',
        quality: '1080p',
        format: 'm3u8',
        headers: {},
        expires_in: 120,
        note: '',
      },
    ])
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('中文搜索 → 渠道 → 集数 → 播放器（Renderer 收到流）', async () => {
    renderPage()

    // 1. 渠道命中渲染（中文关键词扩展后聚合结果）
    // 注意：'Sousou no Frieren' 也会出现在页头副标题，必须用渠道卡片按钮（含「选集」）定位
    const hit = await screen.findByRole('button', { name: /选集/ })
    expect(api.watchSearch).toHaveBeenCalledWith('Sousou no Frieren')

    // 2. 点击渠道 → 集数分组展开
    fireEvent.click(hit)
    const episode = await screen.findByText('第 1 集')
    expect(api.watchDetail).toHaveBeenCalledWith('animeheaven', 'frieren::ref')

    // 3. 点击某集 → 取流 → 播放器打开并收到流
    fireEvent.click(episode)
    await waitFor(() => expect(api.watchStreams).toHaveBeenCalledWith('animeheaven', 'frieren::1'))
    const player = await screen.findByTestId('channel-player')
    expect(player).toHaveTextContent('Sousou no Frieren · 第 1 集')
    expect(screen.getByTestId('player-streams')).toHaveTextContent('https://cdn.example.com/master.m3u8')
  })

  it('渠道详情失败时优雅降级，不阻断页面', async () => {
    vi.mocked(api.watchDetail).mockRejectedValue(new Error('boom'))
    renderPage()

    const hit = await screen.findByRole('button', { name: /选集/ })
    fireEvent.click(hit)

    expect(await screen.findByText('渠道暂时不可用，请稍后再试')).toBeInTheDocument()
    expect(screen.queryByText('第 1 集')).not.toBeInTheDocument()
  })
})
