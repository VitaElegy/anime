# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Online watch channels: Anilibria (open JSON API + direct HLS, Chinese keyword
  expansion) and Gogoanime (HTML scraping + megaplay HLS) providers with real
  playback, registered in the channel registry (docs/CHANNEL_ARCHITECTURE.md).
- Stream proxy HLS ad-segment filtering: mirror playlists (megap.mikora.top etc.)
  are sanitized on the fly so tiktokcdn image segments never reach hls.js.
- 8 new channel parsing / HLS sanitizer tests (backend 100 -> 108).
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

- WatchParty implementation reworked after studying howardchung/watchparty
  (custom controls, zero echo-suppression gates).
- Search API consolidated into `/api/search/anime` and `/api/search/torrents`.

### Fixed

- Chinese filename / query compatibility bugs in playback and search.
- SSE state convergence for multi-viewer rooms (suppression + debounce).
- `RuntimeError: read() called while another coroutine is already waiting`
  in the transcoding pipeline.
