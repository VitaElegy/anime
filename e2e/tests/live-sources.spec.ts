/**
 * OPTIONAL live-source verification (docs/E2E_TESTING.md §3.3).
 *
 * Skipped unless ANIME_E2E_LIVE=1. Requires a manually started backend that is
 * NOT in fixture mode (real channels) with network reachable — e.g.:
 *
 *   ANIME_HTTP_PROXY=http://127.0.0.1:7892 \
 *     python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
 *   ANIME_E2E_LIVE=1 ANIME_E2E_LIVE_BACKEND=http://127.0.0.1:8001 \
 *     npx playwright test tests/live-sources.spec.ts
 *
 * It proves the real AnimeHeaven chain: search → detail → streams → proxy 206.
 */
import { expect, test } from '@playwright/test'

const LIVE = process.env.ANIME_E2E_LIVE === '1'
const BACKEND = process.env.ANIME_E2E_LIVE_BACKEND || 'http://127.0.0.1:8001'

test.skip(!LIVE, 'set ANIME_E2E_LIVE=1 to run live-source tests (manual backend + proxy required)')

test('AnimeHeaven live: search → detail → streams → proxy Range 206', async ({ request }) => {
  const search = await request.get(`${BACKEND}/api/watch/search`, { params: { q: 'frieren' } })
  expect(search.status()).toBe(200)
  const hits = (await search.json()) as Array<{ channel: string; detail_ref: string }>
  const heaven = hits.find((h) => h.channel === 'animeheaven')
  expect(heaven, 'animeheaven should be healthy and hit').toBeTruthy()

  const detail = await request.get(`${BACKEND}/api/watch/animeheaven/detail`, {
    params: { ref: heaven!.detail_ref },
  })
  expect(detail.status()).toBe(200)
  const detailJson = (await detail.json()) as { groups?: Array<{ episodes?: Array<{ episode_ref: string }> }> }
  const episode = detailJson.groups?.[0]?.episodes?.[0]
  expect(episode, 'animeheaven should expose episodes').toBeTruthy()

  const streams = await request.get(`${BACKEND}/api/watch/animeheaven/streams`, {
    params: { ref: episode!.episode_ref },
  })
  expect(streams.status()).toBe(200)
  const list = (await streams.json()) as Array<{ type: string; url: string }>
  const mp4 = list.find((s) => s.type === 'mp4')
  expect(mp4, 'animeheaven should resolve an mp4 direct link').toBeTruthy()

  const prox = await request.get(`${BACKEND}/api/watch/proxy/stream`, {
    params: { url: mp4!.url, referer: 'https://animeheaven.me/' },
    headers: { Range: 'bytes=0-2047' },
  })
  expect(prox.status()).toBe(206)
  expect(prox.headers()['content-type']).toContain('video/mp4')
  const body = await prox.body()
  expect(body.byteLength).toBe(2048)
})

test('Anikoto live: search → detail → streams → HLS master/sub/TS segment', async ({ request }) => {
  const search = await request.get(`${BACKEND}/api/watch/search`, { params: { q: 'frieren' } })
  expect(search.status()).toBe(200)
  const hits = (await search.json()) as Array<{ channel: string; detail_ref: string; title?: string }>
  const anikoto = hits.find(
    (h) => h.channel === 'anikoto' && (h.title || '').includes('Frieren: Beyond Journey'),
  )
  expect(anikoto, 'anikoto should be healthy and hit the main Frieren entry').toBeTruthy()

  const detail = await request.get(`${BACKEND}/api/watch/anikoto/detail`, {
    params: { ref: anikoto!.detail_ref },
  })
  expect(detail.status()).toBe(200)
  const detailJson = (await detail.json()) as { groups?: Array<{ episodes?: Array<{ episode_ref: string }> }> }
  const episode = detailJson.groups?.[0]?.episodes?.[0]
  expect(episode, 'anikoto should expose episodes').toBeTruthy()

  const streams = await request.get(`${BACKEND}/api/watch/anikoto/streams`, {
    params: { ref: episode!.episode_ref },
  })
  expect(streams.status()).toBe(200)
  const list = (await streams.json()) as Array<{ type: string; url: string; headers?: Record<string, string> }>
  const hls = list.find((s) => s.type === 'hls')
  expect(hls, 'anikoto should resolve an HLS stream').toBeTruthy()
  const referer = hls!.headers?.Referer || 'https://vidtube.site/'

  // master -> sub-playlist -> segment through the REAL stream proxy.
  const master = await request.get(`${BACKEND}/api/watch/proxy/stream`, {
    params: { url: hls!.url, referer },
  })
  expect(master.status()).toBe(200)
  const masterText = await master.text()
  expect(masterText).toContain('#EXTM3U')
  const subLine = masterText
    .split('\n')
    .map((l) => l.trim())
    .find((l) => l && !l.startsWith('#'))
  expect(subLine, 'master should reference a sub-playlist').toBeTruthy()

  const subUrl = subLine!.startsWith('/') ? `${BACKEND}${subLine}` : subLine!
  const sub = await request.get(subUrl)
  expect(sub.status()).toBe(200)
  const subText = await sub.text()
  expect(subText).toContain('#EXTM3U')
  const segLine = subText
    .split('\n')
    .map((l) => l.trim())
    .find((l) => l && !l.startsWith('#'))
  expect(segLine, 'sub-playlist should reference segments').toBeTruthy()

  const segUrl = segLine!.startsWith('/') ? `${BACKEND}${segLine}` : segLine!
  const seg = await request.get(segUrl)
  expect(seg.status()).toBe(200)
  const body = await seg.body()
  expect(body.byteLength).toBeGreaterThan(1024)
  // TS sync bytes at offset 0: proxy strips megaplay's 252B PNG prefix and
  // vidtube serves raw MPEG-TS — both must start with 0x47 0x40.
  expect(body[0]).toBe(0x47)
  expect(body[1]).toBe(0x40)
})
