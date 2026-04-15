"""Minimal local authentication for personal favorites."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time

from app.services import database as db

USERNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,23}$")
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
PBKDF2_ITERATIONS = 180_000


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_password(password: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        PBKDF2_ITERATIONS,
    ).hex()


def _validate_credentials(username: str, password: str):
    if not USERNAME_RE.match(username):
        raise ValueError("用户名需为 3-24 位，只能包含字母、数字、点、下划线或中划线")
    if len(password) < 8:
        raise ValueError("密码至少需要 8 位")


def _public_user(user: dict) -> dict:
    return {
        "id": int(user["id"]),
        "username": user["username"],
        "created_at": int(user.get("created_at", 0) or 0),
        "updated_at": int(user.get("updated_at", 0) or 0),
        "last_login_at": int(user.get("last_login_at", 0) or 0),
    }


def _issue_session(user: dict) -> dict:
    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    db.create_user_session(_token_hash(token), int(user["id"]), expires_at)
    db.touch_user_login(int(user["id"]))
    fresh_user = db.get_user_by_id(int(user["id"])) or user
    return {"user": _public_user(fresh_user), "token": token, "expires_at": expires_at}


def register(username: str, password: str) -> dict:
    username = normalize_username(username)
    _validate_credentials(username, password)
    salt_hex = secrets.token_hex(16)
    password_hash = _hash_password(password, salt_hex)
    user = db.create_user(username, password_hash, salt_hex)
    if not user:
        raise ValueError("用户名已存在")
    return _issue_session(user)


def login(username: str, password: str) -> dict:
    username = normalize_username(username)
    _validate_credentials(username, password)
    user = db.get_user_by_username(username)
    if not user:
        raise ValueError("用户名或密码错误")
    expected = user.get("password_hash", "")
    actual = _hash_password(password, user.get("password_salt", ""))
    if not expected or not hmac.compare_digest(expected, actual):
        raise ValueError("用户名或密码错误")
    return _issue_session(user)


def get_user_from_token(token: str) -> dict | None:
    if not token:
        return None
    user = db.get_user_by_session(_token_hash(token))
    if not user:
        return None
    return _public_user(user)


def logout(token: str) -> bool:
    if not token:
        return False
    return db.delete_user_session(_token_hash(token))
