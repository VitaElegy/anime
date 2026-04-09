import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import settings
from app.routers import anilist as anilist_router, cover_resolve, crawl, download, favorites, image_proxy, metadata, schedule, search, watchparty
from app.services import database as db
from app.services.qbittorrent import qb_service
from app.services.http_client import close_all_clients
from app.services import aria2_engine

logger = logging.getLogger("anime-downloader")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Ensure cache dirs exist
    settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    settings.COVER_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Init SQLite
    db.init_db()

    # Connect to qBittorrent — non-blocking with timeout
    try:
        await asyncio.wait_for(asyncio.to_thread(qb_service.connect), timeout=5)
        logger.info("Connected to qBittorrent at %s", settings.qb_url)
        # Pre-cache engine selection so first request is instant
        from app.routers import download as dl_router
        dl_router._active_engine = "qbittorrent"
        dl_router._engine_checked_at = __import__("time").monotonic()
    except Exception as e:
        logger.warning("qBittorrent not available: %s — trying built-in aria2 engine", e)
        try:
            ok = await aria2_engine.ensure_running()
            if ok:
                logger.info("Built-in aria2 engine started (zero-config BT downloads ready)")
                from app.routers import download as dl_router
                dl_router._active_engine = "aria2"
                dl_router._engine_checked_at = __import__("time").monotonic()
            else:
                logger.warning("aria2 engine also failed — download features disabled until engine available")
        except Exception as e2:
            logger.warning("aria2 engine startup failed: %s", e2)

    yield

    # Shutdown — close all httpx clients + aria2 subprocess
    await aria2_engine.shutdown()
    await close_all_clients()
    logger.info("Shutting down")


app = FastAPI(
    title="Anime Download Manager",
    description="Search anime torrents from Nyaa / SubsPlease, download via qBittorrent, fetch metadata from Bangumi.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — restrict to known frontend origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(search.router, prefix="/api/search", tags=["Search"])
app.include_router(download.router, prefix="/api/download", tags=["Download"])
app.include_router(metadata.router, prefix="/api/metadata", tags=["Metadata"])
app.include_router(favorites.router, prefix="/api/favorites", tags=["Favorites"])
app.include_router(crawl.router, prefix="/api/crawl", tags=["Crawl"])
app.include_router(schedule.router, prefix="/api/schedule", tags=["Schedule"])
app.include_router(image_proxy.router, prefix="/api/image", tags=["Image"])
app.include_router(cover_resolve.router, prefix="/api/covers", tags=["Covers"])
app.include_router(anilist_router.router, prefix="/api/anilist", tags=["AniList"])
app.include_router(watchparty.router, prefix="/api/watchparty", tags=["WatchParty"])


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "code": "internal_error"})


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    return {"status": "ok", "qb_connected": qb_service.is_connected}
