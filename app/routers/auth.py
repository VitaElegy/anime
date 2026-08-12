"""Local auth routes for account-based favorites."""

import logging

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response

from app.dependencies.auth import get_current_user
from app.models import AuthRequest, AuthResponse, ImportFavoritesResponse, UserPublic
from app.services import auth as auth_service
from app.services import database as db
from app.services.rate_limit import LOGIN_FAILURE_LIMITER

router = APIRouter()
logger = logging.getLogger(__name__)

# Cookie name for the optional HttpOnly auth token. Clients can still use
# ``Authorization: Bearer`` headers — the cookie is a second, safer channel
# for the browser-hosted SPA.
AUTH_COOKIE_NAME = "anime_auth"
COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # mirrors SESSION_TTL_SECONDS


def _extract_token(authorization: str | None) -> str:
    value = (authorization or "").strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value


def _client_ip(request: Request) -> str:
    # Honour the forwarded header when behind nginx; fall back to the direct
    # peer address otherwise. We intentionally look at the *first* entry so
    # that a proxy chain like "real, trusted-proxy" keys on the real origin.
    forwarded = (request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        # ``secure`` is left to nginx: it strips the flag over plain HTTP in
        # development and preserves it when TLS terminates there. FastAPI
        # defaults to not setting it, which matches our test client.
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(AUTH_COOKIE_NAME)


@router.post("/register", response_model=AuthResponse, summary="Register and sign in")
async def register(req: AuthRequest, response: Response):
    try:
        result = auth_service.register(req.username, req.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_auth_cookie(response, result["token"])
    return result


@router.post("/login", response_model=AuthResponse, summary="Login with username and password")
async def login(req: AuthRequest, request: Request, response: Response):
    key = f"login:{_client_ip(request)}"
    try:
        result = auth_service.login(req.username, req.password)
    except ValueError as exc:
        # Only throttle on *failed* attempts — successful logins mustn't
        # count against the quota.
        allowed = await LOGIN_FAILURE_LIMITER.hit(key)
        if not allowed:
            retry_after = await LOGIN_FAILURE_LIMITER.seconds_until_retry(key)
            raise HTTPException(
                status_code=429,
                detail="尝试次数过多，请稍后再试",
                headers={"Retry-After": str(max(1, int(retry_after)))},
            ) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # A successful login resets the failure counter for this IP.
    LOGIN_FAILURE_LIMITER.reset(key)
    _set_auth_cookie(response, result["token"])
    return result


@router.get("/me", response_model=UserPublic, summary="Get current signed-in user")
async def me(user: dict = Depends(get_current_user)):
    return user


@router.post("/logout", summary="Logout current session")
async def logout(
    response: Response,
    authorization: str | None = Header(default=None),
    anime_auth: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
):
    token = _extract_token(authorization) or (anime_auth or "").strip()
    if token:
        auth_service.logout(token)
    _clear_auth_cookie(response)
    return {"status": "ok"}


@router.post(
    "/import-legacy-favorites",
    response_model=ImportFavoritesResponse,
    summary="Import old shared favorites into current account",
)
async def import_legacy_favorites(user: dict = Depends(get_current_user)):
    return db.import_legacy_favorites(int(user["id"]))
