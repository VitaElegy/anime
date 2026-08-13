# Roadmap

This file records where the project is going and, importantly, decisions made
along the way so contributors don't re-litigate them.

## Current status

- Core (search / download / library / watch party / accounts) is functional.
- Backend tests: green (128 passed). Frontend tests: green (13 passed, kept
  green in CI).
- Deployment: bare-metal via systemd + Nginx; Docker Compose available for dev.
- Search fast-fail (2026-08-13): Bangumi unreachable no longer stalls first
  searches (~60s → ≤3s with negative cache + circuit breaker); channel keyword
  expansion keeps instant offline title-map hits.
- Backup Resource Library v1 (2026-08-13): Kitsu provider (free metadata with
  zh_cn titles + official page link) registered as an external backup channel;
  role spec + candidate audit in docs/RESOURCE_BACKUP_PLAN.md.

## Decisions

### `feature/watch-party` remote branch (2026-08-13)

The remote branch `feature/watch-party` (12 commits) contains an earlier
WatchParty implementation with voice chat, an aria2 download engine and a
7-source torrent search. It was **superseded** by the current in-tree
implementation (SSE-based rooms + social layer) which was developed on top of
`master`. The branch is kept for reference; no merge is planned.

- Backlog: evaluate cherry-picking the **aria2 download engine** and **voice
  chat** capabilities from that branch into the current codebase.

## Planned work

### Synchronization protocol v2 (`docs/WATCH_SYNC_PROTOCOL.md` §8)

Reserved fields to enable:

- [ ] `captions_url` — current subtitle track
- [ ] `audio_track` — multi-audio-track selection
- [ ] `buffering` — viewer buffer-state aggregation ("please wait for me")
- [ ] `presence[]` — live member list & status in-room

### Watch-room UX hardening (`docs/MULTIVIEWER_SYNC_REPORT.md` §8)

- [x] Role-based permissions: only the host may send control commands
      (implemented 2026-08 — `WatchRoomPage.isOwner` gate + non-owner
      heartbeat `requireReady`; covered by frontend tests)
- [ ] RTT compensation for more accurate seeks over WAN
- [x] Heartbeat & explicit SSE re-subscribe after disconnect (implemented
      2026-08 — presence heartbeat + room re-entry confirmation)

### Playback & transcoding (`docs/HIGH_RESOLUTION_PLAYBACK_REPORT.md` §6)

- [ ] On-demand transcoding (start playback after the first ~30s, `event` playlists)
- [ ] Browser HEVC/AV1 direct-play detection (skip transcoding when possible)
- [ ] Parallel 3-ladder GPU transcoding for a single source

### Data-source integrations (`docs/RESOURCE_DIRECTORY.md` §9)

- [ ] `/api/live-tv` endpoint from public IPTV playlists (watch parties for live TV)
- [ ] PreDB metadata for "newly released" signals
- [ ] Evaluate Comicat / DMHY / AnimeTosho ports from `feature/watch-party`

### Backup resource library (`docs/RESOURCE_BACKUP_PLAN.md`)

- [x] Kitsu v1: search (zh_cn titles) + external official link (priority=60)
- [ ] Shikimori metadata-only backup (search/detail, English/Russian)
- [ ] AnimePahe playable source (cloudscraper CF bypass, ref Animepahe-API)
- [ ] ReAnime.to playable source (flixcloud HLS AES-256, ref ReAnime.to-API)
- [ ] AniAPI after its JS challenge is removed (was 200, now JS-challenged)

### Engineering

- [ ] Publish container images (backend + frontend) for `docker compose up` prod
- [ ] Add end-to-end tests (Playwright) covering search → download → watch
- [ ] Add GitHub Pages / demo deployment of the frontend
