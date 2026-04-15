"""Local media library scanning and playback planning."""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import subprocess
from pathlib import Path

from app.config import settings
from app.services import database as db

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".m4v", ".webm", ".mkv", ".mov", ".avi", ".ts"}
SIDECAR_SUBTITLE_EXTENSIONS = {".ass", ".ssa", ".srt", ".vtt"}
SAFE_VIDEO_CODECS = {"h264", "av1", "vp8", "vp9"}
SAFE_AUDIO_CODECS = {"aac", "mp3", "opus", "vorbis"}
TEXT_SUBTITLE_CODECS = {"subrip", "srt", "webvtt", "mov_text"}
STYLE_HEAVY_SUBTITLE_CODECS = {"ass", "ssa", "hdmv_pgs_subtitle", "dvd_subtitle"}


def _media_id(relative_path: str) -> str:
    return hashlib.md5(relative_path.encode("utf-8")).hexdigest()


def _display_title(path: Path) -> str:
    return path.stem.replace("_", " ").replace(".", " ").strip() or path.name


def _relative_path(path: Path) -> str:
    try:
        return path.relative_to(settings.DOWNLOAD_DIR).as_posix()
    except ValueError:
        return path.name


def _clean_probe_error(message: str) -> str:
    lines = [line.strip() for line in (message or "").splitlines() if line.strip()]
    if not lines:
        return "ffprobe failed"
    keywords = ("invalid", "error", "failed", "unable", "not found", "moov", "ebml")
    picked = [line for line in lines if any(keyword in line.lower() for keyword in keywords)]
    return " | ".join((picked or lines)[-3:])[:400]


def _probe_media(path: Path) -> tuple[dict, str, str]:
    try:
        result = subprocess.run(
            [
                settings.FFPROBE_BIN,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout or "{}"), "ready", ""
    except FileNotFoundError:
        logger.warning("ffprobe not found, falling back to extension-based media inspection")
        return {}, "unavailable", "ffprobe not found"
    except subprocess.CalledProcessError as exc:
        error = _clean_probe_error(exc.stderr)
        logger.warning("ffprobe failed for %s: %s", path, error)
        return {}, "failed", error
    except json.JSONDecodeError as exc:
        logger.warning("ffprobe returned invalid JSON for %s: %s", path, exc)
        return {}, "failed", f"ffprobe returned invalid JSON: {exc}"
    return {}, "failed", "ffprobe failed"


def _sidecar_subtitles(path: Path) -> list[dict]:
    items = []
    for ext in sorted(SIDECAR_SUBTITLE_EXTENSIONS):
        candidate = path.with_suffix(ext)
        if candidate.exists():
            items.append(
                {
                    "path": candidate.name,
                    "codec": ext.lstrip("."),
                    "language": "",
                    "title": candidate.stem,
                    "source": "sidecar",
                }
            )
    return items


def _analyze_media(path: Path) -> dict:
    stat = path.stat()
    relative_path = _relative_path(path)
    probe, probe_status, probe_error = _probe_media(path)
    streams = probe.get("streams", []) if isinstance(probe, dict) else []
    format_info = probe.get("format", {}) if isinstance(probe, dict) else {}

    video_codecs = []
    audio_codecs = []
    subtitle_codecs = []
    subtitles = _sidecar_subtitles(path)

    for stream in streams:
        codec_type = (stream.get("codec_type") or "").strip()
        codec_name = (stream.get("codec_name") or "").strip()
        if codec_type == "video" and codec_name:
            video_codecs.append(codec_name)
        elif codec_type == "audio" and codec_name:
            audio_codecs.append(codec_name)
        elif codec_type == "subtitle" and codec_name:
            subtitle_codecs.append(codec_name)
            subtitles.append(
                {
                    "path": "",
                    "codec": codec_name,
                    "language": (stream.get("tags", {}) or {}).get("language", ""),
                    "title": (stream.get("tags", {}) or {}).get("title", ""),
                    "source": "embedded",
                }
            )

    has_video_stream = any((stream.get("codec_type") or "").strip() == "video" for stream in streams)
    if probe_status == "ready" and not has_video_stream:
        probe_status = "failed"
        probe_error = "未检测到可用的视频流"

    container = (
        (format_info.get("format_name") or "").split(",")[0]
        or path.suffix.lstrip(".").lower()
    )
    duration = float(format_info.get("duration") or 0)

    subtitle_set = {item.get("codec", "") for item in subtitles if item.get("codec")}
    has_style_heavy_subtitles = bool(subtitle_set & STYLE_HEAVY_SUBTITLE_CODECS) or any(
        item.get("codec") in {"ass", "ssa"} for item in subtitles
    )

    if probe_status == "failed":
        direct_play_supported = False
        recommended_mode = "blocked"
    else:
        direct_play_supported = (
            path.suffix.lower() in {".mp4", ".m4v", ".webm"}
            and (not video_codecs or set(video_codecs).issubset(SAFE_VIDEO_CODECS))
            and (not audio_codecs or set(audio_codecs).issubset(SAFE_AUDIO_CODECS))
            and not has_style_heavy_subtitles
        )
        recommended_mode = "direct_play" if direct_play_supported else "pretranscode_hls"

    asset = {
        "media_id": _media_id(relative_path),
        "title": _display_title(path),
        "relative_path": relative_path,
        "source_path": str(path.resolve()),
        "size": stat.st_size,
        "modified_at": int(stat.st_mtime),
        "container": container,
        "duration": duration,
        "video_codecs": sorted(set(video_codecs)),
        "audio_codecs": sorted(set(audio_codecs)),
        "subtitle_codecs": sorted(set(subtitle_codecs)),
        "subtitles": subtitles,
        "probe_status": probe_status,
        "probe_error": probe_error,
        "direct_play_supported": direct_play_supported,
        "recommended_mode": recommended_mode,
    }

    existing = db.get_media_asset(asset["media_id"])
    if existing:
        asset["hls_status"] = existing.get("hls_status", "missing")
        asset["hls_playlist"] = existing.get("hls_playlist", "")
        asset["hls_updated_at"] = existing.get("hls_updated_at", 0)
        asset["last_error"] = existing.get("last_error", "")
    if probe_status == "failed":
        asset["hls_status"] = "error"
        asset["hls_playlist"] = ""
        asset["last_error"] = probe_error

    return asset


def scan_library() -> list[dict]:
    settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    assets = []
    valid_relative_paths = []
    for path in sorted(settings.DOWNLOAD_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        asset = _analyze_media(path)
        db.upsert_media_asset(asset)
        assets.append(db.get_media_asset(asset["media_id"]) or asset)
        valid_relative_paths.append(asset["relative_path"])
    db.delete_missing_media_assets(valid_relative_paths)
    return db.list_media_assets()


def list_library(refresh: bool = False) -> list[dict]:
    if refresh:
        return scan_library()
    assets = db.list_media_assets()
    return assets if assets else scan_library()


def get_media_asset(media_id: str) -> dict | None:
    asset = db.get_media_asset(media_id)
    if asset:
        return asset
    scan_library()
    return db.get_media_asset(media_id)


def get_media_path(media_id: str) -> Path | None:
    asset = get_media_asset(media_id)
    if not asset:
        return None
    path = Path(asset["source_path"])
    return path if path.exists() else None


def get_media_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


def is_asset_watchable(asset: dict | None) -> bool:
    return bool(asset) and asset.get("probe_status") != "failed"


def get_asset_block_reason(asset: dict | None) -> str:
    if not asset:
        return "Media asset not found"
    return asset.get("probe_error") or asset.get("watch_block_reason") or "片源解析失败，暂时不能用于观看"


def get_playback_url(asset: dict) -> str:
    if not is_asset_watchable(asset):
        return ""
    if asset.get("hls_status") == "ready" and asset.get("hls_playlist"):
        return asset["hls_playlist"]
    return f"/api/media/{asset['media_id']}/stream"
