# Roadmap

This file records where the project is going and, importantly, decisions made
along the way so contributors don't re-litigate them.

## Current status

- Core (search / download / library / watch party / accounts) is functional.
- Backend tests: green. Frontend tests: green (kept green in CI).
- Deployment: bare-metal via systemd + Nginx; Docker Compose available for dev.

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

- [ ] Role-based permissions: only the host may send control commands
- [ ] RTT compensation for more accurate seeks over WAN
- [ ] Heartbeat & explicit SSE re-subscribe after disconnect

### Playback & transcoding (`docs/HIGH_RESOLUTION_PLAYBACK_REPORT.md` §6)

- [ ] On-demand transcoding (start playback after the first ~30s, `event` playlists)
- [ ] Browser HEVC/AV1 direct-play detection (skip transcoding when possible)
- [ ] Parallel 3-ladder GPU transcoding for a single source

### Data-source integrations (`docs/RESOURCE_DIRECTORY.md` §9)

- [ ] `/api/live-tv` endpoint from public IPTV playlists (watch parties for live TV)
- [ ] PreDB metadata for "newly released" signals
- [ ] Evaluate Comicat / DMHY / AnimeTosho ports from `feature/watch-party`

### Engineering

- [ ] Publish container images (backend + frontend) for `docker compose up` prod
- [ ] Add end-to-end tests (Playwright) covering search → download → watch
- [ ] Add GitHub Pages / demo deployment of the frontend
