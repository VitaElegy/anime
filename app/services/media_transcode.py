"""Offline HLS preparation for locally downloaded media.

This module turns arbitrary source media (MKV / 4K HEVC / multi-audio, etc.)
into a multi-bitrate HLS ladder suitable for streaming to any modern browser:

- Picks a hardware encoder (NVENC / QSV / AMF / VideoToolbox) when available,
  falling back to libx264 on CPU. 4K HEVC → H.264 transcode with NVENC takes
  ~30 seconds / minute instead of 10+ minutes on CPU.
- Generates 3 quality rungs (1080p / 720p / 480p) and a master playlist so
  hls.js can ABR-switch automatically — the highest-bandwidth viewer sees
  full quality, the weakest link in the room doesn't drag everyone down.
- Burns in subtitles when present (Advanced SubStation Alpha / embedded PGS
  are not playable natively in browsers).
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.services import database as db
from app.services import media_library

logger = logging.getLogger(__name__)

# Cap concurrent transcodes so a burst of "prepare" clicks can't saturate the
# machine's CPU / disk. Two in flight is plenty for a home server; adjust via
# env if someone really needs more.
_MAX_CONCURRENT_TRANSCODES = 2
_transcode_semaphore: asyncio.Semaphore | None = None

_transcode_tasks: dict[str, asyncio.Task] = {}

# ffmpeg ``-progress`` emits ``key=value\n`` pairs separated by a blank line.
# We care mostly about ``out_time_ms`` to compute completion percentage.
_PROGRESS_LINE = re.compile(r"^(?P<key>[a-zA-Z_]+)=(?P<value>.*)$")


# ---------------------------------------------------------------------------
# Hardware encoder detection
#
# We probe ffmpeg exactly once and cache the result. The probe is "can we
# actually initialize this encoder on the current host?" — merely listing the
# encoder in ``-encoders`` is not enough because the driver / runtime may be
# missing even though ffmpeg was compiled with support.
# ---------------------------------------------------------------------------
_HW_CANDIDATES = (
    # (encoder_name, friendly_label, preset_args tuple)
    ("h264_nvenc", "NVIDIA NVENC", ("-preset", "p4", "-tune", "hq", "-rc", "vbr")),
    (
        "h264_qsv",
        "Intel Quick Sync",
        (
            "-preset",
            "medium",
        ),
    ),
    (
        "h264_amf",
        "AMD AMF",
        (
            "-quality",
            "balanced",
        ),
    ),
    ("h264_videotoolbox", "Apple VideoToolbox", ()),
)


@lru_cache(maxsize=1)
def _detect_video_encoder() -> tuple[str, str, tuple[str, ...]]:
    """Return (encoder, label, preset_args) — hardware preferred, x264 fallback."""
    for encoder, label, preset in _HW_CANDIDATES:
        try:
            # A dry-run encode of one frame of synthetic video is the cheapest
            # way to check the encoder is actually functional, not just listed.
            result = subprocess.run(
                [
                    settings.FFMPEG_BIN,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=black:s=320x240:r=1:d=0.1",
                    "-c:v",
                    encoder,
                    "-frames:v",
                    "1",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                timeout=15,
            )
            if result.returncode == 0:
                logger.info("Using hardware video encoder: %s (%s)", encoder, label)
                return encoder, label, preset
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue

    logger.info("No hardware encoder available, falling back to libx264 (CPU)")
    return "libx264", "libx264 (CPU)", ("-preset", "veryfast", "-tune", "film")


def detect_video_encoder() -> dict:
    """Public helper — surface the selected encoder to API / UI."""
    name, label, _ = _detect_video_encoder()
    return {"encoder": name, "label": label, "hardware": name != "libx264"}


# ---------------------------------------------------------------------------
# ABR ladder — three rungs cover everyone from mobile to 1080p desktop.
# ``max_height`` keeps the aspect ratio intact; sources smaller than a rung's
# height are downscaled-through (ffmpeg "scale=-2:min(ih,N)") not upscaled.
# ---------------------------------------------------------------------------
ABR_RUNGS: tuple[dict, ...] = (
    # name      max_height  v_bitrate  maxrate   bufsize   a_bitrate
    {
        "name": "1080p",
        "height": 1080,
        "v_bitrate": "5000k",
        "maxrate": "6000k",
        "bufsize": "10000k",
        "a_bitrate": "192k",
    },
    {
        "name": "720p",
        "height": 720,
        "v_bitrate": "2800k",
        "maxrate": "3400k",
        "bufsize": "6000k",
        "a_bitrate": "160k",
    },
    {
        "name": "480p",
        "height": 480,
        "v_bitrate": "1200k",
        "maxrate": "1500k",
        "bufsize": "2500k",
        "a_bitrate": "128k",
    },
)


def _pick_rungs(source_height: int) -> list[dict]:
    """Skip rungs larger than the source to avoid up-scaling.

    Always keep the smallest rung so low-bandwidth viewers have a fighting
    chance regardless of the source resolution.
    """
    if source_height <= 0:
        return list(ABR_RUNGS)
    kept = [r for r in ABR_RUNGS if r["height"] <= source_height]
    if not kept:
        kept = [ABR_RUNGS[-1]]  # smallest rung as a last resort
    return kept


def _get_semaphore() -> asyncio.Semaphore:
    """Lazily create the semaphore so we bind it to the running event loop."""
    global _transcode_semaphore
    if _transcode_semaphore is None:
        _transcode_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_TRANSCODES)
    return _transcode_semaphore


def _transcode_log_path(media_id: str) -> Path:
    log_dir = settings.STREAM_CACHE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{media_id}.log"


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


async def _consume_progress(
    stdout: asyncio.StreamReader,
    media_id: str,
    duration_seconds: float,
    rung_count: int,
    rung_index: int,
) -> None:
    """Parse ``-progress pipe:1`` output and publish percentage snapshots.

    With an ABR ladder we run ``rung_count`` ffmpeg passes sequentially, so the
    overall percentage is ``(rung_index + current_rung_pct) / rung_count``.
    """
    last_publish = 0.0
    while True:
        line = await stdout.readline()
        if not line:
            return
        decoded = line.decode("utf-8", errors="ignore").strip()
        if not decoded:
            continue
        match = _PROGRESS_LINE.match(decoded)
        if not match:
            continue
        key, value = match.group("key"), match.group("value")
        if key != "out_time_ms":
            continue
        try:
            out_time_seconds = int(value) / 1_000_000.0
        except ValueError:
            continue
        if duration_seconds <= 0:
            continue
        rung_pct = max(0.0, min(1.0, out_time_seconds / duration_seconds))
        overall = (rung_index + rung_pct) / max(1, rung_count)
        pct = max(0, min(99, int(round(overall * 100))))
        loop = asyncio.get_running_loop()
        if loop.time() - last_publish < 1.0:
            continue
        last_publish = loop.time()
        await asyncio.to_thread(
            db.update_media_hls_status,
            media_id,
            status="preparing",
            playlist=_playlist_url(media_id),
            last_error="",
            progress=pct,
        )


def _source_height(asset: dict) -> int:
    """Best-effort resolution parse; falls back to 0 meaning 'unknown'."""
    for key in ("height", "video_height"):
        val = asset.get(key)
        if val:
            try:
                return int(val)
            except (ValueError, TypeError):
                continue
    return 0


def _build_rung_command(
    source_path: Path,
    outdir: Path,
    rung: dict,
    asset: dict,
    encoder: str,
    encoder_preset: tuple[str, ...],
) -> list[str]:
    """Build a single-variant ffmpeg command for one ABR rung."""
    command = [settings.FFMPEG_BIN, "-y", "-i", str(source_path)]

    # Always encode the primary video stream and the default audio stream.
    # Tolerate files with no audio via the "?" modifier on the audio map.
    command.extend(["-map", "0:v:0", "-map", "0:a:0?"])

    # Video filter chain: subtitles first (burn-in), then scale. Scale uses
    # ``min(ih,H)`` so small sources aren't upscaled.
    filters: list[str] = []
    subtitle_filter = _subtitle_filter(source_path, asset)
    if subtitle_filter:
        filters.append(subtitle_filter)
    filters.append(f"scale=-2:'min(ih,{rung['height']})'")
    command.extend(["-vf", ",".join(filters)])

    # Video codec + encoder-specific preset. Tune CBR-ish via maxrate/bufsize
    # so hls.js can make accurate ABR decisions.
    command.extend(["-c:v", encoder])
    command.extend(list(encoder_preset))
    command.extend(
        [
            "-b:v",
            rung["v_bitrate"],
            "-maxrate",
            rung["maxrate"],
            "-bufsize",
            rung["bufsize"],
        ]
    )
    if encoder == "libx264":
        # -profile high and -level 4.1 keeps 1080p compatible with virtually
        # every browser including iOS Safari.
        command.extend(["-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p"])

    # Audio: always transcode to AAC stereo 48k for maximum compatibility.
    command.extend(
        [
            "-c:a",
            "aac",
            "-b:a",
            rung["a_bitrate"],
            "-ac",
            "2",
            "-ar",
            "48000",
        ]
    )

    # Keep segment size small (4s) for snappier seeking / faster first frame.
    command.extend(
        [
            "-sn",
            "-f",
            "hls",
            "-hls_time",
            "4",
            "-hls_playlist_type",
            "vod",
            "-hls_flags",
            "independent_segments",
            "-hls_segment_filename",
            str(outdir / "segment_%03d.ts"),
            "-progress",
            "pipe:1",
            "-nostats",
            str(outdir / "playlist.m3u8"),
        ]
    )
    return command


def _write_master_playlist(media_id: str, rungs_used: list[dict]) -> None:
    """Write the top-level master playlist referencing each rung's sub-playlist.

    hls.js picks an initial variant based on its own heuristics and then
    switches up/down as measured bandwidth changes. Each viewer thus gets the
    best quality their connection supports without the room host having to
    pick a global setting.
    """
    root = _output_dir(media_id)
    lines = ["#EXTM3U", "#EXT-X-VERSION:6"]
    for rung in rungs_used:
        # Bandwidth estimate = video bitrate + audio bitrate (bits/s).
        v_bps = int(rung["v_bitrate"].rstrip("k")) * 1000
        a_bps = int(rung["a_bitrate"].rstrip("k")) * 1000
        bandwidth = v_bps + a_bps
        # Approximate width assuming 16:9 aspect; close enough for ABR hints.
        width = int(rung["height"] * 16 / 9)
        lines.append(
            f'#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={width}x{rung["height"]},NAME="{rung["name"]}"'
        )
        lines.append(f"{rung['name']}/playlist.m3u8")
    (root / "index.m3u8").write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    if outdir.exists():
        shutil.rmtree(outdir, ignore_errors=True)
    outdir.mkdir(parents=True, exist_ok=True)

    encoder, encoder_label, encoder_preset = _detect_video_encoder()
    rungs = _pick_rungs(_source_height(asset))
    duration_seconds = float(asset.get("duration") or 0)

    logger.info(
        "Preparing HLS for %s (media_id=%s) using %s with %d rung(s): %s",
        source_path,
        media_id,
        encoder_label,
        len(rungs),
        [r["name"] for r in rungs],
    )

    all_stderr: list[str] = []

    for rung_index, rung in enumerate(rungs):
        rung_dir = outdir / rung["name"]
        rung_dir.mkdir(parents=True, exist_ok=True)
        command = _build_rung_command(source_path, rung_dir, rung, asset, encoder, encoder_preset)

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # NOTE: We consume stdout (progress) and stderr (logs) in parallel via
        # dedicated tasks. Do NOT also call process.communicate() — it would
        # race with _consume_progress on the same stdout reader and trigger
        # ``RuntimeError: read() called while another coroutine is already
        # waiting for incoming data`` on Python 3.12+.
        progress_task = asyncio.create_task(
            _consume_progress(
                process.stdout,  # type: ignore[arg-type]
                media_id,
                duration_seconds,
                rung_count=len(rungs),
                rung_index=rung_index,
            )
        )

        async def _drain_stderr(process=process) -> bytes:
            chunks: list[bytes] = []
            while True:
                assert process.stderr is not None
                chunk = await process.stderr.read(64 * 1024)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)

        stderr_task = asyncio.create_task(_drain_stderr())

        return_code = await process.wait()
        # Give the drainers a moment to flush anything buffered after exit.
        stderr_bytes, _ = await asyncio.gather(stderr_task, progress_task)

        stderr_text = stderr_bytes.decode("utf-8", errors="ignore")
        all_stderr.append(f"=== rung {rung['name']} ===\n{stderr_text}")

        if return_code != 0 or not (rung_dir / "playlist.m3u8").exists():
            try:
                _transcode_log_path(media_id).write_text("\n".join(all_stderr), encoding="utf-8")
            except OSError:
                logger.warning("Failed to persist transcode log for %s", media_id, exc_info=True)
            db.update_media_hls_status(
                media_id,
                status="error",
                playlist="",
                last_error=_summarize_ffmpeg_error(stderr_text),
            )
            return

    # All rungs succeeded — stitch them into a master playlist and mark ready.
    _write_master_playlist(media_id, rungs)

    try:
        _transcode_log_path(media_id).write_text("\n".join(all_stderr), encoding="utf-8")
    except OSError:
        logger.warning("Failed to persist transcode log for %s", media_id, exc_info=True)

    db.update_media_hls_status(
        media_id,
        status="ready",
        playlist=_playlist_url(media_id),
        last_error="",
    )


async def _prepare(media_id: str):
    """Wait for a transcode slot, run ffmpeg, and clean up task bookkeeping."""
    semaphore = _get_semaphore()
    # Reflect queue position in the stored state so the UI can distinguish
    # "queued behind other jobs" from "currently running".
    db.update_media_hls_status(
        media_id,
        status="queued",
        playlist=_playlist_url(media_id),
        last_error="",
    )
    try:
        async with semaphore:
            db.update_media_hls_status(
                media_id,
                status="preparing",
                playlist=_playlist_url(media_id),
                last_error="",
            )
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

    db.update_media_hls_status(media_id, status="queued", playlist=_playlist_url(media_id), last_error="")
    _transcode_tasks[media_id] = asyncio.create_task(_prepare(media_id))
    return db.get_media_asset(media_id)


def is_preparing(media_id: str) -> bool:
    task = _transcode_tasks.get(media_id)
    if task and not task.done():
        return True
    asset = db.get_media_asset(media_id)
    if not asset:
        return False
    return asset.get("hls_status") in {"queued", "preparing"}


def transcode_log_path(media_id: str) -> Path:
    """Expose the transcode log location for diagnostics."""
    return _transcode_log_path(media_id)
