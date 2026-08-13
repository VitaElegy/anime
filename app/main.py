import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import anilist as anilist_router
from app.routers import (
    auth,
    cover_resolve,
    crawl,
    download,
    favorites,
    image_proxy,
    media,
    metadata,
    schedule,
    search,
    social,
    watch,
    watch_history,
    watch_rooms,
)
from app.routers import calendar as calendar_router
from app.services import cache_warmer, watch_room
from app.services import database as db
from app.services.qbittorrent import qb_service

logger = logging.getLogger("anime-downloader")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
settings.STREAM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
settings.HLS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Fail fast when the operator tries to ship the factory default
    # qBittorrent password into production.
    settings.assert_runtime_safety()

    warm_task: asyncio.Task | None = None
    room_cleanup_task: asyncio.Task | None = None

    # Ensure cache dirs exist
    settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    settings.COVER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    settings.STREAM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    settings.HLS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Init SQLite
    db.init_db()

    # Connect to qBittorrent — non-blocking with timeout
    try:
        await asyncio.wait_for(asyncio.to_thread(qb_service.connect), timeout=5)
        logger.info("Connected to qBittorrent at %s", settings.qb_url)
    except Exception as e:
        logger.warning("qBittorrent not available: %s (download features disabled)", e)

    if not settings.E2E_FIXTURE:
        try:
            await asyncio.wait_for(cache_warmer.warm_core_caches(), timeout=25)
        except Exception as e:
            logger.warning("Initial cache warmup skipped: %s", e)
        warm_task = asyncio.create_task(cache_warmer.run_periodic_warmer())
    room_cleanup_task = asyncio.create_task(watch_room.run_periodic_room_cleanup())

    yield

    # Shutdown
    if warm_task is not None:
        warm_task.cancel()
        with suppress(asyncio.CancelledError):
            await warm_task
    if room_cleanup_task is not None:
        room_cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await room_cleanup_task
    logger.info("Shutting down")


app = FastAPI(
    title="Anime Download Manager",
    description="Search anime torrents from Nyaa / SubsPlease, download via qBittorrent, fetch metadata from Bangumi.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(search.router, prefix="/api/search", tags=["Search"])
app.include_router(download.router, prefix="/api/download", tags=["Download"])
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(metadata.router, prefix="/api/metadata", tags=["Metadata"])
app.include_router(favorites.router, prefix="/api/favorites", tags=["Favorites"])
app.include_router(crawl.router, prefix="/api/crawl", tags=["Crawl"])
app.include_router(schedule.router, prefix="/api/schedule", tags=["Schedule"])
app.include_router(calendar_router.router, prefix="/api/calendar", tags=["Calendar"])
app.include_router(image_proxy.router, prefix="/api/image", tags=["Image"])
app.include_router(cover_resolve.router, prefix="/api/covers", tags=["Covers"])
app.include_router(anilist_router.router, prefix="/api/anilist", tags=["AniList"])
app.include_router(media.router, prefix="/api/media", tags=["Media"])
app.include_router(watch_rooms.router, prefix="/api/watch/rooms", tags=["Watch Rooms"])
app.include_router(watch_history.router, prefix="/api/watch/history", tags=["Watch History"])
app.include_router(social.router, prefix="/api/social", tags=["Social"])
app.include_router(watch.router, prefix="/api/watch", tags=["Watch Channels"])


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": str(exc), "code": "internal_error"})


@app.get("/", include_in_schema=False)
async def root():
    if FRONTEND_DIST.exists():
        return FileResponse(FRONTEND_DIST / "index.html")
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    return {"status": "ok", "qb_connected": qb_service.is_connected}


@app.get("/api/health", include_in_schema=False)
async def api_health():
    return await health()


app.mount("/media/hls", StaticFiles(directory=settings.HLS_OUTPUT_DIR), name="media-hls")


if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")

        candidate = FRONTEND_DIST / path
        if path and candidate.is_file():
            return FileResponse(candidate)

        return FileResponse(FRONTEND_DIST / "index.html")
