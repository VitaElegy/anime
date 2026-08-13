# NicoTracker / anime

> 自托管的番剧资源追踪 · 聚合搜索 · 下载 · 媒体库 · 多人同看（Watch Party）一站式服务

[![CI](https://img.shields.io/github/actions/workflow/status/VitaElegy/anime/ci.yml?branch=master&label=CI&logo=github)](https://github.com/VitaElegy/anime/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Node](https://img.shields.io/badge/Node-20%2B-339933?logo=nodedotjs&logoColor=white)](https://nodejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)](https://react.dev/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

一个前后端分离的番剧资源管理平台：**多源聚合搜索 → qBittorrent 下载 → HLS ABR 转码播放 → SSE 多人同看**，并内置账号、好友、收藏、日历等社交与追番能力。

## ✨ 功能特性

- 🔍 **多源聚合搜索**：Nyaa / SubsPlease / Mikan / AnimeGarden 四源并行，中文关键词优先（`asyncio.gather` + 去重排序）；Bangumi / AniList / Bilibili 元数据检索
- ▶️ **在线观看渠道**：Anilibria / Gogoanime 聚合搜索（AGE / Libvio / Zzzfun 实测失效已禁用，恢复后可随时开启），详情页一键点播（渠道卡片 → 集数 → hls.js 直播）；SSRF 防护代理 + HLS 广告段过滤
- ⬇️ **种子下载**：通过 qBittorrent WebUI API 下发任务，支持批量、暂停/恢复、进度查询
- 🎞️ **高清播放管线**：HLS ABR 三档码率（1080p / 720p / 480p）、硬件编码自动检测（NVENC / QSV / AMF / VideoToolbox）、HEVC MKV 4K 适配、HTTP Range 流式播放
- 👥 **多人同看**：SSE 房间实时同步（播放 / 暂停 / seek / 倍速）、自定义控制条、聊天、好友、私信、房间邀请
- 👤 **账号体系**：注册 / 登录 / 登出、登录限流、生产环境配置守卫（拒绝 qBittorrent 出厂默认密码）
- 🗂️ **追番管理**：收藏、日历、观看历史、断点续播、爬取控制台
- 🛡️ **工程化**：SQLite schema 迁移器、缓存预热、请求限流、CI（pytest + vitest + ruff + eslint + build）

## 🏗️ 架构

```text
┌─────────────────────────────┐        ┌──────────────────────────────┐
│  React 19 + Vite + Tailwind │  /api  │  FastAPI (app/)              │
│  hls.js / SSE EventSource   │ ─────▶ │  ├─ routers/  18 组 REST 路由 │
│  frontend/src               │ ◀───── │  ├─ services/ 外部源与业务层  │
└─────────────────────────────┘        │  ├─ channels/ 在线观看渠道层  │
                                       │  └─ SQLite (data/nicotracker.db)
                                       └──────────┬─────────────────────
                                                  │
              ┌─────────────────────┬─────────────┴──────────┬──────────────────┐
              ▼                     ▼                        ▼                  ▼
       Bangumi / AniList      Nyaa / SubsPlease        qBittorrent        ffmpeg
       / Bilibili 元数据      Mikan / AnimeGarden       (WebUI API)       (HLS ABR)
                             种子搜索                  下载引擎          转码管线
```

## 📁 项目结构

```text
anime/
├── app/                  # FastAPI 后端
│   ├── main.py           # 应用入口（lifespan、路由注册）
│   ├── config.py         # pydantic-settings 配置（ANIME_* 环境变量）
│   ├── models.py         # Pydantic 模型
│   ├── db_migrations.py  # SQLite 前向迁移器
│   ├── routers/          # API 路由（search/download/auth/media/social/watch_rooms…）
│   └── services/         # 数据源、转码、限流、SSE 房间、社交等业务层
├── frontend/             # React 19 + Vite 8 + TS + Tailwind 4 前端
│   └── src/
│       ├── pages/        # 首页 / 搜索 / 下载 / 番剧库 / 日历 / 爬取 / 同看大厅 / 房间
│       ├── api/          # axios API 客户端
│       └── lib/          # SSE 房间事件流、格式化工具
├── scripts/              # 真实环境 smoke 测试脚本（需运行中的后端）
├── tests/                # pytest 后端单测（77 个用例）
├── docs/                 # 设计与协议文档（搜索 API / 同看协议 / 资源目录）
├── deploy/               # systemd / Nginx / Docker 部署示例
├── data/                 # 运行期数据（SQLite、封面、HLS 输出，已 gitignore）
├── pyproject.toml        # 后端打包 / ruff / pytest 配置
├── Makefile              # 统一命令入口
├── docker-compose.yml    # 一键容器化（backend + frontend + 可选 qBittorrent）
└── .env.example          # 环境变量模板
```

## 🚀 快速开始

### 本地开发

前置要求：Python 3.11+、Node.js 20+、ffmpeg、可选 qBittorrent（缺省时下载功能自动降级）。

```bash
# 1. 安装依赖（后端 venv + 前端 node_modules）
make install

# 2. 配置环境变量
cp .env.example .env
# 按需修改 ANIME_QB_PASSWORD 等

# 3. 同时启动后端 (:8000) 与前端 (:5173)
make dev
```

打开 <http://localhost:5173> 即可。后端健康检查：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/health
```

> 开发时前端 Vite 会把 `/api` 代理到 `:8000`，SSE 连接同样走代理。

### Docker 部署

```bash
# 后端 + 前端（qBittorrent 请自行配置或外接）
docker compose up -d --build

# 或带上内置 qBittorrent 的零配置模式
docker compose --profile with-bt up -d --build
```

- 前端：<http://localhost:3000>
- 后端：<http://localhost:8000>
- qBittorrent WebUI（with-bt 模式）：<http://localhost:8080>（默认 `admin/adminadmin`，**生产环境务必修改**）

### 生产部署（裸机）

见 [deploy/DEPLOY_SERVER.md](deploy/DEPLOY_SERVER.md)，包含 systemd 服务单元与 Nginx 反代 / SSE 配置：

- [deploy/systemd/anime-backend.service](deploy/systemd/anime-backend.service)
- [deploy/nginx/anime.conf](deploy/nginx/anime.conf)

## ⚙️ 环境变量

全部变量均有默认值（见 `app/config.py`），以 `ANIME_` 为前缀，通过 `.env` 或环境注入。复制 `.env.example` 后按需修改即可。

| 分组 | 变量 |
|---|---|
| 运行模式 | `ANIME_ENV`（`production` 会启用配置守卫） |
| qBittorrent | `ANIME_QB_HOST` `ANIME_QB_PORT` `ANIME_QB_USERNAME` `ANIME_QB_PASSWORD` |
| 数据源 | `ANIME_BANGUMI_API_BASE` `ANIME_NYAA_BASE_URL` `ANIME_SUBSPLEASE_RSS` `ANIME_MIKAN_BASE_URL` `ANIME_MIKAN_MIRROR_URL` `ANIME_ANIME_GARDEN_API_BASE` `ANIME_BILIBILI_API_BASE` |
| 存储路径 | `ANIME_DOWNLOAD_DIR` `ANIME_COVER_CACHE_DIR` `ANIME_STREAM_CACHE_DIR` `ANIME_HLS_OUTPUT_DIR` |
| 媒体工具 | `ANIME_FFMPEG_BIN` `ANIME_FFPROBE_BIN` |
| 代理 | `ANIME_HTTP_PROXY`（Nyaa / dmhy 等被墙源 + 在线渠道） |
| 限流 | `ANIME_NYAA_RATE_LIMIT` `ANIME_BANGUMI_RATE_LIMIT` `ANIME_MIKAN_RATE_LIMIT` `ANIME_ANIME_GARDEN_RATE_LIMIT` `ANIME_BILIBILI_RATE_LIMIT` |

> ⚠️ `ANIME_ENV=production` 时若仍使用 qBittorrent 出厂默认密码 `adminadmin`，后端会**拒绝启动**（`app/config.py` 的 `assert_runtime_safety`）。

## 🧪 测试与检查

```bash
make test          # 后端 pytest + 前端 vitest
make lint          # ruff（后端）+ eslint（前端）
make build         # 前端生产构建（tsc + vite build）
```

| 检查项 | 命令 | 当前状态 |
|---|---|---|
| 后端单测 | `pytest tests/ -q` | 108 passed |
| 后端 Lint | `ruff check app/ tests/` | ✅ |
| 前端单测 | `npm test -- --run`（frontend/） | 13 passed |
| 前端 Lint | `npm run lint`（frontend/） | ✅ |
| 前端构建 | `npm run build`（frontend/） | ✅ |

真实环境 smoke 脚本（需运行中的后端）见 [scripts/README.md](scripts/README.md)。

## 📚 文档

| 文档 | 说明 |
|---|---|
| [docs/SEARCH_API.md](docs/SEARCH_API.md) | 搜索 API 参考（`/api/search/anime`、`/api/search/torrents`） |
| [docs/WATCH_SYNC_PROTOCOL.md](docs/WATCH_SYNC_PROTOCOL.md) | 同看 SSE 同步协议 v1 与 v2 预留位 |
| [docs/RESOURCE_DIRECTORY.md](docs/RESOURCE_DIRECTORY.md) | 高清影视资源源站目录与集成 ROI 排序 |
| [docs/CHANNEL_ARCHITECTURE.md](docs/CHANNEL_ARCHITECTURE.md) | 在线观看渠道架构规范（角色边界 / 接口契约 / 测试要求） |
| [docs/RESOURCE_GUIDE.md](docs/RESOURCE_GUIDE.md) | 资源站使用指南 |
| [docs/OPEN_SOURCE_PLAN.md](docs/OPEN_SOURCE_PLAN.md) | 开源化整改规划与跟踪清单 |
| [SEARCH_REDESIGN_REPORT.md](SEARCH_REDESIGN_REPORT.md) | 搜索重构攻坚报告（根因 / 实施 / 验证） |
| [PLAYBACK_SYNC_TEST_REPORT.md](PLAYBACK_SYNC_TEST_REPORT.md) | 真实播放 + 双端 SSE 同步测试报告 |
| [MULTIVIEWER_SYNC_REPORT.md](MULTIVIEWER_SYNC_REPORT.md) | 同看多人同步攻坚报告 |
| [WATCHPARTY_INSPIRED_REFACTOR.md](WATCHPARTY_INSPIRED_REFACTOR.md) | WatchParty 架构重构说明 |
| [HIGH_RESOLUTION_PLAYBACK_REPORT.md](HIGH_RESOLUTION_PLAYBACK_REPORT.md) | 高清播放管线（HLS ABR / 硬件编码）报告 |

## 🗺️ Roadmap

见 [ROADMAP.md](ROADMAP.md) — 包含同步协议 v2、同看权限 / RTT 补偿、按需转码、直播同看、Comicat / DMHY 源移植等规划，以及 `feature/watch-party` 分支的决策记录。

## 🤝 贡献

欢迎提交 Issue 与 PR！请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)（开发环境、检查命令、提交规范）与 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。安全问题请通过 [SECURITY.md](SECURITY.md) 的渠道报告。

## 📄 License

[MIT](LICENSE) © VitaElegy
