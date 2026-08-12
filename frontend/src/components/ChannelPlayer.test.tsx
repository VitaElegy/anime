import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ChannelPlayer from '@/components/ChannelPlayer'
import type { ChannelStream } from '@/types'

const loadSource = vi.fn()
const attachMedia = vi.fn()
const destroy = vi.fn()
const on = vi.fn()

class FakeHls {
  static isSupported = () => true
  static Events = { MANIFEST_PARSED: 'manifestParsed', ERROR: 'error' }
  loadSource = loadSource
  attachMedia = attachMedia
  destroy = destroy
  on = on
}

vi.mock('hls.js', () => ({ default: FakeHls }))

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

const stream = (overrides: Partial<ChannelStream> = {}): ChannelStream => ({
  type: 'hls',
  url: 'https://cdn.example.com/a.m3u8',
  quality: '自动',
  format: 'm3u8',
  headers: {},
  expires_in: 0,
  note: '',
  ...overrides,
})

describe('ChannelPlayer (Renderer)', () => {
  it('plays mp4 through the backend stream proxy', () => {
    render(
      <ChannelPlayer
        title="葬送的芙莉莲 · 第1集"
        streams={[stream({ type: 'mp4', url: 'https://cdn.example.com/a.mp4', headers: { Referer: 'https://src.example/' } })]}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByText('葬送的芙莉莲 · 第1集')).toBeInTheDocument()
    const video = document.querySelector('video') as HTMLVideoElement
    expect(video.src).toContain('/api/watch/proxy/stream')
    expect(video.src).toContain(encodeURIComponent('https://cdn.example.com/a.mp4'))
    expect(video.src).toContain('referer=')
  })

  it('initializes hls.js for hls streams and shows line switcher', async () => {
    render(
      <ChannelPlayer
        title="测试"
        streams={[stream(), stream({ url: 'https://cdn.example.com/b.m3u8', quality: '高清' })]}
        onClose={vi.fn()}
      />,
    )
    await waitFor(() => expect(loadSource).toHaveBeenCalledWith(expect.stringContaining('/api/watch/proxy/stream')))
    expect(screen.getByText('自动')).toBeInTheDocument()
    expect(screen.getByText('高清')).toBeInTheDocument()
  })

  it('shows an error when no streams are available', async () => {
    render(<ChannelPlayer title="测试" streams={[]} onClose={vi.fn()} />)
    expect(await screen.findByText('该渠道暂时没有可播放的线路')).toBeInTheDocument()
  })

  it('destroys hls on unmount', async () => {
    const { unmount } = render(<ChannelPlayer title="测试" streams={[stream()]} onClose={vi.fn()} />)
    await waitFor(() => expect(loadSource).toHaveBeenCalled())
    unmount()
    expect(destroy).toHaveBeenCalled()
  })
})
