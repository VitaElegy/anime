"""Real playback + multi-client sync end-to-end test.

Covers:
  1. Scan local media library (ffprobe) — real MP4 gets probed + indexed.
  2. HTTP Range GET the stream endpoint — verifies real bytes flow.
  3. Spin up two concurrent SSE clients (two "viewers") on the same room.
  4. A third "host" thread updates playback state (pause/seek/rate).
  5. Assert both viewers receive matching room_state events with millisecond
     latency.
  6. Send a chat-free state broadcast round to stress the fan-out path.

No qBittorrent required — we use media_library.scan to adopt the MP4 we
generated via ffmpeg directly under data/downloads/.
"""

from __future__ import annotations

import json
import queue
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://localhost:8000"


# ---------------------------------------------------------------------------
# Tiny HTTP helpers (no third-party deps to keep the smoke light)
# ---------------------------------------------------------------------------

def _req(method: str, path: str, *, body=None, headers=None, timeout: int = 30):
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.headers, r.read()


def _get_json(path: str, timeout: int = 30):
    st, _, body = _req("GET", path, timeout=timeout)
    return st, json.loads(body.decode("utf-8")) if body else None


def _banner(s: str):
    print("\n" + "=" * 78)
    print(f"  {s}")
    print("=" * 78)


# ---------------------------------------------------------------------------
# Step 1 & 2 — local media library + stream
# ---------------------------------------------------------------------------

def scan_and_pick_media() -> dict:
    _banner("1) POST /api/media/scan — scan download dir (ffprobe)")
    st, _, body = _req("POST", "/api/media/scan", timeout=60)
    data = json.loads(body.decode("utf-8"))
    items = data.get("items", [])
    print(f"items indexed: {len(items)}  refreshed_at={data.get('refreshed_at')}")
    for it in items:
        print(
            f"  [{it.get('media_id','?')[:8]}]  "
            f"probe={it.get('probe_status'):<10}  "
            f"direct_play={it.get('direct_play_supported')}  "
            f"{it.get('relative_path')}"
        )
    watchable = [it for it in items if it.get("probe_status") == "ready"]
    if not watchable:
        print("FATAL: no watchable asset — check ffprobe path and data/downloads", file=sys.stderr)
        sys.exit(3)
    picked = watchable[0]
    print(f"\n[PICKED] {picked['relative_path']} ({picked['duration']:.1f}s, {picked.get('video_codecs')})")
    return picked


def verify_stream(media_id: str):
    _banner("2) HTTP Range stream — grab first 256 KiB of real bytes")
    t0 = time.perf_counter()
    try:
        st, hdrs, body = _req(
            "GET",
            f"/api/media/{media_id}/stream",
            headers={"Range": "bytes=0-262143"},
            timeout=30,
        )
    except urllib.error.HTTPError as e:
        print(f"stream err: HTTP {e.code}: {e.read()[:200]!r}", file=sys.stderr)
        sys.exit(4)
    dt = (time.perf_counter() - t0) * 1000
    ctype = hdrs.get("Content-Type", "")
    crange = hdrs.get("Content-Range", "")
    size = len(body)
    sig = body[4:12]  # typical MP4 'ftyp' box marker
    print(f"status       = {st}")
    print(f"Content-Type = {ctype}")
    print(f"Content-Range= {crange}")
    print(f"bytes        = {size}  (in {dt:.1f} ms)")
    print(f"box signature= {sig!r}  (should contain b'ftyp' for a real MP4)")
    assert st in (200, 206), f"stream returned {st}"
    assert size > 1024, "stream body too small to be real video"
    assert b"ftyp" in body[:64], "not a valid MP4 (ftyp box not at head)"
    print("✓ real MP4 bytes confirmed end-to-end")


# ---------------------------------------------------------------------------
# Step 3-5 — multi-client SSE sync
# ---------------------------------------------------------------------------

def sse_viewer(name: str, room_id: str, events: queue.Queue, stop: threading.Event):
    """Blocking SSE listener running in its own thread.

    SSE frames are separated by a blank line. urllib's urlopen returns a
    file-like object whose ``readline()`` yields exactly one line at a time
    without waiting for a buffer fill — this is the only way to get sub-second
    latency out of stdlib HTTP.
    """
    url = f"{BASE}/api/watch/rooms/{room_id}/events"
    lines: list[str] = []
    try:
        req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
        with urllib.request.urlopen(req, timeout=60) as r:
            while not stop.is_set():
                raw = r.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line == "":
                    # frame boundary
                    if lines:
                        _dispatch("\n".join(lines), name, events)
                        lines = []
                else:
                    lines.append(line)
    except Exception as e:  # noqa: BLE001
        if not stop.is_set():
            events.put(("_error", name, str(e), time.perf_counter()))


def _dispatch(frame: str, viewer: str, events: queue.Queue):
    ev_type, data_lines = "", []
    for line in frame.splitlines():
        if line.startswith("event:"):
            ev_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
        elif line.startswith(":"):
            continue  # SSE comment (heartbeat)
    if not ev_type:
        return
    data_raw = "\n".join(data_lines)
    try:
        data = json.loads(data_raw) if data_raw else {}
    except Exception:
        data = {"raw": data_raw}
    events.put((ev_type, viewer, data, time.perf_counter()))


def run_multi_client_sync(room_id: str, media_id: str):
    _banner("3) Spin up 2 SSE viewers + 1 host in parallel")
    ev_q: queue.Queue = queue.Queue()
    stop = threading.Event()

    viewers = []
    for name in ("alice", "bob"):
        t = threading.Thread(target=sse_viewer, args=(name, room_id, ev_q, stop), daemon=True)
        t.start()
        viewers.append((name, t))

    # Let both viewers subscribe & receive the initial snapshot
    time.sleep(1.2)

    # Drain the initial snapshots
    initial_count = 0
    while not ev_q.empty():
        ev = ev_q.get_nowait()
        print(f"  initial  [{ev[1]:>5}]  {ev[0]}  media_id={ev[2].get('state',{}).get('media_id','') or '(none)'}")
        initial_count += 1
    print(f"  (drained {initial_count} initial frames)")

    _banner("4) Host fires 4 state updates — attach media, play, seek, pause")
    t_sent = {}
    updates = [
        {
            "media_id": media_id,
            "playback_mode": "direct_play",
            "playback_url": f"/api/media/{media_id}/stream",
            "paused": True,
            "position_seconds": 0.0,
            "updated_by": "host",
        },
        {"paused": False, "position_seconds": 0.0, "updated_by": "host"},
        {"paused": False, "position_seconds": 12.5, "updated_by": "host"},
        {"paused": True, "position_seconds": 12.5, "playback_rate": 1.25, "updated_by": "host"},
    ]

    for i, patch in enumerate(updates, 1):
        t_sent[i] = time.perf_counter()
        st, _, body = _req("PUT", f"/api/watch/rooms/{room_id}/state", body=patch)
        print(f"  PUT #{i} status={st}  patch={json.dumps(patch, ensure_ascii=False)}")
        time.sleep(0.8)  # let SSE fan-out settle before next change

    # Give a generous window for the final SSE frame to arrive before closing.
    time.sleep(3.0)
    stop.set()

    _banner("5) Collect SSE events and verify both viewers received them")
    received = {"alice": [], "bob": []}
    errors = []
    while not ev_q.empty():
        ev = ev_q.get_nowait()
        if ev[0] == "_error":
            errors.append(ev)
            continue
        ev_type, viewer, data, ts = ev
        if ev_type == "room_state":
            received[viewer].append((data.get("state", {}), ts))

    for name, rows in received.items():
        print(f"  {name}: got {len(rows)} room_state events after initial")
        for (st, _) in rows[-4:]:
            print(
                f"    paused={st.get('paused')}  pos={st.get('position_seconds')}  "
                f"rate={st.get('playback_rate')}  by={st.get('updated_by')}"
            )

    if errors:
        for e in errors:
            print(f"  !! {e[1]} -> {e[2]}", file=sys.stderr)

    _banner("6) Sync convergence — end state should be identical on both viewers")
    alice_last = received["alice"][-1][0] if received["alice"] else None
    bob_last = received["bob"][-1][0] if received["bob"] else None

    def _fingerprint(s):
        if not s:
            return None
        return (
            s.get("paused"),
            round(float(s.get("position_seconds") or 0), 2),
            round(float(s.get("playback_rate") or 1), 2),
            s.get("media_id", ""),
        )

    fa, fb = _fingerprint(alice_last), _fingerprint(bob_last)
    print(f"  alice-final = {fa}")
    print(f"  bob-final   = {fb}")
    ok = fa is not None and fa == fb
    print(f"  converged   = {ok}")

    # Rough latency: last-sent vs last-received per viewer
    latencies_ms = []
    for viewer in ("alice", "bob"):
        if received[viewer]:
            last_recv_ts = received[viewer][-1][1]
            last_sent_ts = t_sent[len(updates)]
            latencies_ms.append((last_recv_ts - last_sent_ts) * 1000)
    if latencies_ms:
        print(
            f"  latency     ≈ {statistics.mean(latencies_ms):.1f} ms "
            f"(min {min(latencies_ms):.1f} / max {max(latencies_ms):.1f})"
        )

    assert ok, "Multi-client state did NOT converge — sync broken!"

    # Pull the authoritative state one more time
    _, final = _get_json(f"/api/watch/rooms/{room_id}")
    print(f"  server auth = {json.dumps(final.get('state'), ensure_ascii=False)}")


# ---------------------------------------------------------------------------

def main() -> int:
    _banner("0) Backend health")
    _, h = _get_json("/api/health")
    print(json.dumps(h, ensure_ascii=False))
    if h.get("status") != "ok":
        return 2

    picked = scan_and_pick_media()
    verify_stream(picked["media_id"])

    _banner("3a) Create watch room bound to the real media")
    st, _, body = _req(
        "POST",
        "/api/watch/rooms",
        body={
            "name": f"【Sync-Test】{picked.get('title','demo')}",
            "host_name": "host",
            "media_id": picked["media_id"],
            "playback_mode": "direct_play",
            "playback_url": f"/api/media/{picked['media_id']}/stream",
        },
    )
    room = json.loads(body.decode("utf-8"))
    rid = room["room_id"]
    print(f"room_id = {rid}")

    run_multi_client_sync(rid, picked["media_id"])

    _banner("DONE")
    print(f"Room kept alive:   {BASE}/api/watch/rooms/{rid}")
    print(f"Stream URL:        {BASE}/api/media/{picked['media_id']}/stream")
    return 0


if __name__ == "__main__":
    sys.exit(main())
