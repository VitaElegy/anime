"""Download management routes — add, pause, resume, delete, progress."""

import asyncio

from fastapi import APIRouter, HTTPException, Query

from app.models import BatchDownloadRequest, DownloadRequest, DownloadTask
from app.services.qbittorrent import qb_service

router = APIRouter()


def _check_connected():
    if not qb_service.is_connected:
        raise HTTPException(status_code=503, detail="qBittorrent is not connected")


@router.post("", summary="Add a single download")
async def add_download(req: DownloadRequest):
    _check_connected()
    try:
        result = await asyncio.to_thread(
            qb_service.add_torrent,
            magnet=req.magnet,
            torrent_url=req.torrent_url,
            save_path=req.save_path,
            category=req.category,
        )
        return {"status": "ok" if result == "Ok." else "error", "detail": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/batch", summary="Batch add multiple downloads concurrently")
async def add_batch(req: BatchDownloadRequest):
    _check_connected()
    items = [
        {
            "magnet": item.magnet,
            "torrent_url": item.torrent_url,
            "save_path": item.save_path,
            "category": item.category,
        }
        for item in req.items
    ]
    results = await qb_service.add_torrents_batch(items)
    return {"results": results}


@router.get("/progress", response_model=list[DownloadTask], summary="List all download progress")
async def list_progress(
    category: str = Query("", description="Filter by category (empty = all)"),
):
    _check_connected()
    return await asyncio.to_thread(qb_service.get_all_progress, category)


@router.get("/progress/{torrent_hash}", response_model=DownloadTask, summary="Get single torrent progress")
async def get_progress(torrent_hash: str):
    _check_connected()
    task = await asyncio.to_thread(qb_service.get_progress, torrent_hash)
    if task is None:
        raise HTTPException(status_code=404, detail="Torrent not found")
    return task


@router.put("/{torrent_hash}/pause", summary="Pause a torrent")
async def pause_torrent(torrent_hash: str):
    _check_connected()
    await asyncio.to_thread(qb_service.pause, torrent_hash)
    return {"status": "ok"}


@router.put("/{torrent_hash}/resume", summary="Resume a torrent")
async def resume_torrent(torrent_hash: str):
    _check_connected()
    await asyncio.to_thread(qb_service.resume, torrent_hash)
    return {"status": "ok"}


@router.delete("/{torrent_hash}", summary="Delete a torrent")
async def delete_torrent(
    torrent_hash: str,
    delete_files: bool = Query(False, description="Also delete downloaded files"),
):
    _check_connected()
    await asyncio.to_thread(qb_service.delete, torrent_hash, delete_files)
    return {"status": "ok"}
