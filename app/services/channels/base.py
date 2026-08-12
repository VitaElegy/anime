"""Channel abstraction layer.

Role contract is defined in docs/CHANNEL_ARCHITECTURE.md §1.1 / §3.
A provider is the ONLY component that talks to an external anime site.
"""

from __future__ import annotations

import abc

from app.models import ChannelDetail, ChannelInfo, ChannelSearchResult, ChannelStream


class ChannelError(Exception):
    """Raised when a channel fails at a specific stage (search/detail/streams)."""

    def __init__(
        self,
        channel: str,
        stage: str,
        message: str = "",
        *,
        retryable: bool = True,
    ):
        super().__init__(f"[{channel}:{stage}] {message}")
        self.channel = channel
        self.stage = stage
        self.retryable = retryable


class ChannelProvider(abc.ABC):
    """One concrete resource site. Responsibilities:

    - ``search``: keyword -> standardized ChannelSearchResult list
    - ``get_detail``: detail_ref -> ChannelDetail (with episode groups)
    - ``get_streams``: episode_ref -> playable ChannelStream list

    It must NOT aggregate, render, cache or play anything itself.
    """

    #: unique channel id, e.g. "age"
    id: str = ""
    #: human readable name, e.g. "AGE动漫"
    name: str = ""
    #: whether this channel is enabled at all
    enabled: bool = True
    supports_search: bool = True
    supports_detail: bool = True
    supports_streams: bool = True
    language: str = "zh"  # "zh" | "ja" | "en" | "zh-en"
    description: str = ""
    #: True = official external-link only channel (no get_streams)
    external: bool = False

    @abc.abstractmethod
    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        """Search the source site for an anime by keyword."""

    async def get_detail(self, detail_ref: str) -> ChannelDetail:
        if not self.supports_detail:
            raise ChannelError(self.id, "detail", "channel does not support detail", retryable=False)
        raise NotImplementedError

    async def get_streams(self, episode_ref: str) -> list[ChannelStream]:
        if not self.supports_streams:
            return []
        raise NotImplementedError

    def external_url(self, detail_ref: str) -> str:
        return ""

    def info(self, healthy: bool = True) -> ChannelInfo:
        return ChannelInfo(
            id=self.id,
            name=self.name,
            enabled=self.enabled,
            healthy=healthy,
            supports_search=self.supports_search,
            supports_detail=self.supports_detail,
            supports_streams=self.supports_streams,
            language=self.language,
            description=self.description,
            external=self.external,
        )
