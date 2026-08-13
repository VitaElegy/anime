# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Maccms（AppleCMS）资源站家族直链 HLS 备份渠道（docs/RESOURCE_BACKUP_PLAN.md
  §2.8）：标准 JSON API `GET /api.php/provide/vod`，中文关键词直搜、详情集数
  直出、HLS master 直链；**镜像域名并发竞速**（单域 5s / 总 7.5s，首个成功
  返回），单镜像挂掉不拖垮渠道。落地 360资源（360zy）/ iKun资源（ikunzy）/
  樱花资源（yhzy），`priority=59`、`language=zh`，2026-08-13 实测搜索/详情/
  播放/分片全链路可播（maowushi / bfikuncdn / wgslsw+yhzybf CDN，TS `47 40`
  magic）。11 例 fixture 测试（backend 201 -> 212）。
- Miruro playable HLS backup channel (docs/RESOURCE_BACKUP_PLAN.md §2.5): AniList
  GraphQL search + Miruro `/api/secure/pipe` episodes/streams (pewe ->
  hls.anidb.app HLS, verified 2026-08-13), `priority=58`, curl_cffi Chrome TLS
  fingerprint as the documented exception to the shared HTTP client; 11 fixture
  tests (backend 163 -> 174).
- Online watch channels: Anilibria (open JSON API + direct HLS, Chinese keyword
  expansion) and Gogoanime (HTML scraping + megaplay HLS) providers with real
  playback, registered in the channel registry (docs/CHANNEL_ARCHITECTURE.md).
- Stream proxy HLS playlist rewriting: every URI is resolved against the
  playlist base and rewritten to a same-origin proxy URL (fixes relative
  variant/segment paths on Gogoanime mirrors). Megaplay obfuscated segments
  ("tiktokcdn" PNG-wrapped payloads) are kept and the proxy strips their
  252-byte junk prefix so hls.js receives clean MPEG-TS (previous "ad
  filtering" dropped them and playback produced an empty playlist).
- 8 new channel parsing / HLS sanitizer tests (backend 100 -> 108).
- Offline Chinese -> English/Romaji title map as keyword-expansion fallback,
  so Chinese-first search still reaches English-indexed channels when
  Bangumi/network lookup is unavailable.
- Multi-source search: Bangumi / AniList metadata + Nyaa / SubsPlease / Mikan /
  AnimeGarden torrent aggregation (Chinese-first query handling).
- Bilibili 番剧 metadata integration (search + season detail).
- Watch Party: synchronized playback over SSE (play / pause / seek / rate),
  custom control bar, activity toasts, watch rooms, chat, friends, direct
  messages and room invitations.
- Watch history and social features (lobby presence, friend requests, DMs).
- HLS ABR transcoding pipeline (1080p/720p/480p ladder) with hardware encoder
  auto-detection (NVENC / QSV / AMF / VideoToolbox) and HTTP Range streaming.
- Account system (register / login / logout) with login rate limiting and
  production config guards (qBittorrent default-password protection).
- Schema migration runner (`app/db_migrations.py`, forward-only SQLite).
- 9 backend test modules + 3 frontend test files, plus design/validation docs.
- Open-source project metadata: LICENSE, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT,
  CI workflow, dependabot, docker-compose, Makefile, ruff/pytest config.

### Changed

- Resource backup plan: AnimePahe ruled out as a programmatic stream source
  (2026-08-13 TLS/browser probe) — `.tv/.net` API is hijacked by an ad-wall
  (302 -> `ch=1` -> advertiser landing page, never returns JSON even in a real
  browser), `.com/.org/.ru/.si/.me` are Cloudflare-gated, dead, or domain-for-sale;
  `_reference/Animepahe-API` is now stale. Recorded in RESOURCE_BACKUP_PLAN §2/§7.

- WatchParty implementation reworked after studying howardchung/watchparty
  (custom controls, zero echo-suppression gates).
- Search API consolidated into `/api/search/anime` and `/api/search/torrents`.

### Fixed

- CI e2e job: install frontend dependencies before the Playwright webServer
  starts Vite (was missing -> `vite: not found` exit 127, last 3 pushes red).
- Chinese filename / query compatibility bugs in playback and search.
- SSE state convergence for multi-viewer rooms (suppression + debounce).
- `RuntimeError: read() called while another coroutine is already waiting`
  in the transcoding pipeline.
