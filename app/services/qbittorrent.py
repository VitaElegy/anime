"""qBittorrent WebAPI service wrapper — thread-safe, concurrency-limited."""

import asyncio
import logging
import socket
import threading
import time

import qbittorrentapi

from app.config import settings
from app.models import DownloadTask

logger = logging.getLogger(__name__)

# Max concurrent qB API calls (qB WebUI is single-threaded internally)
_QB_SEMAPHORE = asyncio.Semaphore(5)
# Max items in a single batch request
MAX_BATCH_SIZE = 30


class QBittorrentService:
    """Thread-safe qBittorrent connection manager with retry-on-fail pattern."""

    def __init__(self):
        self._client: qbittorrentapi.Client | None = None
        self._connected = False
        self._lock = threading.Lock()
        self._last_check: float = 0
        self._check_interval: float = 30.0  # seconds between health checks

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self):
        """Login to qBittorrent. Raises on failure. Thread-safe."""
        with self._lock:
            # Double-check after acquiring lock
            if self._connected and self._client is not None:
                try:
                    self._client.app.version
                    return
                except Exception:
                    pass

            # Quick port check
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            try:
                sock.connect((settings.QB_HOST, settings.QB_PORT))
            except (ConnectionRefusedError, OSError, socket.timeout) as e:
                self._connected = False
                raise ConnectionError(f"qBittorrent not reachable at {settings.QB_HOST}:{settings.QB_PORT}") from e
            finally:
                sock.close()

            self._client = qbittorrentapi.Client(
                host=settings.QB_HOST,
                port=settings.QB_PORT,
                username=settings.QB_USERNAME,
                password=settings.QB_PASSWORD,
                REQUESTS_ARGS={"timeout": 10},
            )
            self._client.auth_log_in()
            self._connected = True
            self._last_check = time.monotonic()
            logger.info("qBittorrent version: %s", self._client.app.version)

    def _ensure_connected(self):
        """Reconnect if needed. Uses cached check to avoid excessive pings."""
        if not self._connected or self._client is None:
            self.connect()
            return

        # Skip health check if recently verified
        now = time.monotonic()
        if now - self._last_check < self._check_interval:
            return

        # Periodic health check (every 30s, not every request)
        try:
            self._client.app.version
            self._last_check = now
        except Exception:
            logger.warning("qBittorrent connection lost, reconnecting...")
            self._connected = False
            self.connect()

    def _call_with_retry(self, fn):
        """Execute a qB API call (zero-arg callable) with one retry on connection failure.

        All callers pass a lambda that captures self._client at call time,
        so after reconnect the lambda automatically uses the new client.
        """
        try:
            self._ensure_connected()
            assert self._client is not None
            return fn()
        except (qbittorrentapi.exceptions.APIConnectionError, AssertionError):
            logger.warning("qB call failed, retrying after reconnect...")
            self._connected = False
            self.connect()
            assert self._client is not None
            return fn()

    def add_torrent(
        self,
        magnet: str = "",
        torrent_url: str = "",
        save_path: str = "",
        category: str = "anime",
    ) -> str:
        """Add a single torrent. Returns "Ok." on success."""
        kwargs: dict = {"category": category}
        kwargs["save_path"] = save_path or str(settings.DOWNLOAD_DIR)

        if magnet:
            return self._call_with_retry(lambda: self._client.torrents_add(urls=magnet, **kwargs))
        elif torrent_url:
            return self._call_with_retry(lambda: self._client.torrents_add(urls=torrent_url, **kwargs))
        else:
            raise ValueError("Must provide either magnet or torrent_url")

    async def add_torrents_batch(self, items: list[dict]) -> list[dict]:
        """
        Add multiple torrents with concurrency limit.
        Max MAX_BATCH_SIZE items, max 5 concurrent qB calls.
        """
        if len(items) > MAX_BATCH_SIZE:
            items = items[:MAX_BATCH_SIZE]
            logger.warning("Batch truncated to %d items", MAX_BATCH_SIZE)

        async def _add_one(idx: int, item: dict) -> dict:
            async with _QB_SEMAPHORE:
                try:
                    result = await asyncio.to_thread(
                        self.add_torrent,
                        magnet=item.get("magnet", ""),
                        torrent_url=item.get("torrent_url", ""),
                        save_path=item.get("save_path", ""),
                        category=item.get("category", "anime"),
                    )
                    ok = result == "Ok."
                    return {"index": idx, "status": "ok" if ok else "error", "detail": result}
                except Exception as e:
                    return {"index": idx, "status": "error", "detail": str(e)}

        tasks = [_add_one(i, item) for i, item in enumerate(items)]
        return list(await asyncio.gather(*tasks))

    def get_progress(self, torrent_hash: str) -> DownloadTask | None:
        """Get progress of a single torrent by hash."""
        torrents = self._call_with_retry(
            lambda: self._client.torrents_info(torrent_hashes=torrent_hash)
        )
        if not torrents:
            return None
        t = torrents[0]
        return DownloadTask(
            hash=t.hash, name=t.name, progress=t.progress,
            speed=t.dlspeed, state=t.state, size=t.total_size,
            eta=t.eta if t.eta != 8640000 else -1,
        )

    def get_all_progress(self, category: str = "") -> list[DownloadTask]:
        """Get progress of all torrents."""
        kwargs = {}
        if category:
            kwargs["category"] = category
        torrents = self._call_with_retry(
            lambda: self._client.torrents_info(**kwargs)
        )
        return [
            DownloadTask(
                hash=t.hash, name=t.name, progress=t.progress,
                speed=t.dlspeed, state=t.state, size=t.total_size,
                eta=t.eta if t.eta != 8640000 else -1,
            )
            for t in torrents
        ]

    def pause(self, torrent_hash: str):
        self._call_with_retry(
            lambda: self._client.torrents_pause(torrent_hashes=torrent_hash)
        )

    def resume(self, torrent_hash: str):
        self._call_with_retry(
            lambda: self._client.torrents_resume(torrent_hashes=torrent_hash)
        )

    def delete(self, torrent_hash: str, delete_files: bool = False):
        self._call_with_retry(
            lambda: self._client.torrents_delete(torrent_hashes=torrent_hash, delete_files=delete_files)
        )


# Singleton instance
qb_service = QBittorrentService()
