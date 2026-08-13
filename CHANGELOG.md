# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

- Chinese filename / query compatibility bugs in playback and search.
- SSE state convergence for multi-viewer rooms (suppression + debounce).
- `RuntimeError: read() called while another coroutine is already waiting`
  in the transcoding pipeline.
