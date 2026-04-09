"""Built-in aria2 BT download engine — zero-config magnet/torrent download.

Auto-downloads aria2c binary on first use, starts it as a background subprocess
with JSON-RPC enabled, and provides the same interface as qbittorrent.py.

Used as automatic fallback when qBittorrent is not available.
"""

import asyncio
import hashlib
import io
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx

from app.config import settings
from app.models import DownloadTask

logger = logging.getLogger(__name__)

# aria2c binary location
_BIN_DIR = Path(__file__).resolve().parent.parent.parent / "bin"
_ARIA2C_EXE = _BIN_DIR / ("aria2c.exe" if platform.system() == "Windows" else "aria2c")

# aria2 RPC config
_RPC_PORT = 6800
_RPC_SECRET = "nicotracker"
_RPC_URL = f"http://localhost:{_RPC_PORT}/jsonrpc"

# Download URL for aria2c (GitHub release)
_ARIA2_VERSION = "1.37.0"
_ARIA2_DOWNLOAD_URLS = {
    "Windows": f"https://github.com/aria2/aria2/releases/download/release-{_ARIA2_VERSION}/aria2-{_ARIA2_VERSION}-win-64bit-build1.zip",
}

# State
_process: subprocess.Popen | None = None
_api = None  # aria2p.API instance
_started = False


def _find_aria2c() -> Path | None:
    """Find aria2c binary: 1) project bin/, 2) system PATH."""
    if _ARIA2C_EXE.exists():
        return _ARIA2C_EXE
    system_path = shutil.which("aria2c")
    if system_path:
        return Path(system_path)
    return None


async def _download_aria2c() -> Path | None:
    """Download aria2c binary for current platform."""
    system = platform.system()
    url = _ARIA2_DOWNLOAD_URLS.get(system)
    if not url:
        logger.error("No aria2c download available for %s", system)
        return None

    logger.info("Downloading aria2c from %s ...", url)
    _BIN_DIR.mkdir(parents=True, exist_ok=True)

    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        # Extract aria2c.exe from zip
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            for name in zf.namelist():
                if name.endswith("aria2c.exe") or name.endswith("aria2c"):
                    data = zf.read(name)
                    _ARIA2C_EXE.write_bytes(data)
                    if system != "Windows":
                        _ARIA2C_EXE.chmod(0o755)
                    logger.info("aria2c extracted to %s (%d bytes)", _ARIA2C_EXE, len(data))
                    return _ARIA2C_EXE

        logger.error("aria2c binary not found in downloaded archive")
        return None
    except Exception as e:
        logger.error("Failed to download aria2c: %s", e)
        return None


def _start_process(aria2c_path: Path) -> bool:
    """Start aria2c as a background subprocess with RPC enabled."""
    global _process

    if _process and _process.poll() is None:
        return True  # Already running

    download_dir = settings.DOWNLOAD_DIR
    download_dir.mkdir(parents=True, exist_ok=True)

    # Session file for task persistence across restarts
    session_dir = Path(__file__).resolve().parent.parent.parent / "data"
    session_dir.mkdir(parents=True, exist_ok=True)
    session_file = session_dir / "aria2.session"
    # Create empty session file if it doesn't exist
    if not session_file.exists():
        session_file.touch()
    # DHT data persistence
    dht_file = session_dir / "dht.dat"

    cmd = [
        str(aria2c_path),
        "--enable-rpc",
        f"--rpc-listen-port={_RPC_PORT}",
        f"--rpc-secret={_RPC_SECRET}",
        "--rpc-listen-all=false",
        f"--dir={download_dir}",
        # ── Session persistence (restart recovery) ──
        f"--save-session={session_file}",
        f"--input-file={session_file}",
        "--save-session-interval=30",
        "--force-save=true",
        # ── Resume / continue ──
        "--continue=true",
        "--auto-file-renaming=false",
        "--allow-overwrite=false",
        # ── BT settings ──
        "--seed-time=0",
        "--bt-save-metadata=true",
        f"--bt-metadata-only=false",
        "--max-concurrent-downloads=5",
        "--max-connection-per-server=16",
        "--split=16",
        "--min-split-size=1M",
        "--bt-enable-lpd=true",
        f"--dht-file-path={dht_file}",
        "--dht-listen-port=6881",
        "--listen-port=6881",
        "--enable-dht=true",
        "--enable-peer-exchange=true",
        "--bt-request-peer-speed-limit=10M",
        "--bt-max-peers=100",
        "--quiet=true",
        "--console-log-level=warn",
    ]

    try:
        # Suppress console window on Windows
        kwargs = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        _process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **kwargs,
        )
        # Wait briefly to check it didn't crash immediately
        time.sleep(0.5)
        if _process.poll() is not None:
            stderr = _process.stderr.read().decode(errors="replace") if _process.stderr else ""
            logger.error("aria2c exited immediately: %s", stderr[:500])
            return False

        logger.info("aria2c started (PID %d) on RPC port %d", _process.pid, _RPC_PORT)
        return True
    except Exception as e:
        logger.error("Failed to start aria2c: %s", e)
        return False


def _get_api():
    """Get or create aria2p API instance."""
    global _api
    if _api is None:
        import aria2p
        _api = aria2p.API(
            aria2p.Client(host="http://localhost", port=_RPC_PORT, secret=_RPC_SECRET)
        )
    return _api


async def ensure_running() -> bool:
    """Ensure aria2c is downloaded and running. Returns True if ready."""
    global _started

    if _started and _process and _process.poll() is None:
        return True

    # Find or download aria2c
    aria2c_path = _find_aria2c()
    if not aria2c_path:
        aria2c_path = await _download_aria2c()
    if not aria2c_path:
        return False

    # Start subprocess
    ok = _start_process(aria2c_path)
    if ok:
        _started = True
    return ok


async def shutdown():
    """Stop aria2c subprocess gracefully — saves session first for restart recovery."""
    global _process, _started, _api

    # Try to save session via RPC before killing
    if _api and _started:
        try:
            _api.client.save_session()
            logger.info("aria2 session saved")
        except Exception as e:
            logger.warning("Failed to save aria2 session via RPC: %s", e)

    if _process and _process.poll() is None:
        try:
            _process.terminate()
            _process.wait(timeout=5)
            logger.info("aria2c stopped gracefully")
        except Exception:
            _process.kill()
            logger.warning("aria2c killed forcefully")
    _process = None
    _started = False
    _api = None


# ─── Download interface (mirrors qbittorrent.py) ───


def add_torrent(
    magnet: str = "",
    torrent_url: str = "",
    save_path: str = "",
    category: str = "anime",
) -> str:
    """Add a single torrent/magnet. Returns 'Ok.' on success."""
    api = _get_api()
    opts = {}
    if save_path:
        opts["dir"] = save_path

    uri = magnet or torrent_url
    if not uri:
        raise ValueError("Must provide either magnet or torrent_url")

    try:
        downloads = api.add(uri, options=opts)
        if downloads:
            d = downloads[0] if isinstance(downloads, list) else downloads
            logger.info("aria2 download added: %s (gid=%s)", d.name or uri[:60], d.gid)
            return "Ok."
        return "Failed to add download"
    except Exception as e:
        logger.error("aria2 add_torrent failed: %s", e)
        raise


def _safe_eta(d) -> int:
    """Extract ETA in seconds from aria2p Download. Returns -1 if unknown."""
    try:
        if not d.eta or not hasattr(d.eta, "total_seconds"):
            return -1
        secs = int(d.eta.total_seconds())
        # aria2p returns 999999999 days when ETA is unknown
        if secs > 86400 * 365:  # > 1 year = unknown
            return -1
        return secs
    except Exception:
        return -1


def get_all_progress(category: str = "") -> list[DownloadTask]:
    """Get all download tasks."""
    api = _get_api()
    tasks = []

    try:
        for d in api.get_downloads():
            # Skip metadata downloads (intermediate aria2 magnet resolution)
            if getattr(d, "is_metadata", False):
                continue
            # Skip if name starts with [METADATA]
            name = d.name or ""
            if name.startswith("[METADATA]"):
                continue

            # Map aria2 status to qB-compatible state
            state_map = {
                "active": "downloading",
                "waiting": "queuedDL",
                "paused": "pausedDL",
                "complete": "stalledUP",
                "removed": "error",
                "error": "error",
            }
            state = state_map.get(d.status, d.status)
            if d.is_complete:
                state = "stalledUP"
            # Active but speed=0 → searching peers
            if d.status == "active" and (d.download_speed or 0) == 0:
                state = "stalledDL"

            tasks.append(DownloadTask(
                hash=d.gid,
                name=name or "(unknown)",
                progress=d.progress / 100.0 if d.progress else 0.0,
                speed=d.download_speed or 0,
                state=state,
                size=d.total_length or 0,
                eta=_safe_eta(d),
            ))
    except Exception as e:
        logger.error("aria2 get_all_progress failed: %s", e)

    return tasks


def get_progress(gid: str) -> DownloadTask | None:
    """Get progress of a single download by GID."""
    api = _get_api()
    try:
        d = api.get_download(gid)
        if not d:
            return None
        if d.is_complete:
            state = "stalledUP"
        elif d.status == "paused":
            state = "pausedDL"
        elif d.is_active:
            state = "downloading" if (d.download_speed or 0) > 0 else "stalledDL"
        else:
            state = d.status
        return DownloadTask(
            hash=d.gid,
            name=d.name or "(unknown)",
            progress=d.progress / 100.0 if d.progress else 0.0,
            speed=d.download_speed or 0,
            state=state,
            size=d.total_length or 0,
            eta=_safe_eta(d),
        )
    except Exception as e:
        logger.error("aria2 get_progress failed for %s: %s", gid, e)
        return None


def pause(gid: str):
    """Pause a download."""
    api = _get_api()
    try:
        api.pause([api.get_download(gid)])
    except Exception as e:
        logger.error("aria2 pause failed for %s: %s", gid, e)


def resume(gid: str):
    """Resume a paused download."""
    api = _get_api()
    try:
        api.resume([api.get_download(gid)])
    except Exception as e:
        logger.error("aria2 resume failed for %s: %s", gid, e)


def delete(gid: str, delete_files: bool = False):
    """Remove a download."""
    api = _get_api()
    try:
        d = api.get_download(gid)
        if d:
            api.remove([d], force=True, files=delete_files)
    except Exception as e:
        logger.error("aria2 delete failed for %s: %s", gid, e)
