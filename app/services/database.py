"""SQLite database for favorites, watch tracking, and user preferences."""

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

DB_PATH = Path(settings.COVER_CACHE_DIR).parent / "nicotracker.db"


def get_db_path() -> Path:
    return DB_PATH


@contextmanager
def get_conn():
    # ``check_same_thread=False`` is safe here because every ``get_conn`` call
    # creates its own connection and never hands it out across threads. It just
    # silences sqlite3's overly strict cross-thread guard for code that runs
    # inside ``asyncio.to_thread`` (where the same connection object would be
    # fine but the worker thread differs across awaits).
    conn = sqlite3.connect(str(DB_PATH), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # 5-second busy timeout lets concurrent writers queue instead of failing
    # with "database is locked" the moment two requests land at the same time.
    conn.execute("PRAGMA busy_timeout=5000")
    # WAL mode is persistent once set, but re-asserting it is cheap and keeps
    # the invariant visible at the call site.
    conn.execute("PRAGMA journal_mode=WAL")
    # ``NORMAL`` is the recommended pairing with WAL — honours fsync on
    # checkpoints but skips it on every commit. Good enough for our data.
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        if conn.in_transaction:
            conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    """Create tables if they don't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bangumi_id INTEGER UNIQUE NOT NULL,
                name_cn TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                cover_url TEXT NOT NULL DEFAULT '',
                score REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'watching',
                episode_progress INTEGER NOT NULL DEFAULT 0,
                total_episodes INTEGER NOT NULL DEFAULT 0,
                tags TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS crawl_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                keyword TEXT NOT NULL DEFAULT '',
                result_count INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'success',
                error_message TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_favorites_status ON favorites(status);
            CREATE INDEX IF NOT EXISTS idx_favorites_bangumi_id ON favorites(bangumi_id);
            CREATE INDEX IF NOT EXISTS idx_crawl_history_source ON crawl_history(source);

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL DEFAULT '',
                password_salt TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                last_login_at INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

            CREATE TABLE IF NOT EXISTS user_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL DEFAULT 0,
                expires_at INTEGER NOT NULL DEFAULT 0,
                last_used_at INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at);

            CREATE TABLE IF NOT EXISTS user_favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                bangumi_id INTEGER NOT NULL,
                name_cn TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                cover_url TEXT NOT NULL DEFAULT '',
                score REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'watching',
                episode_progress INTEGER NOT NULL DEFAULT 0,
                total_episodes INTEGER NOT NULL DEFAULT 0,
                tags TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, bangumi_id),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_user_favorites_user_id ON user_favorites(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_favorites_status ON user_favorites(user_id, status);

            CREATE TABLE IF NOT EXISTS title_cover_map (
                title_hash TEXT PRIMARY KEY,
                cleaned_title TEXT NOT NULL,
                bangumi_id INTEGER NOT NULL DEFAULT 0,
                name_cn TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                cover_url TEXT NOT NULL DEFAULT '',
                cover_local TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_tcm_bangumi ON title_cover_map(bangumi_id);

            CREATE TABLE IF NOT EXISTS response_cache (
                cache_key TEXT PRIMARY KEY,
                cache_group TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL DEFAULT '',
                updated_at INTEGER NOT NULL DEFAULT 0,
                expires_at INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_response_cache_group ON response_cache(cache_group);
            CREATE INDEX IF NOT EXISTS idx_response_cache_expires ON response_cache(expires_at);

            CREATE TABLE IF NOT EXISTS media_assets (
                media_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                relative_path TEXT NOT NULL UNIQUE,
                source_path TEXT NOT NULL DEFAULT '',
                size INTEGER NOT NULL DEFAULT 0,
                modified_at INTEGER NOT NULL DEFAULT 0,
                container TEXT NOT NULL DEFAULT '',
                duration REAL NOT NULL DEFAULT 0,
                video_codecs TEXT NOT NULL DEFAULT '[]',
                audio_codecs TEXT NOT NULL DEFAULT '[]',
                subtitle_codecs TEXT NOT NULL DEFAULT '[]',
                subtitles TEXT NOT NULL DEFAULT '[]',
                probe_status TEXT NOT NULL DEFAULT 'pending',
                probe_error TEXT NOT NULL DEFAULT '',
                direct_play_supported INTEGER NOT NULL DEFAULT 0,
                recommended_mode TEXT NOT NULL DEFAULT 'pretranscode_hls',
                hls_status TEXT NOT NULL DEFAULT 'missing',
                hls_playlist TEXT NOT NULL DEFAULT '',
                hls_updated_at INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_media_assets_mode ON media_assets(recommended_mode);
            CREATE INDEX IF NOT EXISTS idx_media_assets_hls_status ON media_assets(hls_status);

            CREATE TABLE IF NOT EXISTS watch_rooms (
                room_id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                host_name TEXT NOT NULL DEFAULT '',
                owner_user_id INTEGER NOT NULL DEFAULT 0,
                owner_username TEXT NOT NULL DEFAULT '',
                state_json TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_watch_rooms_updated_at ON watch_rooms(updated_at);

            CREATE TABLE IF NOT EXISTS user_watch_history (
                entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                room_id TEXT NOT NULL DEFAULT '',
                room_name TEXT NOT NULL DEFAULT '',
                media_id TEXT NOT NULL DEFAULT '',
                media_title TEXT NOT NULL DEFAULT '',
                playback_mode TEXT NOT NULL DEFAULT 'direct_play',
                position_seconds REAL NOT NULL DEFAULT 0,
                duration_seconds REAL NOT NULL DEFAULT 0,
                paused INTEGER NOT NULL DEFAULT 1,
                updated_by TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, room_id, media_id),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_user_watch_history_user_updated_at ON user_watch_history(user_id, updated_at);

            CREATE TABLE IF NOT EXISTS user_presence (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL DEFAULT '',
                current_room_id TEXT NOT NULL DEFAULT '',
                current_room_name TEXT NOT NULL DEFAULT '',
                current_page TEXT NOT NULL DEFAULT '',
                status_text TEXT NOT NULL DEFAULT '',
                last_seen_at INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_user_presence_last_seen_at ON user_presence(last_seen_at);

            CREATE TABLE IF NOT EXISTS friend_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                requester_user_id INTEGER NOT NULL,
                requester_username TEXT NOT NULL DEFAULT '',
                target_user_id INTEGER NOT NULL,
                target_username TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                UNIQUE(requester_user_id, target_user_id),
                FOREIGN KEY(requester_user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(target_user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_friend_requests_target_status ON friend_requests(target_user_id, status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_friend_requests_requester_status ON friend_requests(requester_user_id, status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS friendships (
                user_id INTEGER NOT NULL,
                friend_user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(user_id, friend_user_id),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(friend_user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_friendships_user_id ON friendships(user_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS direct_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_user_id INTEGER NOT NULL,
                sender_username TEXT NOT NULL DEFAULT '',
                recipient_user_id INTEGER NOT NULL,
                recipient_username TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL DEFAULT 0,
                read_at INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(sender_user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(recipient_user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_direct_messages_pair_created_at ON direct_messages(sender_user_id, recipient_user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_direct_messages_recipient_unread ON direct_messages(recipient_user_id, sender_user_id, read_at, created_at DESC);

            CREATE TABLE IF NOT EXISTS room_invitations (
                invitation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id TEXT NOT NULL,
                room_name TEXT NOT NULL DEFAULT '',
                sender_user_id INTEGER NOT NULL,
                sender_username TEXT NOT NULL DEFAULT '',
                recipient_user_id INTEGER NOT NULL,
                recipient_username TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                UNIQUE(room_id, sender_user_id, recipient_user_id),
                FOREIGN KEY(room_id) REFERENCES watch_rooms(room_id) ON DELETE CASCADE,
                FOREIGN KEY(sender_user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(recipient_user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_room_invitations_recipient_status ON room_invitations(recipient_user_id, status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_room_invitations_sender_status ON room_invitations(sender_user_id, status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS room_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id TEXT NOT NULL,
                sender_user_id INTEGER NOT NULL,
                sender_username TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(room_id) REFERENCES watch_rooms(room_id) ON DELETE CASCADE,
                FOREIGN KEY(sender_user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_room_messages_room_created_at ON room_messages(room_id, created_at DESC, message_id DESC);
        """)
        _ensure_column(conn, "media_assets", "probe_status", "TEXT NOT NULL DEFAULT 'pending'")
        _ensure_column(conn, "media_assets", "probe_error", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "media_assets", "hls_progress", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "watch_rooms", "owner_user_id", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "watch_rooms", "owner_username", "TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_watch_rooms_owner_user_id ON watch_rooms(owner_user_id)")
        # Run version-tracked migrations for anything that came after baseline.
        from app import db_migrations

        db_migrations.apply_pending(conn)
        conn.execute("DELETE FROM user_sessions WHERE expires_at > 0 AND expires_at < ?", (int(time.time()),))
        conn.execute(
            "DELETE FROM response_cache WHERE expires_at > 0 AND expires_at < ?", (int(time.time()) - 86400,)
        )
        conn.execute(
            "DELETE FROM user_presence WHERE last_seen_at > 0 AND last_seen_at < ?",
            (int(time.time()) - 86400,),
        )
    logger.info("Database initialized at %s", DB_PATH)


def _decode_user(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "created_at": int(row["created_at"] or 0),
        "updated_at": int(row["updated_at"] or 0),
        "last_login_at": int(row["last_login_at"] or 0),
    }


def create_user(username: str, password_hash: str, password_salt: str) -> dict | None:
    now = int(time.time())
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO users (username, password_hash, password_salt, created_at, updated_at, last_login_at)
                   VALUES (?, ?, ?, ?, ?, 0)""",
                (username, password_hash, password_salt, now, now),
            )
    except sqlite3.IntegrityError:
        return None
    return get_user_by_username(username)


def get_user_by_username(username: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            return None
        user = _decode_user(row)
        user["password_hash"] = row["password_hash"]
        user["password_salt"] = row["password_salt"]
        return user


def get_user_by_id(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return None
        user = _decode_user(row)
        user["password_hash"] = row["password_hash"]
        user["password_salt"] = row["password_salt"]
        return user


def touch_user_login(user_id: int):
    now = int(time.time())
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
            (now, now, user_id),
        )


def create_user_session(token_hash: str, user_id: int, expires_at: int):
    now = int(time.time())
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO user_sessions (token_hash, user_id, created_at, expires_at, last_used_at)
               VALUES (?, ?, ?, ?, ?)""",
            (token_hash, user_id, now, expires_at, now),
        )


def get_user_by_session(token_hash: str) -> dict | None:
    now = int(time.time())
    with get_conn() as conn:
        row = conn.execute(
            """SELECT users.*, user_sessions.expires_at
               FROM user_sessions
               JOIN users ON users.id = user_sessions.user_id
               WHERE user_sessions.token_hash = ?""",
            (token_hash,),
        ).fetchone()
        if not row:
            return None
        if int(row["expires_at"] or 0) and int(row["expires_at"]) < now:
            conn.execute("DELETE FROM user_sessions WHERE token_hash = ?", (token_hash,))
            return None
        conn.execute("UPDATE user_sessions SET last_used_at = ? WHERE token_hash = ?", (now, token_hash))
        return _decode_user(row)


def delete_user_session(token_hash: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM user_sessions WHERE token_hash = ?", (token_hash,))
        return cur.rowcount > 0


# ─── Favorites CRUD ───


def add_favorite(bangumi_id: int, name_cn: str, name: str, cover_url: str, score: float = 0) -> dict:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO favorites (bangumi_id, name_cn, name, cover_url, score, updated_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (bangumi_id, name_cn, name, cover_url, score),
        )
        row = conn.execute("SELECT * FROM favorites WHERE bangumi_id = ?", (bangumi_id,)).fetchone()
        return dict(row)


def remove_favorite(bangumi_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM favorites WHERE bangumi_id = ?", (bangumi_id,))
        return cur.rowcount > 0


def get_favorites(status: str = "") -> list[dict]:
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM favorites WHERE status = ? ORDER BY updated_at DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM favorites ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]


def get_favorite(bangumi_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM favorites WHERE bangumi_id = ?", (bangumi_id,)).fetchone()
        return dict(row) if row else None


def update_favorite(bangumi_id: int, **kwargs) -> dict | None:
    allowed = {"status", "episode_progress", "total_episodes", "tags", "notes"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return get_favorite(bangumi_id)
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [bangumi_id]
    with get_conn() as conn:
        conn.execute(
            f"UPDATE favorites SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE bangumi_id = ?",
            vals,
        )
        row = conn.execute("SELECT * FROM favorites WHERE bangumi_id = ?", (bangumi_id,)).fetchone()
        return dict(row) if row else None


def _decode_favorite_row(row) -> dict:
    return dict(row)


def add_user_favorite(
    user_id: int, bangumi_id: int, name_cn: str, name: str, cover_url: str, score: float = 0
) -> dict:
    now = int(time.time())
    with get_conn() as conn:
        existing = conn.execute(
            """SELECT id, created_at, status, episode_progress, total_episodes, tags, notes
               FROM user_favorites WHERE user_id = ? AND bangumi_id = ?""",
            (user_id, bangumi_id),
        ).fetchone()
        created_at = int(existing["created_at"]) if existing else now
        conn.execute(
            """INSERT OR REPLACE INTO user_favorites (
                id, user_id, bangumi_id, name_cn, name, cover_url, score, status,
                episode_progress, total_episodes, tags, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(existing["id"]) if existing else None,
                user_id,
                bangumi_id,
                name_cn,
                name,
                cover_url,
                score,
                existing["status"] if existing else "watching",
                int(existing["episode_progress"]) if existing else 0,
                int(existing["total_episodes"]) if existing else 0,
                existing["tags"] if existing else "",
                existing["notes"] if existing else "",
                created_at,
                now,
            ),
        )
    return get_user_favorite(user_id, bangumi_id) or {}


def remove_user_favorite(user_id: int, bangumi_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM user_favorites WHERE user_id = ? AND bangumi_id = ?",
            (user_id, bangumi_id),
        )
        return cur.rowcount > 0


def get_user_favorites(user_id: int, status: str = "") -> list[dict]:
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                """SELECT * FROM user_favorites
                   WHERE user_id = ? AND status = ?
                   ORDER BY updated_at DESC""",
                (user_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM user_favorites WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [_decode_favorite_row(row) for row in rows]


def get_user_favorite(user_id: int, bangumi_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_favorites WHERE user_id = ? AND bangumi_id = ?",
            (user_id, bangumi_id),
        ).fetchone()
        return _decode_favorite_row(row) if row else None


def update_user_favorite(user_id: int, bangumi_id: int, **kwargs) -> dict | None:
    allowed = {"status", "episode_progress", "total_episodes", "tags", "notes"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return get_user_favorite(user_id, bangumi_id)
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [int(time.time()), user_id, bangumi_id]
    with get_conn() as conn:
        conn.execute(
            f"UPDATE user_favorites SET {sets}, updated_at = ? WHERE user_id = ? AND bangumi_id = ?",
            vals,
        )
        row = conn.execute(
            "SELECT * FROM user_favorites WHERE user_id = ? AND bangumi_id = ?",
            (user_id, bangumi_id),
        ).fetchone()
        return _decode_favorite_row(row) if row else None


def import_legacy_favorites(user_id: int) -> dict:
    now = int(time.time())
    with get_conn() as conn:
        legacy_rows = conn.execute("SELECT * FROM favorites ORDER BY updated_at DESC").fetchall()
        imported = 0
        skipped = 0
        for row in legacy_rows:
            exists = conn.execute(
                "SELECT 1 FROM user_favorites WHERE user_id = ? AND bangumi_id = ?",
                (user_id, row["bangumi_id"]),
            ).fetchone()
            if exists:
                skipped += 1
                continue
            conn.execute(
                """INSERT INTO user_favorites (
                    user_id, bangumi_id, name_cn, name, cover_url, score, status,
                    episode_progress, total_episodes, tags, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    row["bangumi_id"],
                    row["name_cn"],
                    row["name"],
                    row["cover_url"],
                    row["score"],
                    row["status"],
                    row["episode_progress"],
                    row["total_episodes"],
                    row["tags"],
                    row["notes"],
                    now,
                    now,
                ),
            )
            imported += 1
    return {"imported": imported, "skipped": skipped, "total": imported + skipped}


def get_all_favorites(status: str = "") -> list[dict]:
    items = get_favorites(status)
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM user_favorites WHERE status = ? ORDER BY updated_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM user_favorites ORDER BY updated_at DESC").fetchall()
    return [_decode_favorite_row(row) for row in rows] + items


# ─── Crawl History ───


def add_crawl_record(
    source: str,
    keyword: str,
    result_count: int,
    duration_ms: int,
    status: str = "success",
    error_message: str = "",
):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO crawl_history (source, keyword, result_count, duration_ms, status, error_message)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (source, keyword, result_count, duration_ms, status, error_message),
        )


def get_crawl_history(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM crawl_history ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ─── Title → Cover persistent mapping ───


def get_title_cover(title_hash: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM title_cover_map WHERE title_hash = ?", (title_hash,)).fetchone()
        return dict(row) if row else None


def get_title_covers_batch(title_hashes: list[str]) -> dict[str, dict]:
    """Batch lookup. Returns {hash: row_dict}."""
    if not title_hashes:
        return {}
    placeholders = ",".join("?" for _ in title_hashes)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM title_cover_map WHERE title_hash IN ({placeholders})", title_hashes
        ).fetchall()
        return {row["title_hash"]: dict(row) for row in rows}


def upsert_title_cover(
    title_hash: str,
    cleaned_title: str,
    bangumi_id: int,
    name_cn: str,
    name: str,
    cover_url: str,
    cover_local: str = "",
):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO title_cover_map (title_hash, cleaned_title, bangumi_id, name_cn, name, cover_url, cover_local)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (title_hash, cleaned_title, bangumi_id, name_cn, name, cover_url, cover_local),
        )


# ─── Persistent Response Cache ───


def get_response_cache(cache_key: str, *, _retry: bool = False) -> dict | None:
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT cache_key, cache_group, payload, updated_at, expires_at FROM response_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if not row:
                return None
            try:
                payload = json.loads(row["payload"])
            except json.JSONDecodeError:
                conn.execute("DELETE FROM response_cache WHERE cache_key = ?", (cache_key,))
                return None
            return {
                "cache_key": row["cache_key"],
                "cache_group": row["cache_group"],
                "payload": payload,
                "updated_at": row["updated_at"],
                "expires_at": row["expires_at"],
            }
    except sqlite3.OperationalError as exc:
        if _retry or "response_cache" not in str(exc).lower():
            raise
        init_db()
        return get_response_cache(cache_key, _retry=True)


def set_response_cache(
    cache_key: str, cache_group: str, payload, ttl_seconds: int, *, _retry: bool = False
) -> dict:
    now = int(time.time())
    expires_at = now + max(ttl_seconds, 0)
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO response_cache (cache_key, cache_group, payload, updated_at, expires_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (cache_key, cache_group, payload_json, now, expires_at),
            )
    except sqlite3.OperationalError as exc:
        if _retry or "response_cache" not in str(exc).lower():
            raise
        init_db()
        return set_response_cache(cache_key, cache_group, payload, ttl_seconds, _retry=True)
    return {
        "cache_key": cache_key,
        "cache_group": cache_group,
        "payload": payload,
        "updated_at": now,
        "expires_at": expires_at,
    }


def delete_response_cache(cache_key: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM response_cache WHERE cache_key = ?", (cache_key,))


def purge_expired_response_cache():
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM response_cache WHERE expires_at > 0 AND expires_at < ?", (int(time.time()),)
        )


# ─── Local Media Library ───


def upsert_media_asset(asset: dict) -> dict:
    now = int(time.time())
    payload = {
        "media_id": asset["media_id"],
        "title": asset.get("title", ""),
        "relative_path": asset.get("relative_path", ""),
        "source_path": asset.get("source_path", ""),
        "size": int(asset.get("size", 0) or 0),
        "modified_at": int(asset.get("modified_at", 0) or 0),
        "container": asset.get("container", ""),
        "duration": float(asset.get("duration", 0) or 0),
        "video_codecs": json.dumps(asset.get("video_codecs", []), ensure_ascii=False, separators=(",", ":")),
        "audio_codecs": json.dumps(asset.get("audio_codecs", []), ensure_ascii=False, separators=(",", ":")),
        "subtitle_codecs": json.dumps(
            asset.get("subtitle_codecs", []), ensure_ascii=False, separators=(",", ":")
        ),
        "subtitles": json.dumps(asset.get("subtitles", []), ensure_ascii=False, separators=(",", ":")),
        "probe_status": asset.get("probe_status", "pending"),
        "probe_error": asset.get("probe_error", ""),
        "direct_play_supported": 1 if asset.get("direct_play_supported") else 0,
        "recommended_mode": asset.get("recommended_mode", "pretranscode_hls"),
        "hls_status": asset.get("hls_status", "missing"),
        "hls_playlist": asset.get("hls_playlist", ""),
        "hls_updated_at": int(asset.get("hls_updated_at", 0) or 0),
        "last_error": asset.get("last_error", ""),
    }
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT created_at FROM media_assets WHERE media_id = ?",
            (payload["media_id"],),
        ).fetchone()
        created_at = int(existing["created_at"]) if existing else now
        conn.execute(
            """INSERT OR REPLACE INTO media_assets (
                media_id, title, relative_path, source_path, size, modified_at, container, duration,
                video_codecs, audio_codecs, subtitle_codecs, subtitles, probe_status, probe_error,
                direct_play_supported, recommended_mode, hls_status, hls_playlist, hls_updated_at,
                last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload["media_id"],
                payload["title"],
                payload["relative_path"],
                payload["source_path"],
                payload["size"],
                payload["modified_at"],
                payload["container"],
                payload["duration"],
                payload["video_codecs"],
                payload["audio_codecs"],
                payload["subtitle_codecs"],
                payload["subtitles"],
                payload["probe_status"],
                payload["probe_error"],
                payload["direct_play_supported"],
                payload["recommended_mode"],
                payload["hls_status"],
                payload["hls_playlist"],
                payload["hls_updated_at"],
                payload["last_error"],
                created_at,
                now,
            ),
        )
    return get_media_asset(payload["media_id"]) or {}


def _decode_media_asset(row) -> dict:
    row = dict(row)
    probe_status = row.get("probe_status", "pending")
    probe_error = row.get("probe_error", "")
    watch_enabled = probe_status != "failed"
    return {
        "media_id": row["media_id"],
        "title": row["title"],
        "relative_path": row["relative_path"],
        "source_path": row["source_path"],
        "size": row["size"],
        "modified_at": row["modified_at"],
        "container": row["container"],
        "duration": row["duration"],
        "video_codecs": json.loads(row["video_codecs"] or "[]"),
        "audio_codecs": json.loads(row["audio_codecs"] or "[]"),
        "subtitle_codecs": json.loads(row["subtitle_codecs"] or "[]"),
        "subtitles": json.loads(row["subtitles"] or "[]"),
        "probe_status": probe_status,
        "probe_error": probe_error,
        "direct_play_supported": bool(row["direct_play_supported"]),
        "recommended_mode": row["recommended_mode"],
        "watch_enabled": watch_enabled,
        "watch_block_reason": probe_error if not watch_enabled else "",
        "hls_status": row["hls_status"],
        "hls_playlist": row["hls_playlist"],
        "hls_updated_at": row["hls_updated_at"],
        "hls_progress": int(row.get("hls_progress") or 0),
        "last_error": row["last_error"],
    }


def get_media_asset(media_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM media_assets WHERE media_id = ?", (media_id,)).fetchone()
        return _decode_media_asset(row) if row else None


def get_media_asset_by_path(relative_path: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM media_assets WHERE relative_path = ?", (relative_path,)).fetchone()
        return _decode_media_asset(row) if row else None


def list_media_assets() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM media_assets ORDER BY updated_at DESC, title ASC").fetchall()
        return [_decode_media_asset(row) for row in rows]


def delete_missing_media_assets(valid_relative_paths: list[str]):
    with get_conn() as conn:
        if not valid_relative_paths:
            conn.execute("DELETE FROM media_assets")
            return
        placeholders = ",".join("?" for _ in valid_relative_paths)
        conn.execute(
            f"DELETE FROM media_assets WHERE relative_path NOT IN ({placeholders})",
            valid_relative_paths,
        )


def update_media_hls_status(
    media_id: str,
    *,
    status: str,
    playlist: str | None = None,
    last_error: str | None = None,
    progress: int | None = None,
) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM media_assets WHERE media_id = ?", (media_id,)).fetchone()
        if not row:
            return None
        row = dict(row)
        current_playlist = row["hls_playlist"] if playlist is None else playlist
        current_error = row["last_error"] if last_error is None else last_error
        # Pick a reasonable progress value automatically based on the new
        # status so callers don't have to repeat themselves.
        if progress is None:
            if status == "ready":
                progress_value = 100
            elif status in {"missing", "queued", "error"}:
                progress_value = 0
            else:
                current = row.get("hls_progress", 0)
                progress_value = int(current or 0)
        else:
            progress_value = max(0, min(100, int(progress)))
        conn.execute(
            """UPDATE media_assets
               SET hls_status = ?, hls_playlist = ?, hls_updated_at = ?, last_error = ?, hls_progress = ?, updated_at = ?
               WHERE media_id = ?""",
            (
                status,
                current_playlist,
                int(time.time()),
                current_error,
                progress_value,
                int(time.time()),
                media_id,
            ),
        )
    return get_media_asset(media_id)


# ─── Watch Rooms ───


def upsert_watch_room(
    room_id: str,
    name: str,
    host_name: str,
    state: dict,
    *,
    owner_user_id: int | None = None,
    owner_username: str | None = None,
) -> dict:
    now = int(time.time())
    state_json = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT created_at, owner_user_id, owner_username FROM watch_rooms WHERE room_id = ?",
            (room_id,),
        ).fetchone()
        created_at = int(existing["created_at"]) if existing else now
        resolved_owner_user_id = (
            int(existing["owner_user_id"]) if existing and owner_user_id is None else int(owner_user_id or 0)
        )
        resolved_owner_username = (
            existing["owner_username"] if existing and owner_username is None else (owner_username or "")
        )
        conn.execute(
            """INSERT OR REPLACE INTO watch_rooms (
                room_id, name, host_name, owner_user_id, owner_username, state_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                room_id,
                name,
                host_name,
                resolved_owner_user_id,
                resolved_owner_username,
                state_json,
                created_at,
                now,
            ),
        )
    return get_watch_room(room_id) or {}


def _decode_watch_room(row) -> dict:
    row = dict(row)
    return {
        "room_id": row["room_id"],
        "name": row["name"],
        "host_name": row["host_name"],
        "owner_user_id": int(row.get("owner_user_id") or 0),
        "owner_username": row.get("owner_username", ""),
        "state": json.loads(row["state_json"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_watch_rooms(owner_user_id: int | None = None) -> list[dict]:
    with get_conn() as conn:
        if owner_user_id is None:
            rows = conn.execute("SELECT * FROM watch_rooms ORDER BY updated_at DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM watch_rooms WHERE owner_user_id = ? ORDER BY updated_at DESC",
                (owner_user_id,),
            ).fetchall()
        return [_decode_watch_room(row) for row in rows]


def get_watch_room(room_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM watch_rooms WHERE room_id = ?", (room_id,)).fetchone()
        return _decode_watch_room(row) if row else None


def delete_watch_room(room_id: str) -> bool:
    with get_conn() as conn:
        result = conn.execute("DELETE FROM watch_rooms WHERE room_id = ?", (room_id,))
        return result.rowcount > 0


def delete_watch_rooms(room_ids: list[str]) -> int:
    normalized_room_ids = [room_id for room_id in dict.fromkeys(room_ids) if room_id]
    if not normalized_room_ids:
        return 0
    placeholders = ",".join("?" for _ in normalized_room_ids)
    with get_conn() as conn:
        result = conn.execute(
            f"DELETE FROM watch_rooms WHERE room_id IN ({placeholders})", tuple(normalized_room_ids)
        )
        return int(result.rowcount or 0)


def _decode_watch_history_row(row) -> dict:
    return {
        "entry_id": int(row["entry_id"]),
        "user_id": int(row["user_id"]),
        "room_id": row["room_id"],
        "room_name": row["room_name"],
        "media_id": row["media_id"],
        "media_title": row["media_title"],
        "playback_mode": row["playback_mode"],
        "position_seconds": float(row["position_seconds"] or 0),
        "duration_seconds": float(row["duration_seconds"] or 0),
        "paused": bool(row["paused"]),
        "updated_by": row["updated_by"],
        "created_at": int(row["created_at"] or 0),
        "updated_at": int(row["updated_at"] or 0),
    }


def upsert_user_watch_history(
    user_id: int,
    *,
    room_id: str,
    room_name: str,
    media_id: str,
    media_title: str,
    playback_mode: str,
    position_seconds: float,
    duration_seconds: float,
    paused: bool,
    updated_by: str = "",
) -> dict:
    now = int(time.time())
    with get_conn() as conn:
        existing = conn.execute(
            """SELECT entry_id, created_at
               FROM user_watch_history
               WHERE user_id = ? AND room_id = ? AND media_id = ?""",
            (user_id, room_id, media_id),
        ).fetchone()
        created_at = int(existing["created_at"]) if existing else now
        conn.execute(
            """INSERT OR REPLACE INTO user_watch_history (
                entry_id, user_id, room_id, room_name, media_id, media_title, playback_mode,
                position_seconds, duration_seconds, paused, updated_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(existing["entry_id"]) if existing else None,
                user_id,
                room_id,
                room_name,
                media_id,
                media_title,
                playback_mode,
                float(position_seconds or 0),
                float(duration_seconds or 0),
                1 if paused else 0,
                updated_by,
                created_at,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM user_watch_history WHERE user_id = ? AND room_id = ? AND media_id = ?",
            (user_id, room_id, media_id),
        ).fetchone()
    return _decode_watch_history_row(row) if row else {}


def list_user_watch_history(user_id: int, limit: int = 12) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM user_watch_history
               WHERE user_id = ?
               ORDER BY updated_at DESC
               LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [_decode_watch_history_row(row) for row in rows]


def get_user_watch_history_entry(user_id: int, room_id: str, media_id: str = "") -> dict | None:
    with get_conn() as conn:
        if media_id:
            row = conn.execute(
                """SELECT * FROM user_watch_history
                   WHERE user_id = ? AND room_id = ? AND media_id = ?
                   ORDER BY updated_at DESC
                   LIMIT 1""",
                (user_id, room_id, media_id),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT * FROM user_watch_history
                   WHERE user_id = ? AND room_id = ?
                   ORDER BY updated_at DESC
                   LIMIT 1""",
                (user_id, room_id),
            ).fetchone()
        return _decode_watch_history_row(row) if row else None


# ─── Presence / Friends / Chat ───
#
# The implementations live in :mod:\pp.services.database_social\ as of
# P1-#7. We re-export them here so every existing
# \rom app.services import database as db; db.upsert_user_presence(...)# caller keeps working unchanged.
from app.services.database_social import (  # noqa: E402,F401  (re-export)
    _decode_direct_message_row,
    _decode_friend_request_row,
    _decode_presence_row,
    _decode_room_invitation_row,
    _decode_room_message_row,
    add_friendship_pair,
    are_friends,
    cancel_pending_room_invitations_between_users,
    create_direct_message,
    create_friend_request,
    create_room_invitation,
    create_room_message,
    get_active_user_presence,
    get_active_user_presence_map,
    get_friend_request,
    get_friend_request_between,
    get_latest_direct_message_map,
    get_room_invitation,
    get_unread_direct_message_counts,
    list_active_user_presence,
    list_direct_messages,
    list_friends,
    list_incoming_friend_requests,
    list_incoming_room_invitations,
    list_outgoing_friend_requests,
    list_outgoing_room_invitations,
    list_room_messages,
    mark_direct_messages_read,
    purge_stale_user_presence,
    remove_friendship_pair,
    update_friend_request_status,
    update_room_invitation_status,
    upsert_user_presence,
)
