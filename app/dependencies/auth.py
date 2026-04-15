"""Authentication dependencies for FastAPI routes."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.services import auth as auth_service


def _extract_token(authorization: str | None) -> str:
    value = (authorization or "").strip()
    if not value:
        return ""
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value


def get_optional_user(authorization: str | None = Header(default=None)) -> dict | None:
    token = _extract_token(authorization)
    if not token:
        return None
    return auth_service.get_user_from_token(token)


def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    user = get_optional_user(authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
        )
    return user
