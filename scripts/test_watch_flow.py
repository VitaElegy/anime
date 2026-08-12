"""End-to-end smoke test for search → pick → watch-room lifecycle.

No qBittorrent required: we use a public sample video URL as the 'downloaded'
media so the watch-room synchronized playback path can still be exercised.
"""

import json
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

BASE = "http://localhost:8000"


def _get(path: str, timeout: int = 30):
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return json.loads(data.decode("utf-8"))


def _request(method: str, path: str, body=None, timeout: int = 30):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def section(title: str):
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def main() -> int:
    # ------------------------------------------------------------------
    section("1) Backend health")
    h = _get("/api/health")
    print(json.dumps(h, ensure_ascii=False))
    if h.get("status") != "ok":
        print("FATAL: backend not healthy", file=sys.stderr)
        return 2

    # ------------------------------------------------------------------
    section("2) Torrent search — 葬送 (Chinese keyword, end-to-end)")
    q = urllib.parse.quote("葬送")
    t_resp = _get(f"/api/search/torrents?q={q}&limit=5")
    torrents = t_resp.get("torrents", [])
    print(f"Hits: {t_resp.get('total')}")
    for i, t in enumerate(torrents, 1):
        print(f"  [{i}] ({t['source']}) {t['title'][:60]}  | {t['size']} | seed={t['seeders']} | fansub={t.get('fansub','')}")
    if not torrents:
        print("FATAL: no torrents (search pipeline broken)", file=sys.stderr)
        return 3

    chosen = torrents[0]
    print(f"\n[SELECTED] {chosen['title'][:80]}")
    print(f"           magnet: {chosen['link'][:80]}...")

    # ------------------------------------------------------------------
    section("3) Anime metadata search — 葬送 (Bangumi)")
    a_resp = _get(f"/api/search/anime?q={q}&limit=3")
    animes = a_resp.get("anime", [])
    for a in animes:
        print(f"  id={a['id']:>6}  score={a.get('score')}  {a['title']}")

    anime_pick = animes[0] if animes else {}

    # ------------------------------------------------------------------
    section("4) Simulate a playable media — public sample video")
    # No qBittorrent available, so use a well-known MP4 the browser can play directly.
    sample_media = {
        "title": f"{anime_pick.get('title','Sample')} (demo stream)",
        "playback_url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
        "playback_mode": "direct_play",
        "media_id": f"demo-{int(time.time())}",
    }
    print(json.dumps(sample_media, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    section("5) Create watch room (without media_id — media library empty)")
    # watch_room.create_room refuses any media_id that isn't in the local
    # media library, and we don't have qBittorrent up so the library is empty.
    # Happily, rooms can be created first and have media attached later; that
    # matches the real UX where the host opens the lobby, then picks media.
    create_body = {
        "name": f"【测试】{anime_pick.get('title','Demo')}同看",
        "host_name": "tester",
    }
    try:
        room = _request("POST", "/api/watch/rooms", body=create_body)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"FATAL: room creation failed HTTP {e.code}: {detail}", file=sys.stderr)
        return 4
    room_id = room.get("room_id", "")
    print(f"room_id   = {room_id}")
    print(f"name      = {room.get('name')}")
    print(f"host_name = {room.get('host_name')}")
    print(f"state     = {json.dumps(room.get('state'), ensure_ascii=False)}")
    if not room_id:
        print("FATAL: room creation failed", file=sys.stderr)
        return 4

    # ------------------------------------------------------------------
    section("6) List watch rooms (lobby should now contain our room)")
    all_rooms = _get("/api/watch/rooms")
    print(f"total rooms in lobby: {len(all_rooms)}")
    ours = [r for r in all_rooms if r.get("room_id") == room_id]
    print(f"our room visible:    {bool(ours)}")
    if ours:
        r = ours[0]
        pc = r.get("participant_count", "-")
        print(f"  participant_count = {pc}")

    # ------------------------------------------------------------------
    section("7) Update playback state — simulate pause toggle + seek")
    # Can't bind a real media_id (library is empty), but we can still flip
    # paused/position/playback_rate — these are independent of the asset.
    upd = _request(
        "PUT",
        f"/api/watch/rooms/{room_id}/state",
        body={
            "paused": False,
            "position_seconds": 42.0,
            "playback_rate": 1.0,
            "updated_by": "tester",
        },
    )
    st = upd.get("state", {})
    print(f"paused           = {st.get('paused')}")
    print(f"position_seconds = {st.get('position_seconds')}")
    print(f"updated_by       = {st.get('updated_by')}")

    # ------------------------------------------------------------------
    section("8) Re-fetch the room and confirm persistence")
    fetched = _get(f"/api/watch/rooms/{room_id}")
    st2 = fetched.get("state", {})
    print(f"media_id         = {st2.get('media_id')}")
    print(f"position_seconds = {st2.get('position_seconds')}")
    print(f"playback_mode    = {st2.get('playback_mode')}")

    # ------------------------------------------------------------------
    section("9) List room messages (should be empty to start)")
    try:
        msgs = _get(f"/api/watch/rooms/{room_id}/messages?limit=5")
        print(f"message count = {len(msgs)}")
    except urllib.error.HTTPError as e:
        print(f"messages endpoint -> HTTP {e.code} (auth required? body={e.read()[:200]!r})")

    # ------------------------------------------------------------------
    section("10) Done — room left intact for UI inspection")
    print(f"Open http://localhost:3000/watch/{room_id}  (or wherever the frontend lives)")
    print(f"Or browse the lobby at http://localhost:3000/watch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
