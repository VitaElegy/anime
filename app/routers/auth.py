"""Local auth routes for account-based favorites."""

from fastapi import APIRouter, Depends, Header, HTTPException

from app.dependencies.auth import get_current_user
from app.models import AuthRequest, AuthResponse, ImportFavoritesResponse, UserPublic
from app.services import auth as auth_service
from app.services import database as db

router = APIRouter()


def _extract_token(authorization: str | None) -> str:
    value = (authorization or "").strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value


@router.post("/register", response_model=AuthResponse, summary="Register and sign in")
async def register(req: AuthRequest):
    try:
        return auth_service.register(req.username, req.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/login", response_model=AuthResponse, summary="Login with username and password")
async def login(req: AuthRequest):
    try:
        return auth_service.login(req.username, req.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/me", response_model=UserPublic, summary="Get current signed-in user")
async def me(user: dict = Depends(get_current_user)):
    return user


@router.post("/logout", summary="Logout current session")
async def logout(authorization: str | None = Header(default=None)):
    token = _extract_token(authorization)
    if token:
        auth_service.logout(token)
    return {"status": "ok"}


@router.post("/import-legacy-favorites", response_model=ImportFavoritesResponse, summary="Import old shared favorites into current account")
async def import_legacy_favorites(user: dict = Depends(get_current_user)):
    return db.import_legacy_favorites(int(user["id"]))
