/**
 * Hermetic backend contract tests (docs/E2E_TESTING.md §3.2).
 *
 * These hit the REAL backend (ANIME_E2E_FIXTURE=1) and the REAL StreamProxy,
 * but never the internet: the registry contains only the FixtureChannel and
 * the proxy upstream is the local fixture server. They prove the
 * 渠道 → 集数 → 实际观看 API chain works end to end.
 */
import { expect, test } from '@playwright/test'

const BACKEND = 'http://127.0.0.1:8000'
const FIXTURE_STREAM = 'http://127.0.0.1:8901/fixture.webm'

test('channels list contains only the fixture provider (healthy)', async ({ request }) => {
  const res = await request.get(`${BACKEND}/api/watch/channels`)
  expect(res.status()).toBe(200)
  const channels = (await res.json()) as Array<{ id: string; healthy: boolean }>
  expect(channels).toHaveLength(1)
  expect(channels[0].id).toBe('fixture')
  expect(channels[0].healthy).toBe(true)
})

test('Chinese keyword hits the fixture channel via the real aggregator', async ({ request }) => {
  const res = await request.get(`${BACKEND}/api/watch/search`, { params: { q: '葬送的芙莉莲' } })
  expect(res.status()).toBe(200)
  const hits = (await res.json()) as Array<{ channel: string; detail_ref: string }>
  expect(hits).toHaveLength(1)
  expect(hits[0].channel).toBe('fixture')
  expect(hits[0].detail_ref).toBe('fixture:frieren')
})

test('detail returns episode groups through the real registry', async ({ request }) => {
  const res = await request.get(`${BACKEND}/api/watch/fixture/detail`, { params: { ref: 'fixture:frieren' } })
  expect(res.status()).toBe(200)
  const detail = (await res.json()) as { channel: string; groups: Array<{ episodes: unknown[] }> }
  expect(detail.channel).toBe('fixture')
  expect(detail.groups).toHaveLength(1)
  expect(detail.groups[0].episodes).toHaveLength(3)
})

test('streams resolve to the local fixture webm', async ({ request }) => {
  const res = await request.get(`${BACKEND}/api/watch/fixture/streams`, { params: { ref: 'fixture:ep:1' } })
  expect(res.status()).toBe(200)
  const streams = (await res.json()) as Array<{ type: string; url: string }>
  expect(streams).toHaveLength(1)
  expect(streams[0].type).toBe('web')
  expect(streams[0].url).toBe(FIXTURE_STREAM)
})

test('stream proxy plays the fixture webm with Range 206', async ({ request }) => {
  const res = await request.get(`${BACKEND}/api/watch/proxy/stream`, {
    params: { url: FIXTURE_STREAM },
    headers: { Range: 'bytes=0-1023' },
  })
  expect(res.status()).toBe(206)
  expect(res.headers()['content-type']).toContain('video/webm')
  expect(res.headers()['content-range']).toMatch(/^bytes 0-1023\/\d+$/)
  const body = await res.body()
  expect(body.byteLength).toBe(1024)
  // WebM magic: 0x1A 0x45 0xDF 0xA3
  expect(body[0]).toBe(0x1a)
  expect(body[1]).toBe(0x45)
  expect(body[2]).toBe(0xdf)
  expect(body[3]).toBe(0xa3)
})

test('stream proxy still blocks non-whitelisted hosts in fixture mode', async ({ request }) => {
  const res = await request.get(`${BACKEND}/api/watch/proxy/stream`, {
    params: { url: 'http://evil.example.com/x.webm' },
  })
  expect(res.status()).toBe(403)
})
