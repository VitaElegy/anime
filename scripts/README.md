# Scripts

Live-server / network smoke scripts. These are **not** part of the pytest
suite — they expect a running backend (and sometimes external services) and
are used to validate real end-to-end behavior during development.

| Script | Purpose | Requires |
|---|---|---|
| `test_search.py` | Smoke-test external metadata/torrent sources (Nyaa, SubsPlease, Bangumi, ...) | network access to the sources |
| `test_playback_sync.py` | Real playback + dual-SSE-viewer synchronization E2E | running backend on `:8000`, `ffmpeg`, a local sample video |
| `test_watch_flow.py` | Search → pick → watch-room lifecycle smoke test | running backend on `:8000` |

Example:

```bash
# start the backend first
uvicorn app.main:app --reload --port 8000

# then run a smoke script
python scripts/test_search.py
python scripts/test_playback_sync.py
python scripts/test_watch_flow.py
```
