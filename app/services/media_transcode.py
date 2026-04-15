"""Offline HLS preparation for locally downloaded media."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from app.config import settings
from app.services import database as db
from app.services import media_library

logger = logging.getLogger(__name__)

_transcode_tasks: dict[str, asyncio.Task] = {}


def _summarize_ffmpeg_error(message: str) -> str:
    lines = [line.strip() for line in (message or "").splitlines() if line.strip()]
    if not lines:
        return "ffmpeg failed"
    keywords = ("invalid", "error", "failed", "unable", "not found", "moov", "ebml")
    picked = [line for line in lines if any(keyword in line.lower() for keyword in keywords)]
    return " | ".join((picked or lines)[-4:])[:500]


def _output_dir(media_id: str) -> Path:
    return settings.HLS_OUTPUT_DIR / media_id


def _playlist_path(media_id: str) -> Path:
    return _output_dir(media_id) / "index.m3u8"


def _playlist_url(media_id: str) -> str:
    return f"/media/hls/{media_id}/index.m3u8"


def _escape_filter_path(path: Path) -> str:
    value = str(path.resolve())
    value = value.replace("\\", "\\\\")
    for ch in (":", "'", "[", "]", ","):
        value = value.replace(ch, f"\\{ch}")
    return value


def _subtitle_filter(source_path: Path, asset: dict) -> str | None:
    sidecar = next((item for item in asset.get("subtitles", []) if item.get("source") == "sidecar"), None)
    if sidecar and sidecar.get("path"):
        subtitle_path = source_path.with_name(sidecar["path"])
        if subtitle_path.exists():
            return f"subtitles='{_escape_filter_path(subtitle_path)}'"
    if asset.get("subtitle_codecs"):
        return f"subtitles='{_escape_filter_path(source_path)}'"
    return None


async def _run_ffmpeg(media_id: str):
    asset = media_library.get_media_asset(media_id)
    if not asset:
        return
    if not media_library.is_asset_watchable(asset):
        db.update_media_hls_status(
            media_id,
            status="error",
            playlist="",
            last_error=media_library.get_asset_block_reason(asset),
        )
        return
    source_path = Path(asset["source_path"])
    if not source_path.exists():
        db.update_media_hls_status(media_id, status="error", last_error="Source file not found")
        return

    outdir = _output_dir(media_id)
    playlist = _playlist_path(media_id)
    if outdir.exists():
        shutil.rmtree(outdir, ignore_errors=True)
    outdir.mkdir(parents=True, exist_ok=True)

    command = [
        settings.FFMPEG_BIN,
        "-y",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
    ]
    subtitle_filter = _subtitle_filter(source_path, asset)
    if subtitle_filter:
        command.extend(["-vf", subtitle_filter])

    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ac",
            "2",
            "-sn",
            "-f",
            "hls",
            "-hls_time",
            "6",
            "-hls_playlist_type",
            "vod",
            "-hls_segment_filename",
            str(outdir / "segment_%03d.ts"),
            str(playlist),
        ]
    )

    logger.info("Preparing HLS for %s", source_path)
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0 or not playlist.exists():
        db.update_media_hls_status(
            media_id,
            status="error",
            playlist="",
            last_error=_summarize_ffmpeg_error(stderr.decode("utf-8", "ignore")),
        )
        return

    db.update_media_hls_status(
        media_id,
        status="ready",
        playlist=_playlist_url(media_id),
        last_error="",
    )


async def _prepare(media_id: str):
    try:
        await _run_ffmpeg(media_id)
    except FileNotFoundError:
        db.update_media_hls_status(media_id, status="error", last_error="ffmpeg not found")
    except Exception as exc:
        logger.exception("Failed to prepare HLS for %s", media_id)
        db.update_media_hls_status(media_id, status="error", last_error=str(exc))
    finally:
        _transcode_tasks.pop(media_id, None)


def prepare_hls(media_id: str, force: bool = False) -> dict | None:
    asset = media_library.get_media_asset(media_id)
    if not asset:
        return None
    if not media_library.is_asset_watchable(asset):
        db.update_media_hls_status(
            media_id,
            status="error",
            playlist="",
            last_error=media_library.get_asset_block_reason(asset),
        )
        return db.get_media_asset(media_id)

    playlist = _playlist_path(media_id)
    if asset.get("hls_status") == "ready" and playlist.exists() and not force:
        return asset

    task = _transcode_tasks.get(media_id)
    if task and not task.done() and not force:
        return db.get_media_asset(media_id)

    db.update_media_hls_status(media_id, status="preparing", playlist=_playlist_url(media_id), last_error="")
    _transcode_tasks[media_id] = asyncio.create_task(_prepare(media_id))
    return db.get_media_asset(media_id)


def is_preparing(media_id: str) -> bool:
    task = _transcode_tasks.get(media_id)
    return bool(task and not task.done())
