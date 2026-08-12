"""Social-graph and chat persistence split out from the monolithic
``database.py`` as part of P1-#7.

Everything here uses the shared connection factory :func:`database.get_conn`
so the PRAGMA hardening (busy_timeout, WAL, synchronous=NORMAL, etc.)
applies uniformly. This module deliberately exposes only bare functions —
call sites throughout the codebase already use ``db.create_direct_message``
style access, so we re-export from :mod:`database` to preserve every
existing import path.
"""

from __future__ import annotations

import time

from app.services.database import get_conn

# ─── Presence ────────────────────────────────────────────────────────────────


def _decode_presence_row(row) -> dict:
    return {
        "user_id": int(row["user_id"]),
        "username": row["username"],
        "current_room_id": row["current_room_id"],
        "current_room_name": row["current_room_name"],
        "current_page": row["current_page"],
        "status_text": row["status_text"],
        "last_seen_at": int(row["last_seen_at"] or 0),
        "created_at": int(row["created_at"] or 0),
        "updated_at": int(row["updated_at"] or 0),
    }


def upsert_user_presence(
    user_id: int,
    username: str,
    *,
    current_room_id: str = "",
    current_room_name: str = "",
    current_page: str = "",
    status_text: str = "",
) -> dict:
    now = int(time.time())
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT created_at FROM user_presence WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        created_at = int(existing["created_at"]) if existing else now
        conn.execute(
            """INSERT OR REPLACE INTO user_presence (
                user_id, username, current_room_id, current_room_name, current_page,
                status_text, last_seen_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                username,
                current_room_id,
                current_room_name,
                current_page,
                status_text,
                now,
                created_at,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM user_presence WHERE user_id = ?", (user_id,)).fetchone()
    return _decode_presence_row(row) if row else {}


def list_active_user_presence(active_within_seconds: int = 90) -> list[dict]:
    cutoff = int(time.time()) - max(active_within_seconds, 0)
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM user_presence
               WHERE last_seen_at >= ?
               ORDER BY last_seen_at DESC, username ASC""",
            (cutoff,),
        ).fetchall()
        return [_decode_presence_row(row) for row in rows]


def get_active_user_presence(user_id: int, active_within_seconds: int = 90) -> dict | None:
    cutoff = int(time.time()) - max(active_within_seconds, 0)
    with get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM user_presence
               WHERE user_id = ? AND last_seen_at >= ?""",
            (user_id, cutoff),
        ).fetchone()
    return _decode_presence_row(row) if row else None


def get_active_user_presence_map(active_within_seconds: int = 90) -> dict[int, dict]:
    return {item["user_id"]: item for item in list_active_user_presence(active_within_seconds)}


def purge_stale_user_presence(older_than_seconds: int = 86400):
    cutoff = int(time.time()) - max(older_than_seconds, 0)
    with get_conn() as conn:
        conn.execute("DELETE FROM user_presence WHERE last_seen_at > 0 AND last_seen_at < ?", (cutoff,))


# ─── Friend requests & friendships ───────────────────────────────────────────


def _decode_friend_request_row(row) -> dict:
    return {
        "request_id": int(row["request_id"]),
        "requester_user_id": int(row["requester_user_id"]),
        "requester_username": row["requester_username"],
        "target_user_id": int(row["target_user_id"]),
        "target_username": row["target_username"],
        "status": row["status"],
        "created_at": int(row["created_at"] or 0),
        "updated_at": int(row["updated_at"] or 0),
    }


def get_friend_request(request_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM friend_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        return _decode_friend_request_row(row) if row else None


def get_friend_request_between(user_id: int, other_user_id: int, *, status: str = "pending") -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM friend_requests
               WHERE requester_user_id = ? AND target_user_id = ? AND status = ?
               ORDER BY updated_at DESC
               LIMIT 1""",
            (user_id, other_user_id, status),
        ).fetchone()
        return _decode_friend_request_row(row) if row else None


def create_friend_request(
    requester_user_id: int,
    requester_username: str,
    target_user_id: int,
    target_username: str,
) -> dict:
    now = int(time.time())
    with get_conn() as conn:
        existing = conn.execute(
            """SELECT request_id, created_at FROM friend_requests
               WHERE requester_user_id = ? AND target_user_id = ?""",
            (requester_user_id, target_user_id),
        ).fetchone()
        if existing:
            request_id = int(existing["request_id"])
            conn.execute(
                """UPDATE friend_requests
                   SET requester_username = ?, target_username = ?, status = 'pending', updated_at = ?
                   WHERE request_id = ?""",
                (requester_username, target_username, now, request_id),
            )
        else:
            conn.execute(
                """INSERT INTO friend_requests (
                    requester_user_id, requester_username, target_user_id, target_username, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
                (requester_user_id, requester_username, target_user_id, target_username, now, now),
            )
            request_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    return get_friend_request(request_id) or {}


def update_friend_request_status(request_id: int, status: str) -> dict | None:
    now = int(time.time())
    with get_conn() as conn:
        conn.execute(
            "UPDATE friend_requests SET status = ?, updated_at = ? WHERE request_id = ?",
            (status, now, request_id),
        )
    return get_friend_request(request_id)


def list_incoming_friend_requests(user_id: int, *, status: str = "pending") -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM friend_requests
               WHERE target_user_id = ? AND status = ?
               ORDER BY updated_at DESC, request_id DESC""",
            (user_id, status),
        ).fetchall()
        return [_decode_friend_request_row(row) for row in rows]


def list_outgoing_friend_requests(user_id: int, *, status: str = "pending") -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM friend_requests
               WHERE requester_user_id = ? AND status = ?
               ORDER BY updated_at DESC, request_id DESC""",
            (user_id, status),
        ).fetchall()
        return [_decode_friend_request_row(row) for row in rows]


def are_friends(user_id: int, friend_user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM friendships WHERE user_id = ? AND friend_user_id = ?",
            (user_id, friend_user_id),
        ).fetchone()
        return row is not None


def add_friendship_pair(user_id: int, friend_user_id: int) -> bool:
    if user_id == friend_user_id:
        return False
    now = int(time.time())
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO friendships (user_id, friend_user_id, created_at) VALUES (?, ?, ?)",
            (user_id, friend_user_id, now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO friendships (user_id, friend_user_id, created_at) VALUES (?, ?, ?)",
            (friend_user_id, user_id, now),
        )
    return True


def remove_friendship_pair(user_id: int, friend_user_id: int) -> bool:
    if user_id == friend_user_id:
        return False
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM friendships WHERE (user_id = ? AND friend_user_id = ?) OR (user_id = ? AND friend_user_id = ?)",
            (user_id, friend_user_id, friend_user_id, user_id),
        )
    return True


def cancel_pending_room_invitations_between_users(user_id: int, other_user_id: int) -> int:
    now = int(time.time())
    with get_conn() as conn:
        cur = conn.execute(
            """UPDATE room_invitations
               SET status = 'dismissed', updated_at = ?
               WHERE status = 'pending'
                 AND (
                   (sender_user_id = ? AND recipient_user_id = ?)
                   OR
                   (sender_user_id = ? AND recipient_user_id = ?)
                 )""",
            (now, user_id, other_user_id, other_user_id, user_id),
        )
        return int(cur.rowcount or 0)


def list_friends(user_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT friendships.friend_user_id, friendships.created_at,
                      users.username, users.last_login_at, users.created_at AS user_created_at, users.updated_at
               FROM friendships
               JOIN users ON users.id = friendships.friend_user_id
               WHERE friendships.user_id = ?
               ORDER BY friendships.created_at DESC, users.username ASC""",
            (user_id,),
        ).fetchall()
        return [
            {
                "user_id": int(row["friend_user_id"]),
                "username": row["username"],
                "created_at": int(row["created_at"] or 0),
                "last_login_at": int(row["last_login_at"] or 0),
                "user_created_at": int(row["user_created_at"] or 0),
                "updated_at": int(row["updated_at"] or 0),
            }
            for row in rows
        ]


# ─── Direct messages ─────────────────────────────────────────────────────────


def _decode_direct_message_row(row) -> dict:
    return {
        "message_id": int(row["message_id"]),
        "sender_user_id": int(row["sender_user_id"]),
        "sender_username": row["sender_username"],
        "recipient_user_id": int(row["recipient_user_id"]),
        "recipient_username": row["recipient_username"],
        "body": row["body"],
        "created_at": int(row["created_at"] or 0),
        "read_at": int(row["read_at"] or 0),
    }


def create_direct_message(
    sender_user_id: int,
    sender_username: str,
    recipient_user_id: int,
    recipient_username: str,
    body: str,
) -> dict:
    now = int(time.time())
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO direct_messages (
                sender_user_id, sender_username, recipient_user_id, recipient_username, body, created_at, read_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (sender_user_id, sender_username, recipient_user_id, recipient_username, body, now),
        )
        message_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        row = conn.execute("SELECT * FROM direct_messages WHERE message_id = ?", (message_id,)).fetchone()
    return _decode_direct_message_row(row) if row else {}


def list_direct_messages(user_id: int, friend_user_id: int, limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM direct_messages
               WHERE (sender_user_id = ? AND recipient_user_id = ?)
                  OR (sender_user_id = ? AND recipient_user_id = ?)
               ORDER BY created_at DESC, message_id DESC
               LIMIT ?""",
            (user_id, friend_user_id, friend_user_id, user_id, limit),
        ).fetchall()
        decoded = [_decode_direct_message_row(row) for row in rows]
    decoded.reverse()
    return decoded


def mark_direct_messages_read(recipient_user_id: int, sender_user_id: int) -> int:
    now = int(time.time())
    with get_conn() as conn:
        cur = conn.execute(
            """UPDATE direct_messages
               SET read_at = ?
               WHERE recipient_user_id = ? AND sender_user_id = ? AND read_at = 0""",
            (now, recipient_user_id, sender_user_id),
        )
        return int(cur.rowcount or 0)


def get_unread_direct_message_counts(user_id: int) -> dict[int, int]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT sender_user_id, COUNT(*) AS unread_count
               FROM direct_messages
               WHERE recipient_user_id = ? AND read_at = 0
               GROUP BY sender_user_id""",
            (user_id,),
        ).fetchall()
        return {int(row["sender_user_id"]): int(row["unread_count"] or 0) for row in rows}


def get_latest_direct_message_map(user_id: int, limit: int = 400) -> dict[int, dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM direct_messages
               WHERE sender_user_id = ? OR recipient_user_id = ?
               ORDER BY created_at DESC, message_id DESC
               LIMIT ?""",
            (user_id, user_id, limit),
        ).fetchall()
    latest: dict[int, dict] = {}
    for row in rows:
        message = _decode_direct_message_row(row)
        counterpart_id = (
            message["recipient_user_id"]
            if message["sender_user_id"] == user_id
            else message["sender_user_id"]
        )
        if counterpart_id in latest:
            continue
        latest[counterpart_id] = message
    return latest


# ─── Room invitations ────────────────────────────────────────────────────────


def _decode_room_invitation_row(row) -> dict:
    return {
        "invitation_id": int(row["invitation_id"]),
        "room_id": row["room_id"],
        "room_name": row["room_name"],
        "sender_user_id": int(row["sender_user_id"]),
        "sender_username": row["sender_username"],
        "recipient_user_id": int(row["recipient_user_id"]),
        "recipient_username": row["recipient_username"],
        "message": row["message"],
        "status": row["status"],
        "created_at": int(row["created_at"] or 0),
        "updated_at": int(row["updated_at"] or 0),
    }


def get_room_invitation(invitation_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM room_invitations WHERE invitation_id = ?",
            (invitation_id,),
        ).fetchone()
    return _decode_room_invitation_row(row) if row else None


def create_room_invitation(
    *,
    room_id: str,
    room_name: str,
    sender_user_id: int,
    sender_username: str,
    recipient_user_id: int,
    recipient_username: str,
    message: str = "",
) -> dict:
    now = int(time.time())
    with get_conn() as conn:
        existing = conn.execute(
            """SELECT invitation_id FROM room_invitations
               WHERE room_id = ? AND sender_user_id = ? AND recipient_user_id = ?""",
            (room_id, sender_user_id, recipient_user_id),
        ).fetchone()
        if existing:
            invitation_id = int(existing["invitation_id"])
            conn.execute(
                """UPDATE room_invitations
                   SET room_name = ?, sender_username = ?, recipient_username = ?, message = ?, status = 'pending', updated_at = ?
                   WHERE invitation_id = ?""",
                (room_name, sender_username, recipient_username, message, now, invitation_id),
            )
        else:
            conn.execute(
                """INSERT INTO room_invitations (
                    room_id, room_name, sender_user_id, sender_username,
                    recipient_user_id, recipient_username, message, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    room_id,
                    room_name,
                    sender_user_id,
                    sender_username,
                    recipient_user_id,
                    recipient_username,
                    message,
                    now,
                    now,
                ),
            )
            invitation_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    return get_room_invitation(invitation_id) or {}


def update_room_invitation_status(invitation_id: int, status: str) -> dict | None:
    now = int(time.time())
    with get_conn() as conn:
        conn.execute(
            "UPDATE room_invitations SET status = ?, updated_at = ? WHERE invitation_id = ?",
            (status, now, invitation_id),
        )
    return get_room_invitation(invitation_id)


def list_incoming_room_invitations(user_id: int, *, status: str = "pending") -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM room_invitations
               WHERE recipient_user_id = ? AND status = ?
               ORDER BY updated_at DESC, invitation_id DESC""",
            (user_id, status),
        ).fetchall()
    return [_decode_room_invitation_row(row) for row in rows]


def list_outgoing_room_invitations(user_id: int, *, status: str = "pending") -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM room_invitations
               WHERE sender_user_id = ? AND status = ?
               ORDER BY updated_at DESC, invitation_id DESC""",
            (user_id, status),
        ).fetchall()
    return [_decode_room_invitation_row(row) for row in rows]


# ─── Room messages ───────────────────────────────────────────────────────────


def _decode_room_message_row(row) -> dict:
    return {
        "message_id": int(row["message_id"]),
        "room_id": row["room_id"],
        "sender_user_id": int(row["sender_user_id"]),
        "sender_username": row["sender_username"],
        "body": row["body"],
        "created_at": int(row["created_at"] or 0),
    }


def create_room_message(
    *,
    room_id: str,
    sender_user_id: int,
    sender_username: str,
    body: str,
) -> dict:
    now = int(time.time())
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO room_messages (
                room_id, sender_user_id, sender_username, body, created_at
            ) VALUES (?, ?, ?, ?, ?)""",
            (room_id, sender_user_id, sender_username, body, now),
        )
        message_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        row = conn.execute("SELECT * FROM room_messages WHERE message_id = ?", (message_id,)).fetchone()
    return _decode_room_message_row(row) if row else {}


def list_room_messages(room_id: str, limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM room_messages
               WHERE room_id = ?
               ORDER BY created_at DESC, message_id DESC
               LIMIT ?""",
            (room_id, limit),
        ).fetchall()
    decoded = [_decode_room_message_row(row) for row in rows]
    decoded.reverse()
    return decoded
