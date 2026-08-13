/**
 * Local static fixture server for the hermetic E2E suite.
 *
 * Serves e2e/fixtures/fixture.webm (VP9+Opus, generated with ffmpeg) with full
 * HTTP Range support so the backend StreamProxy behaves like it does against a
 * real CDN (Range 206 / Content-Range / Accept-Ranges).
 *
 * Role (docs/E2E_TESTING.md §2): test double standing in for an anime CDN.
 * It does NOT talk to the internet and does NOT know anything about channels.
 */
import http from 'node:http'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FILE = path.join(__dirname, 'fixtures', 'fixture.webm')
const PORT = Number(process.env.E2E_FIXTURE_PORT || 8901)
const HOST = process.env.E2E_FIXTURE_HOST || '127.0.0.1'

const body = readFileSync(FILE)
const TYPE = 'video/webm'

const server = http.createServer((req, res) => {
  const url = new URL(req.url || '/', `http://${HOST}:${PORT}`)
  if (url.pathname !== '/fixture.webm') {
    res.writeHead(404, { 'Content-Type': 'text/plain' })
    res.end('not found')
    return
  }

  const range = req.headers.range
  if (range) {
    const match = /bytes=(\d*)-(\d*)/.exec(range)
    let start = match?.[1] ? Number(match[1]) : 0
    let end = match?.[2] ? Number(match[2]) : body.length - 1
    if (!Number.isFinite(start) || start < 0) start = 0
    if (!Number.isFinite(end) || end >= body.length) end = body.length - 1
    if (start > end) {
      res.writeHead(416, { 'Content-Range': `bytes */${body.length}` })
      res.end()
      return
    }
    res.writeHead(206, {
      'Content-Type': TYPE,
      'Content-Length': end - start + 1,
      'Content-Range': `bytes ${start}-${end}/${body.length}`,
      'Accept-Ranges': 'bytes',
    })
    res.end(body.subarray(start, end + 1))
    return
  }

  res.writeHead(200, {
    'Content-Type': TYPE,
    'Content-Length': body.length,
    'Accept-Ranges': 'bytes',
  })
  res.end(body)
})

server.listen(PORT, HOST, () => {
  console.log(`[e2e-fixture] serving ${FILE} (${body.length} bytes) on http://${HOST}:${PORT}/fixture.webm`)
})
