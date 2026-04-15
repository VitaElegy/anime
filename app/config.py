from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    # qBittorrent connection
    QB_HOST: str = "localhost"
    QB_PORT: int = 8080
    QB_USERNAME: str = "admin"
    QB_PASSWORD: str = "adminadmin"

    # Bangumi API
    BANGUMI_API_BASE: str = "https://api.bgm.tv"

    # Nyaa
    NYAA_BASE_URL: str = "https://nyaa.land"

    # SubsPlease
    SUBSPLEASE_RSS: str = "https://subsplease.org/rss/?r=1080"

    # Paths
    # Keep defaults repo-local so a fresh Linux/Windows checkout can start
    # without first editing absolute paths. Production should still override
    # these via environment variables or .env.
    DOWNLOAD_DIR: Path = Path("data/downloads")
    COVER_CACHE_DIR: Path = Path("data/covers")
    STREAM_CACHE_DIR: Path = Path("data/streams")
    HLS_OUTPUT_DIR: Path = Path("data/streams/hls")

    # Media tooling
    FFMPEG_BIN: str = "ffmpeg"
    FFPROBE_BIN: str = "ffprobe"

    # HTTP proxy for sites blocked by GFW (Nyaa, dmhy, etc.)
    # e.g. "http://127.0.0.1:7890" or "socks5://127.0.0.1:7891"
    HTTP_PROXY: str = ""

    # Rate limiting (seconds between requests)
    NYAA_RATE_LIMIT: float = 1.0
    BANGUMI_RATE_LIMIT: float = 0.5

    model_config = {"env_prefix": "ANIME_", "env_file": ".env", "extra": "ignore"}

    @property
    def qb_url(self) -> str:
        return f"http://{self.QB_HOST}:{self.QB_PORT}"


settings = Settings()
