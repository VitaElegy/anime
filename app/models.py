from datetime import datetime

from pydantic import BaseModel, Field


class TorrentItem(BaseModel):
    """A single torrent search result."""

    title: str
    magnet: str = ""
    torrent_url: str = ""
    size: str = ""
    seeders: int = 0
    leechers: int = 0
    date: str = ""
    source: str = ""  # "nyaa" or "subsplease"


class SearchResult(BaseModel):
    """Aggregated search results."""

    items: list[TorrentItem] = Field(default_factory=list)
    total: int = 0
    source: str = ""


class DownloadRequest(BaseModel):
    """Request body for adding a download."""

    magnet: str = ""
    torrent_url: str = ""
    save_path: str = ""
    category: str = "anime"


class BatchDownloadRequest(BaseModel):
    """Request body for batch downloads."""

    items: list[DownloadRequest]


class DownloadTask(BaseModel):
    """Status of a download task in qBittorrent."""

    hash: str
    name: str = ""
    progress: float = 0.0  # 0.0 ~ 1.0
    speed: int = 0  # bytes/s
    state: str = ""
    size: int = 0
    eta: int = 0  # seconds, -1 = unknown


class AnimeMetadata(BaseModel):
    """Bangumi anime metadata."""

    id: int
    name_cn: str = ""
    name: str = ""
    summary: str = ""
    score: float = 0.0
    cover_url: str = ""
    cover_local: str = ""


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str
    code: str = "error"
