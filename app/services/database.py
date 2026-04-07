"""SQLite database for favorites, watch tracking, and user preferences."""

import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager

from app.config import settings

logger = logging.getLogger(__name__)

DB_PATH = Path(settings.COVER_CACHE_DIR).parent / "nicotracker.db"


def get_db_path() -> Path:
    return DB_PATH


@contextmanager
def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
        """)
    logger.info("Database initialized at %s", DB_PATH)


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


# ─── Crawl History ───

def add_crawl_record(source: str, keyword: str, result_count: int, duration_ms: int, status: str = "success", error_message: str = ""):
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


def upsert_title_cover(title_hash: str, cleaned_title: str, bangumi_id: int, name_cn: str, name: str, cover_url: str, cover_local: str = ""):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO title_cover_map (title_hash, cleaned_title, bangumi_id, name_cn, name, cover_url, cover_local)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (title_hash, cleaned_title, bangumi_id, name_cn, name, cover_url, cover_local),
        )
