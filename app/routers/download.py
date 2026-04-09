"""Download management routes — add, pause, resume, delete, progress.

Dual-engine architecture:
  - Primary: qBittorrent (if available)
  - Fallback: built-in aria2 engine (auto-downloaded, zero-config)

The active engine is selected automatically at startup and on each request.
"""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.config import settings
from app.models import BatchDownloadRequest, DownloadRequest, DownloadTask
from app.services.qbittorrent import qb_service
from app.services import aria2_engine

logger = logging.getLogger(__name__)
router = APIRouter()

# Which engine is active: "qbittorrent", "aria2", or None
_active_engine: str | None = None
_engine_checked_at: float = 0
_ENGINE_CACHE_TTL = 60  # seconds


async def _get_engine() -> str:
    """Determine which download engine to use. Caches result to avoid repeated slow probes."""
    global _active_engine, _engine_checked_at
    import time

    now = time.monotonic()

    # Fast path: cached and still valid
    if _active_engine and (now - _engine_checked_at) < _ENGINE_CACHE_TTL:
        return _active_engine

    # Check if qBittorrent is already connected (instant, no I/O)
    if qb_service.is_connected:
        _active_engine = "qbittorrent"
        _engine_checked_at = now
        return "qbittorrent"

    # Try qBittorrent connect in thread (non-blocking, 0.5s socket timeout)
    try:
        await asyncio.wait_for(asyncio.to_thread(qb_service.connect), timeout=2)
        _active_engine = "qbittorrent"
        _engine_checked_at = now
        logger.info("Switched to qBittorrent engine")
        return "qbittorrent"
    except Exception:
        pass

    # Fallback to aria2 (usually instant if already running)
    ok = await aria2_engine.ensure_running()
    if ok:
        _active_engine = "aria2"
        _engine_checked_at = now
        return "aria2"

    raise HTTPException(
        status_code=503,
        detail="下载引擎不可用：qBittorrent 未连接，aria2 启动失败。",
    )


def _validate_save_path(save_path: str) -> str:
    """Validate save_path is within DOWNLOAD_DIR to prevent path traversal."""
    if not save_path:
        return str(settings.DOWNLOAD_DIR)
    resolved = Path(save_path).resolve()
    allowed = settings.DOWNLOAD_DIR.resolve()
    if not str(resolved).startswith(str(allowed)):
        raise HTTPException(status_code=400, detail="save_path must be within the download directory")
    return str(resolved)


@router.get("/engine", summary="Get current download engine info")
async def get_engine_info():
    """Return which download engine is active."""
    engine = await _get_engine()
    return {
        "engine": engine,
        "qbittorrent_connected": qb_service.is_connected,
        "aria2_available": aria2_engine._started,
    }


@router.post("", summary="Add a single download")
async def add_download(req: DownloadRequest):
    engine = await _get_engine()
    validated_path = _validate_save_path(req.save_path)
    magnet_short = req.magnet[:80] if req.magnet else "(none)"
    url_short = req.torrent_url[:80] if req.torrent_url else "(none)"
    logger.info("[%s] Adding download: magnet=%s, url=%s", engine, magnet_short, url_short)

    try:
        if engine == "qbittorrent":
            result = await asyncio.to_thread(
                qb_service.add_torrent,
                magnet=req.magnet,
                torrent_url=req.torrent_url,
                save_path=validated_path,
                category=req.category,
            )
        else:
            result = await asyncio.to_thread(
                aria2_engine.add_torrent,
                magnet=req.magnet,
                torrent_url=req.torrent_url,
                save_path=validated_path,
            )

        ok = result == "Ok."
        if ok:
            logger.info("[%s] Download added successfully", engine)
        else:
            logger.warning("[%s] Download result: %s", engine, result)
        return {"status": "ok" if ok else "error", "detail": result, "engine": engine}
    except Exception as e:
        logger.error("[%s] Download failed: %s", engine, e, exc_info=True)
        raise HTTPException(status_code=400, detail=f"添加下载失败: {e}")


@router.post("/batch", summary="Batch add multiple downloads concurrently")
async def add_batch(req: BatchDownloadRequest):
    engine = await _get_engine()
    if len(req.items) > 30:
        raise HTTPException(status_code=400, detail="Maximum 30 items per batch")

    items = [
        {
            "magnet": item.magnet,
            "torrent_url": item.torrent_url,
            "save_path": _validate_save_path(item.save_path),
            "category": item.category,
        }
        for item in req.items
    ]

    if engine == "qbittorrent":
        results = await qb_service.add_torrents_batch(items)
    else:
        # aria2: sequential add with semaphore
        results = []
        for i, item in enumerate(items):
            try:
                r = await asyncio.to_thread(
                    aria2_engine.add_torrent,
                    magnet=item.get("magnet", ""),
                    torrent_url=item.get("torrent_url", ""),
                    save_path=item.get("save_path", ""),
                )
                results.append({"index": i, "status": "ok" if r == "Ok." else "error", "detail": r})
            except Exception as e:
                results.append({"index": i, "status": "error", "detail": str(e)})

    return {"results": results, "engine": engine}


@router.get("/progress", response_model=list[DownloadTask], summary="List all download progress")
async def list_progress(
    category: str = Query("", description="Filter by category (empty = all)"),
):
    engine = await _get_engine()
    if engine == "qbittorrent":
        return await asyncio.to_thread(qb_service.get_all_progress, category)
    else:
        return await asyncio.to_thread(aria2_engine.get_all_progress, category)


@router.get("/progress/{torrent_hash}", response_model=DownloadTask, summary="Get single torrent progress")
async def get_progress(torrent_hash: str):
    engine = await _get_engine()
    if engine == "qbittorrent":
        task = await asyncio.to_thread(qb_service.get_progress, torrent_hash)
    else:
        task = await asyncio.to_thread(aria2_engine.get_progress, torrent_hash)
    if task is None:
        raise HTTPException(status_code=404, detail="Torrent not found")
    return task


@router.put("/{torrent_hash}/pause", summary="Pause a torrent")
async def pause_torrent(torrent_hash: str):
    engine = await _get_engine()
    if engine == "qbittorrent":
        await asyncio.to_thread(qb_service.pause, torrent_hash)
    else:
        await asyncio.to_thread(aria2_engine.pause, torrent_hash)
    return {"status": "ok"}


@router.put("/{torrent_hash}/resume", summary="Resume a torrent")
async def resume_torrent(torrent_hash: str):
    engine = await _get_engine()
    if engine == "qbittorrent":
        await asyncio.to_thread(qb_service.resume, torrent_hash)
    else:
        await asyncio.to_thread(aria2_engine.resume, torrent_hash)
    return {"status": "ok"}


@router.delete("/{torrent_hash}", summary="Delete a torrent")
async def delete_torrent(
    torrent_hash: str,
    delete_files: bool = Query(False, description="Also delete downloaded files"),
):
    engine = await _get_engine()
    if engine == "qbittorrent":
        await asyncio.to_thread(qb_service.delete, torrent_hash, delete_files)
    else:
        await asyncio.to_thread(aria2_engine.delete, torrent_hash, delete_files)
    return {"status": "ok"}


# ─── Settings API ───


@router.get("/settings", summary="Get download settings")
async def get_settings():
    """Return current download directory and other settings."""
    download_dir = settings.DOWNLOAD_DIR.resolve()
    return {
        "download_dir": str(download_dir),
        "exists": download_dir.exists(),
        "free_space": _get_free_space(download_dir),
    }


class UpdateSettingsRequest(BaseModel):
    download_dir: str | None = None


@router.put("/settings", summary="Update download settings")
async def update_settings(req: UpdateSettingsRequest):
    """Update download directory. Creates the directory if it doesn't exist."""
    if req.download_dir:
        new_dir = Path(req.download_dir).resolve()
        try:
            new_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"无法创建目录: {e}")
        settings.DOWNLOAD_DIR = new_dir
        logger.info("Download directory changed to: %s", new_dir)
    return {
        "download_dir": str(settings.DOWNLOAD_DIR.resolve()),
        "exists": settings.DOWNLOAD_DIR.exists(),
        "free_space": _get_free_space(settings.DOWNLOAD_DIR),
    }


def _get_free_space(path: Path) -> int:
    """Get free disk space in bytes for the drive containing path."""
    try:
        import shutil
        usage = shutil.disk_usage(str(path) if path.exists() else str(path.parent))
        return usage.free
    except Exception:
        return 0


# ─── File Browser API ───

# File types to hide from browser (control/temp files)
_HIDDEN_EXTS = {".aria2", ".torrent", ".nfo", ".txt", ".url", ".html", ".htm", ".log", ".part"}
# Media file extensions
_VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".ts", ".flv", ".webm", ".rmvb", ".mov", ".wmv"}
_AUDIO_EXTS = {".flac", ".mp3", ".aac", ".opus", ".ogg", ".wav", ".m4a"}
_SUB_EXTS = {".ass", ".srt", ".ssa", ".sub", ".idx", ".sup", ".vtt"}
_MEDIA_EXTS = _VIDEO_EXTS | _AUDIO_EXTS | _SUB_EXTS


def _classify_file(ext: str) -> str:
    """Classify file by extension."""
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "audio"
    if ext in _SUB_EXTS:
        return "subtitle"
    if ext in {".zip", ".rar", ".7z"}:
        return "archive"
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
        return "image"
    return "other"


def _count_media_in_dir(directory: Path) -> tuple[int, int, int]:
    """Count video files, total media files, and total media size in a directory."""
    videos = 0
    media_count = 0
    media_size = 0
    try:
        for f in directory.rglob("*"):
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            if ext in _HIDDEN_EXTS:
                continue
            if ext in _MEDIA_EXTS:
                media_count += 1
                media_size += f.stat().st_size
                if ext in _VIDEO_EXTS:
                    videos += 1
    except Exception:
        pass
    return videos, media_count, media_size


@router.get("/files", summary="Browse downloaded files")
async def list_files(
    subdir: str = Query("", description="Subdirectory relative to download dir"),
    show_all: bool = Query(False, description="Show hidden/temp files too"),
):
    """List files and folders in the download directory. Hides temp files by default."""
    base = settings.DOWNLOAD_DIR.resolve()
    target = (base / subdir).resolve() if subdir else base

    # Security: ensure target is within download dir
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="路径不在下载目录内")

    if not target.exists():
        return {"path": str(target), "relative": subdir, "items": []}

    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            ext = entry.suffix.lower()

            # Hide temp/control files unless show_all
            if not show_all and entry.is_file() and ext in _HIDDEN_EXTS:
                continue

            rel = str(entry.relative_to(base)).replace("\\", "/")
            if entry.is_dir():
                videos, media_count, media_size = _count_media_in_dir(entry)
                # Skip empty directories (no media inside)
                if not show_all and media_count == 0:
                    continue
                items.append({
                    "name": entry.name,
                    "path": rel,
                    "type": "dir",
                    "size": media_size,
                    "file_count": media_count,
                    "video_count": videos,
                    "modified": entry.stat().st_mtime,
                })
            else:
                stat = entry.stat()
                items.append({
                    "name": entry.name,
                    "path": rel,
                    "type": "file",
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "ext": ext,
                    "category": _classify_file(ext),
                })
    except PermissionError:
        raise HTTPException(status_code=403, detail="没有权限访问此目录")

    return {
        "path": str(target),
        "relative": subdir,
        "parent": str(Path(subdir).parent) if subdir else "",
        "items": items,
    }


@router.delete("/files/{file_path:path}", summary="Delete a downloaded file or folder")
async def delete_file(file_path: str, confirm: bool = Query(False)):
    """Delete a file or empty folder from the download directory."""
    base = settings.DOWNLOAD_DIR.resolve()
    target = (base / file_path).resolve()

    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="路径不在下载目录内")
    if not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    if not confirm:
        return {"status": "confirm", "detail": f"确认删除 {target.name}?", "size": target.stat().st_size if target.is_file() else 0}

    import shutil
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        logger.info("Deleted: %s", target)
        return {"status": "ok", "detail": f"已删除 {target.name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")
