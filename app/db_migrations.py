"""Tiny forward-only schema migration runner.

We deliberately do not pull in Alembic for a project of this size. Each
migration is a callable that takes a ``sqlite3.Connection`` and must be
idempotent on failure (i.e. safe to retry). The runner records applied
versions in the ``schema_migrations`` table so subsequent startups skip them.

Adding a migration:

1. Write a function in this module named ``_migration_NNNN_short_name``.
2. Append ``(NNNN, "short_name", _migration_NNNN_short_name)`` to
   :data:`_MIGRATIONS` in order.
3. That's it — :func:`apply_pending` runs at ``init_db`` time.

Never rewrite or renumber an existing migration; write a new one.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

logger = logging.getLogger(__name__)

MigrationFn = Callable[[sqlite3.Connection], None]


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """Helper: add ``column`` to ``table`` only if it isn't already there."""
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# ─── Migration bodies ────────────────────────────────────────────────────────


def _migration_0001_baseline(conn: sqlite3.Connection) -> None:
    """Add the columns that used to live in ad-hoc _ensure_column calls.

    Idempotent; can be re-applied safely on a freshly-initialised DB.
    """
    _ensure_column(conn, "media_assets", "probe_status", "TEXT NOT NULL DEFAULT 'pending'")
    _ensure_column(conn, "media_assets", "probe_error", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "media_assets", "hls_progress", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "watch_rooms", "owner_user_id", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "watch_rooms", "owner_username", "TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_watch_rooms_owner_user_id ON watch_rooms(owner_user_id)")


# ─── Registry ────────────────────────────────────────────────────────────────

_MIGRATIONS: list[tuple[int, str, MigrationFn]] = [
    (1, "baseline", _migration_0001_baseline),
]


def _ensure_registry_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(row["version"]) for row in rows}


def apply_pending(conn: sqlite3.Connection) -> list[int]:
    """Run every migration that has not yet been recorded. Returns the list
    of versions applied in this call."""
    _ensure_registry_table(conn)
    applied = _applied_versions(conn)
    ran: list[int] = []
    for version, name, migration in _MIGRATIONS:
        if version in applied:
            continue
        logger.info("Applying migration %04d_%s", version, name)
        migration(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (version, name),
        )
        ran.append(version)
    return ran
