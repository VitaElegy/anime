from pathlib import Path

from pydantic_settings import BaseSettings

# qBittorrent ships with this as the factory default WebUI password. We refuse
# to start in production when nobody bothered to change it, so a careless
# ``.env`` cannot cause us to happily drive whoever's qBittorrent happens to
# answer at the configured host.
_QB_FACTORY_PASSWORD = "adminadmin"


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    # Deployment mode. ``production`` triggers extra safety checks on startup.
    ENV: str = "development"

    # qBittorrent connection
    QB_HOST: str = "localhost"
    QB_PORT: int = 8080
    QB_USERNAME: str = "admin"
    QB_PASSWORD: str = _QB_FACTORY_PASSWORD

    # Bangumi API
    BANGUMI_API_BASE: str = "https://api.bgm.tv"

    # Nyaa
    NYAA_BASE_URL: str = "https://nyaa.land"

    # SubsPlease
    SUBSPLEASE_RSS: str = "https://subsplease.org/rss/?r=1080"

    # Mikan Project (中文字幕组资源聚合) — 国内镜像优先，自动回退到主域名
    MIKAN_BASE_URL: str = "https://mikanani.me"
    MIKAN_MIRROR_URL: str = "https://mikanani.kas.pub"

    # AnimeGarden (动漫花园+moe 开源聚合 API, 直接提供结构化 JSON)
    ANIME_GARDEN_API_BASE: str = "https://api.animes.garden"

    # Bilibili 番剧 (公开 API, 免 Cookie)
    BILIBILI_API_BASE: str = "https://api.bilibili.com"

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
    MIKAN_RATE_LIMIT: float = 1.0
    ANIME_GARDEN_RATE_LIMIT: float = 0.5
    BILIBILI_RATE_LIMIT: float = 0.8

    model_config = {"env_prefix": "ANIME_", "env_file": ".env", "extra": "ignore"}

    @property
    def qb_url(self) -> str:
        return f"http://{self.QB_HOST}:{self.QB_PORT}"

    @property
    def is_production(self) -> bool:
        return self.ENV.strip().lower() in {"production", "prod"}

    def assert_runtime_safety(self) -> None:
        """Raise if an obviously unsafe configuration is about to go live.

        Called from the FastAPI ``lifespan`` on startup. We only block the
        process in production — development setups are free to keep the
        factory default password while poking at a local qBittorrent.
        """
        if self.is_production and self.QB_PASSWORD == _QB_FACTORY_PASSWORD:
            raise RuntimeError(
                "ANIME_QB_PASSWORD is still set to qBittorrent's factory default "
                "'adminadmin' while ANIME_ENV=production. Set a real password in "
                ".env before starting the server."
            )


settings = Settings()
