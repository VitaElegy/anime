/**
 * Core UX journey — hermetic end-to-end (docs/E2E_TESTING.md §3.1).
 *
 * 中文搜 → 卡片 → 详情页渠道 → 集数 → 实际观看.
 *
 * Only the metadata layer (Bangumi/AniList/Bilibili) is mocked — it is outside
 * this repo's control and would make CI flaky. The watch layer
 * (/api/watch/*) and the StreamProxy run the REAL backend, and the video is a
 * real webm served by the local fixture server, so the final assertion
 * (video.readyState >= 2) proves actual playback through the proxy.
 */
import { expect, test } from '@playwright/test'

const FIXTURE_ANIME = {
  id: 12345,
  title: '葬送的芙莉莲',
  titleOriginal: 'Sousou no Frieren',
  coverImage: '',
  description: 'E2E fixture metadata',
  year: '2023',
  score: 9.2,
  source: 'Bangumi',
}

const animeMeta = {
  id: 12345,
  name_cn: '葬送的芙莉莲',
  name: 'Sousou no Frieren',
  summary: 'E2E fixture metadata',
  score: 9.2,
  cover_url: '',
  cover_local: '',
}

const fullMeta = {
  id: 12345,
  name_cn: '葬送的芙莉莲',
  name: 'Sousou no Frieren',
  summary: 'E2E fixture metadata',
  score: 9.2,
  score_count: 0,
  rank: 0,
  cover_url: '',
  air_date: '2023-09-29',
  air_weekday: '周五',
  total_episodes: 28,
  tags: [],
  meta_tags: [],
  staff: [],
  theme_songs: [],
  streaming_links: [],
  official_site: '',
  aliases: [],
}

test.beforeEach(async ({ context }) => {
  // Metadata layer is outside the repo's control -> deterministic mocks.
  await context.route('**/api/search/anime**', (route) =>
    route.fulfill({ json: { anime: [FIXTURE_ANIME], total: 1 } })
  )
  await context.route('**/api/search/torrents**', (route) => route.fulfill({ json: { torrents: [] } }))
  await context.route('**/api/metadata/12345/full**', (route) => route.fulfill({ json: fullMeta }))
  await context.route('**/api/metadata/12345/streaming**', (route) => route.fulfill({ json: [] }))
  await context.route('**/api/metadata/12345', (route) => route.fulfill({ json: animeMeta }))
  await context.route('**/api/metadata/search**', (route) => route.fulfill({ json: [animeMeta] }))
  await context.route('**/api/anilist/search**', (route) => route.fulfill({ json: { items: [] } }))
  await context.route('**/api/auth/me**', (route) => route.fulfill({ status: 401, json: { detail: 'unauthorized' } }))
})

test('中文搜 → 卡片 → 渠道 → 集数 → 实际观看', async ({ page }) => {
  // 1. 中文搜索
  await page.goto(`/search?q=${encodeURIComponent('葬送的芙莉莲')}`)

  const card = page.getByRole('button', { name: /葬送的芙莉莲/ })
  await expect(card).toBeVisible()
  await card.click()

  // 2. 详情页：真实后端渠道出现（fixture provider）
  await expect(page).toHaveURL(/\/anime\/12345\?/)
  await expect(page.getByRole('heading', { name: /葬送的芙莉莲/ })).toBeVisible()

  const channelButton = page.getByRole('button', { name: /E2E Fixture/ })
  await expect(channelButton).toBeVisible()

  // 3. 渠道 → 集数
  await channelButton.click()
  const episodeOne = page.getByRole('button', { name: '第 1 集' })
  await expect(episodeOne).toBeVisible()

  // 4. 实际观看：流经真实 StreamProxy 的本地 webm
  const proxyResponse = page.waitForResponse(
    (r) => r.url().includes('/api/watch/proxy/stream?url=') && r.status() >= 200 && r.status() < 300
  )
  await episodeOne.click()

  const video = page.locator('video')
  await expect(video).toBeVisible()

  const src = await video.evaluate((v: HTMLVideoElement) => v.currentSrc || v.src || '')
  expect(src).toContain('/api/watch/proxy/stream?url=')
  expect(await proxyResponse).toBeTruthy()

  // 播放器真正取到数据（readyState >= 2 = HAVE_CURRENT_DATA）
  await expect
    .poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 20_000 })
    .toBeGreaterThanOrEqual(2)

  await expect(page.getByText(/播放失败/)).toHaveCount(0)

  // 关闭播放器，回到详情页
  await page.getByRole('button', { name: '关闭播放器' }).click()
  await expect(video).toHaveCount(0)
})
