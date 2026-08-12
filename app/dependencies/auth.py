"""Authentication dependencies for FastAPI routes."""

from __future__ import annotations

from fastapi import Cookie, Header, HTTPException, status

from app.services import auth as auth_service

# Must match :data:`app.routers.auth.AUTH_COOKIE_NAME`. Kept duplicated as a
# string literal to avoid an import cycle between the dependency module and
# the router.
_AUTH_COOKIE_NAME = "anime_auth"


def _extract_token(authorization: str | None) -> str:
    value = (authorization or "").strip()
    if not value:
        return ""
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return ""


def get_optional_user(
    authorization: str | None = Header(default=None),
    anime_auth: str | None = Cookie(default=None, alias=_AUTH_COOKIE_NAME),
) -> dict | None:
    token = _extract_token(authorization) or (anime_auth or "").strip()
    if not token:
        return None
    return auth_service.get_user_from_token(token)


def get_current_user(
    authorization: str | None = Header(default=None),
    anime_auth: str | None = Cookie(default=None, alias=_AUTH_COOKIE_NAME),
) -> dict:
    user = get_optional_user(authorization=authorization, anime_auth=anime_auth)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
        )
    return user
