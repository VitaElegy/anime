# End-to-End Testing (Playwright)

> 状态：✅ 已落地（2026-08-13），本地 7 passed / 1 skipped（live 需真实网络）。

Hermetic 端到端测试：**中文搜 → 卡片 → 渠道 → 集数 → 实际观看**，全链路在
CI 里可复现，不依赖任何外部网站。

## 1. 为什么需要它

单元测试（pytest / vitest）只证明「每一层单独是对的」，无法证明
「搜索框 → 卡片 → 详情页渠道 → 集数 → 播放器真的放出画面」这条用户主路径
是通的。E2E 用真实浏览器 + 真实后端 + 真实流代理跑完这条路径，同时通过
**fixture 模式**把外部依赖（渠道站、元数据站）替换为确定性替身，保证 CI 稳定。

## 2. Fixture 模式（Hermetic）

`ANIME_E2E_FIXTURE=1` 时后端进入 fixture 模式（仅测试环境使用，生产永不开启）：

| 影响面 | fixture 模式行为 |
|---|---|
| 渠道注册表 | 只注册 `FixtureChannel`（`app/services/channels/fixture.py`），8 个真实渠道全部不加载 |
| 缓存预热 | `cache_warmer` 整体跳过（`app/main.py` lifespan 不启动 warm task） |
| 流代理白名单 | 额外放行 `127.0.0.1` / `localhost`（`app/routers/watch.py` `_host_allowed`），SSRF 保护在生产不受影响 |
| 流上游 | 本地 `fixture-server.mjs`（:8901）提供带 Range 206 的真实 webm |

- `FixtureChannel` 是**测试替身**，不是真实资源站；职责边界同任何
  `ChannelProvider`（search / get_detail / get_streams），见
  `docs/CHANNEL_ARCHITECTURE.md`。
- 中文关键词「葬送的芙莉莲 / 芙莉莲 / 芙莉 / frieren」命中 →
  `fixture:frieren` → 3 集 → 本地 webm。

## 3. 测试分层

| 层 | 文件 | 覆盖 | 依赖 |
|---|---|---|---|
| 核心 UX 旅程 | `e2e/tests/core-journey.spec.ts` | 中文搜 → 卡片 → 渠道 → 集数 → 实际播放（`video.readyState >= 2`） | 元数据层 mock（Bangumi/AniList/Bilibili/auth），watch 层真实后端 + 真实代理 |
| 后端契约 | `e2e/tests/backend-fixture.spec.ts` | channels 只含 fixture、中文搜索、detail 3 集、streams 本地 webm、代理 Range 206 + WebM magic、非白名单 403 | 无外网 |
| 真实源 live（可选） | `e2e/tests/live-sources.spec.ts` | 真实 AnimeHeaven 源搜索→detail→streams→代理 Range 206；真实 **Anikoto** HLS 源搜索→detail→streams→代理 master/子清单/TS 分片（sync `47 40`） | 外网；`ANIME_E2E_LIVE=1` 才跑，默认 skip |

## 4. 本地运行

```bash
cd e2e
npm install            # 首次：仅 @playwright/test
npx playwright install chromium   # 首次：浏览器内核
npx playwright test              # hermetic 全套（7 passed / 1 skipped）
npx playwright test tests/core-journey.spec.ts   # 只跑核心旅程
npx playwright test --headed     # 有头模式观察
# 真实源 smoke（live）需要先手动起一个**非 fixture 模式**的后端（:8001）：
#   ANIME_HTTP_PROXY=http://127.0.0.1:7892 \
#     python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
# 然后指定 live 后端再跑（注意：playwright 会自动另起 fixture 后端 :8000，
# 两者互不影响）：
ANIME_E2E_LIVE=1 ANIME_E2E_LIVE_BACKEND=http://127.0.0.1:8001 \
  npx playwright test tests/live-sources.spec.ts   # 真实源 smoke（AnimeHeaven mp4 + Anikoto HLS 两条）
```

Playwright 会自动拉起 3 个 webServer：

1. `fixture-server.mjs`（:8901）— 本地视频 CDN；
2. 后端 `uvicorn`（:8000，`ANIME_E2E_FIXTURE=1`）；
3. 前端 Vite dev（:4173，故意避开默认 3000 端口）。

> 前端 Vite 默认端口是 3000，E2E 固定用 **4173** 且 `--strictPort`，避免与本地
> 开发服务器冲突。后端/前端若已有进程在跑，本地会复用（CI 则始终全新启动）。

## 5. 排错

- 测试失败产物在 `e2e/test-results/`（截图 / 视频 / trace / error-context）。
- 看 trace：`npx playwright show-trace test-results/<case>/trace.zip`。
- 若 `webServer` 起不来，先确认端口占用：`lsof -i :8000 -i :4173 -i :8901`。
- 后端日志走 `--log-level warning`，排错时可临时改为 `info` 或直接前台手动起后端复现。

## 6. CI

`.github/workflows/ci.yml` 的 `e2e` job：

- ubuntu + Python 3.12 + Node 20 + ffmpeg；
- `cd e2e && npm ci && npx playwright install --with-deps chromium`；
- `npx playwright test`（headless，单 worker）。

## 7. 职责边界（防回归）

- E2E **不**替代单元测试：聚合/缓存/超时/回退等逻辑仍由 pytest 覆盖；
- fixture 模式**不**改生产代码路径：`settings.E2E_FIXTURE` 默认 `False`，
  生产注册表/白名单/预热行为与以前完全一致；
- 新增渠道时无需改 E2E；fixture 只验证「链路」，渠道自身契约由
  `tests/test_*_channel.py` 覆盖。
