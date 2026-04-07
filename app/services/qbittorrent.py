"""qBittorrent WebAPI service wrapper."""

import asyncio
import logging
import socket

import qbittorrentapi

from app.config import settings
from app.models import DownloadTask

logger = logging.getLogger(__name__)


class QBittorrentService:
    """Manages connection and operations with qBittorrent."""

    def __init__(self):
        self._client: qbittorrentapi.Client | None = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self):
        """Login to qBittorrent. Raises on failure."""
        # Quick port check to avoid long urllib3 retry waits
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        try:
            sock.connect((settings.QB_HOST, settings.QB_PORT))
        except (ConnectionRefusedError, OSError, socket.timeout) as e:
            raise ConnectionError(f"qBittorrent not reachable at {settings.QB_HOST}:{settings.QB_PORT}") from e
        finally:
            sock.close()

        self._client = qbittorrentapi.Client(
            host=settings.QB_HOST,
            port=settings.QB_PORT,
            username=settings.QB_USERNAME,
            password=settings.QB_PASSWORD,
            REQUESTS_ARGS={"timeout": 5},
        )
        self._client.auth_log_in()
        self._connected = True
        logger.info("qBittorrent version: %s", self._client.app.version)

    def _ensure_connected(self):
        """Reconnect if needed."""
        if not self._connected or self._client is None:
            self.connect()
            return
        try:
            self._client.app.version  # lightweight ping
        except Exception:
            logger.warning("qBittorrent connection lost, reconnecting...")
            self.connect()

    def add_torrent(
        self,
        magnet: str = "",
        torrent_url: str = "",
        save_path: str = "",
        category: str = "anime",
    ) -> str:
        """
        Add a single torrent.

        Returns "Ok." on success.
        """
        self._ensure_connected()
        assert self._client is not None

        kwargs: dict = {"category": category}
        if save_path:
            kwargs["save_path"] = save_path
        else:
            kwargs["save_path"] = str(settings.DOWNLOAD_DIR)

        if magnet:
            result = self._client.torrents_add(urls=magnet, **kwargs)
        elif torrent_url:
            result = self._client.torrents_add(urls=torrent_url, **kwargs)
        else:
            raise ValueError("Must provide either magnet or torrent_url")

        return result  # "Ok." or "Fails."

    async def add_torrents_batch(self, items: list[dict]) -> list[dict]:
        """
        Add multiple torrents concurrently.

        Each item: {"magnet": ..., "torrent_url": ..., "save_path": ..., "category": ...}
        Returns list of {"index": i, "status": "ok"/"error", "detail": ...}
        """

        async def _add_one(idx: int, item: dict) -> dict:
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
        return await asyncio.gather(*tasks)

    def get_progress(self, torrent_hash: str) -> DownloadTask | None:
        """Get progress of a single torrent by hash."""
        self._ensure_connected()
        assert self._client is not None

        torrents = self._client.torrents_info(torrent_hashes=torrent_hash)
        if not torrents:
            return None

        t = torrents[0]
        return DownloadTask(
            hash=t.hash,
            name=t.name,
            progress=t.progress,
            speed=t.dlspeed,
            state=t.state,
            size=t.total_size,
            eta=t.eta if t.eta != 8640000 else -1,
        )

    def get_all_progress(self, category: str = "") -> list[DownloadTask]:
        """Get progress of all torrents, optionally filtered by category."""
        self._ensure_connected()
        assert self._client is not None

        kwargs = {}
        if category:
            kwargs["category"] = category
        torrents = self._client.torrents_info(**kwargs)

        return [
            DownloadTask(
                hash=t.hash,
                name=t.name,
                progress=t.progress,
                speed=t.dlspeed,
                state=t.state,
                size=t.total_size,
                eta=t.eta if t.eta != 8640000 else -1,
            )
            for t in torrents
        ]

    def pause(self, torrent_hash: str):
        self._ensure_connected()
        assert self._client is not None
        self._client.torrents_pause(torrent_hashes=torrent_hash)

    def resume(self, torrent_hash: str):
        self._ensure_connected()
        assert self._client is not None
        self._client.torrents_resume(torrent_hashes=torrent_hash)

    def delete(self, torrent_hash: str, delete_files: bool = False):
        self._ensure_connected()
        assert self._client is not None
        self._client.torrents_delete(
            torrent_hashes=torrent_hash,
            delete_files=delete_files,
        )


# Singleton instance
qb_service = QBittorrentService()
