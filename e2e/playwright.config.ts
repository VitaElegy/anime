import { defineConfig, devices } from '@playwright/test'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '..')

function backendPython(): string {
  const candidates = [
    path.join(repoRoot, '.venv-test', 'bin', 'python'),
    path.join(repoRoot, '.venv', 'bin', 'python'),
    'python3',
    'python',
  ]
  for (const c of candidates) {
    if (existsSync(c)) return c
  }
  return 'python3'
}

const FIXTURE_PORT = 8901
const BACKEND_PORT = 8000
const FRONTEND_PORT = 4173

/**
 * Hermetic E2E harness (docs/E2E_TESTING.md):
 * - backend runs in ANIME_E2E_FIXTURE=1 mode -> registry contains ONLY the
 *   deterministic FixtureChannel (no external network at all);
 * - fixture-server.mjs stands in for an anime CDN (serves a real webm with
 *   Range support);
 * - frontend runs Vite dev server (proxies /api to the backend).
 */
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], headless: true },
    },
  ],
  webServer: [
    {
      command: 'node fixture-server.mjs',
      cwd: __dirname,
      url: `http://127.0.0.1:${FIXTURE_PORT}/fixture.webm`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: `${backendPython()} -m uvicorn app.main:app --host 127.0.0.1 --port ${BACKEND_PORT} --log-level warning`,
      cwd: repoRoot,
      url: `http://127.0.0.1:${BACKEND_PORT}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ANIME_E2E_FIXTURE: '1',
        ANIME_E2E_STREAM_BASE: `http://127.0.0.1:${FIXTURE_PORT}`,
        ANIME_HTTP_PROXY: '',
      },
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${FRONTEND_PORT} --strictPort`,
      cwd: path.join(repoRoot, 'frontend'),
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
})
