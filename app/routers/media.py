"""Media library routes for direct play and HLS preparation."""

import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from app.models import MediaAsset, MediaAssetListResponse
from app.services import media_library, media_transcode
from app.services.range_stream import build_range_response

router = APIRouter()


@router.get("/library", response_model=MediaAssetListResponse, summary="List local media library")
async def list_media_library(refresh: bool = Query(False, description="Force rescan download directory")):
    items = media_library.list_library(refresh=refresh)
    return {"items": items, "total": len(items), "refreshed_at": int(time.time())}


@router.post("/scan", response_model=MediaAssetListResponse, summary="Rescan local media files")
async def scan_media_library():
    items = media_library.scan_library()
    return {"items": items, "total": len(items), "refreshed_at": int(time.time())}


@router.get("/{media_id}", response_model=MediaAsset, summary="Get a media asset")
async def get_media_asset(media_id: str):
    asset = media_library.get_media_asset(media_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found")
    return asset


@router.post(
    "/{media_id}/prepare", response_model=MediaAsset, summary="Prepare HLS playback for a media asset"
)
async def prepare_hls(
    media_id: str, force: bool = Query(False, description="Force rebuild even if playlist exists")
):
    existing = media_library.get_media_asset(media_id)
    if existing and not media_library.is_asset_watchable(existing):
        raise HTTPException(status_code=409, detail=media_library.get_asset_block_reason(existing))
    asset = media_transcode.prepare_hls(media_id, force=force)
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found")
    return asset


@router.get("/{media_id}/stream", summary="Direct-play a local media file")
async def stream_media(media_id: str, request: Request):
    asset = media_library.get_media_asset(media_id)
    if asset and not media_library.is_asset_watchable(asset):
        raise HTTPException(status_code=409, detail=media_library.get_asset_block_reason(asset))
    path = media_library.get_media_path(media_id)
    if not path:
        raise HTTPException(status_code=404, detail="Media file not found")
    file_path = Path(path)
    return build_range_response(
        request,
        file_path,
        media_type=media_library.get_media_mime(file_path),
        filename=file_path.name,
    )
