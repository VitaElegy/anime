import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '@/api'
import HomePage from '@/pages/HomePage'

vi.mock('@/api', () => ({
  batchResolveCovers: vi.fn(),
  getDownloadProgress: vi.fn(),
  proxyImageUrl: vi.fn((url: string) => url),
  searchSubsPlease: vi.fn(),
}))

describe('HomePage', () => {
  beforeEach(() => {
    vi.mocked(api.searchSubsPlease).mockResolvedValue({
      items: [
        {
          title: '[SubsPlease] Sousou no Frieren - 01 (1080p) [ABC123].mkv',
          magnet: 'magnet:?xt=urn:btih:test',
          torrent_url: 'https://example.com/frieren.torrent',
          size: '1.4 GB',
          seeders: 120,
          leechers: 4,
          date: '2026-04-15',
          source: 'SubsPlease',
        },
      ],
      total: 1,
      source: 'subsplease',
    })
    vi.mocked(api.getDownloadProgress).mockResolvedValue([])
    vi.mocked(api.batchResolveCovers).mockResolvedValue([
      {
        title: '[SubsPlease] Sousou no Frieren - 01 (1080p) [ABC123].mkv',
        title_hash: 'hash-1',
        cover_url: 'https://example.com/frieren.jpg',
        bangumi_id: 123,
        name_cn: '葬送的芙莉莲',
        name: 'Sousou no Frieren',
      },
    ])
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('opens anime detail first from latest releases instead of jumping straight to search', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <HomePage />
      </MemoryRouter>,
    )

    const cardTitle = await screen.findByText('葬送的芙莉莲')
    const detailLink = cardTitle.closest('a')

    expect(detailLink).not.toBeNull()
    const href = detailLink?.getAttribute('href') || ''
    const detailUrl = new URL(href, 'http://localhost')

    expect(detailUrl.pathname).toBe('/anime/123')
    expect(detailUrl.searchParams.get('title')).toBe('葬送的芙莉莲')
    expect(detailUrl.searchParams.get('rawTitle')).toBe('[SubsPlease] Sousou no Frieren - 01 (1080p) [ABC123].mkv')
    expect(href).not.toContain('/search?q=')
  })
})
