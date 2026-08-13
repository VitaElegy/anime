/**
 * 真实 UI 旅程验证（人工/CI 手动跑，连真实后端 8010 + 真实 Vite 4174）：
 *   中文搜 → 卡片 → 渠道 → 集数 → 实际观看（video.readyState >= 2）
 *
 * 前置（在仓库根目录）：
 *   1. 后端：ANIME_HTTP_PROXY=http://127.0.0.1:7892 \
 *        .venv-test/bin/python -m uvicorn app.main:app --port 8010
 *   2. 前端：cd frontend && ANIME_VITE_API_TARGET=http://127.0.0.1:8010 \
 *        npm run dev -- --host 127.0.0.1 --port 4174 --strictPort
 *   3. 运行：node e2e/scripts/real-ui-journey.mjs
 *
 * 可配环境变量：ANIME_UI_BASE（默认 http://127.0.0.1:4174）、
 * ANIME_UI_CHANNELS（逗号分隔渠道 id，默认 jisuzy,bfzyapi,360zy）。
 */
import { chromium } from '@playwright/test'

const BASE = process.env.ANIME_UI_BASE || 'http://127.0.0.1:4174'
const CHANNELS = (process.env.ANIME_UI_CHANNELS || 'jisuzy,bfzyapi,360zy')
  .split(',').map((s) => s.trim()).filter(Boolean)

const CHANNEL_NAMES = {
  jisuzy: '极速资源',
  subozy: '速播资源',
  bfzyapi: '暴风资源',
  ffzy: '非凡资源',
  ikunzy: 'iKun资源',
  yhzy: '樱花资源',
  '360zy': '360资源',
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function runChannel(page, channelId) {
  const label = CHANNEL_NAMES[channelId] || channelId
  console.log(`\n===== [${channelId}] ${label} =====`)
  await page.goto(`${BASE}/anime/0?title=${encodeURIComponent('葬送的芙莉莲')}&rawTitle=${encodeURIComponent('葬送的芙莉莲')}`, {
    waitUntil: 'domcontentloaded',
  })

  // 渠道按钮出现（watchSearch 聚合真实 7 个中文源）
  // 详情页渠道按钮文本 = 渠道名 + 命中标题 + 「选集」拼在一个 button 里，
  // 且同一渠道可能有多条命中（如 bfzyapi 有「葬送的芙莉莲」和「葬送的芙莉莲 第二季」），
  // 因此用 hasText 组合精确定位「渠道名 + 目标标题」且排除第二季的按钮。
  const targetTitle = '葬送的芙莉莲'
  const channelBtn = page
    .locator('button', { hasText: label })
    .filter({ hasText: targetTitle })
    .filter({ hasNotText: '第二季' })
    .first()
  await channelBtn.waitFor({ state: 'visible', timeout: 30_000 })
  console.log('  ✓ 渠道按钮可见:', label)

  const proxied = []
  page.on('response', (resp) => {
    if (resp.url().includes('/api/watch/proxy/stream?url=')) proxied.push(resp.status())
  })

  await channelBtn.click()

  // 集数按钮（Maccms 集名可能是 “第1集” / “第 1 集”）
  const epBtn = page.getByRole('button', { name: /第\s*0*1\s*集/ }).first()
  await epBtn.waitFor({ state: 'visible', timeout: 30_000 })
  console.log('  ✓ 集数按钮可见: 第1集')

  await epBtn.click()

  const video = page.locator('video')
  await video.waitFor({ state: 'visible', timeout: 20_000 })
  const src = await video.evaluate((v) => v.currentSrc || v.src || '')
  console.log('  ✓ 播放器打开, src 含代理:', src.includes('/api/watch/proxy/stream?url='))

  // 真实播放：hls.js 经代理拉 master/key/分片 -> readyState >= 2
  let ready = 0
  let lastErr = ''
  page.on('console', (msg) => {
    if (msg.type() === 'error') lastErr = lastErr || msg.text().slice(0, 200)
  })
  try {
    await page.waitForFunction(
      () => {
        const v = document.querySelector('video')
        return v && v.readyState >= 2
      },
      { timeout: 90_000 },
    )
    ready = await video.evaluate((v) => v.readyState)
  } catch {
    ready = await video.evaluate((v) => v.readyState).catch(() => -1)
  }
  console.log(`  → video.readyState = ${ready} (>=2 即真实取到媒体数据)`)

  // 统计代理请求状态码
  const ok = proxied.filter((s) => s >= 200 && s < 400).length
  const bad = proxied.filter((s) => s >= 400).length
  console.log(`  → 代理请求 ${proxied.length} 次, 成功 ${ok}, 失败 ${bad}`, bad ? `(bad: ${proxied.filter((s) => s >= 400).slice(0, 5)})` : '')
  if (lastErr) console.log('  → 浏览器 console error:', lastErr)

  const failText = await page.getByText(/播放失败/).count()
  if (failText > 0) console.log('  ✗ 页面出现「播放失败」')

  // 关闭播放器，回到详情页
  await page.getByRole('button', { name: '关闭播放器' }).click().catch(() => {})
  await sleep(300)

  return ready >= 2 && bad === 0 && failText === 0
}

const browser = await chromium.launch({ headless: true })
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  userAgent:
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
})
const page = await ctx.newPage()

const results = {}
for (const ch of CHANNELS) {
  try {
    results[ch] = await runChannel(page, ch)
  } catch (e) {
    console.log(`  ✗ [${ch}] 异常:`, String(e).split('\n')[0])
    results[ch] = false
  }
}

await browser.close()

console.log('\n===== 结果汇总 =====')
let allPass = true
for (const [ch, ok] of Object.entries(results)) {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${ch}  ${CHANNEL_NAMES[ch] || ''}`)
  if (!ok) allPass = false
}
process.exit(allPass ? 0 : 1)
