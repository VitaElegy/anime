"""E2E fixture channel — deterministic test double for the full watch journey.

Role contract: docs/CHANNEL_ARCHITECTURE.md §1.1 / §3, and
docs/E2E_TESTING.md §2 (test doubles). This provider is NOT a real resource
site: it exists so Playwright can exercise 中文搜 → 卡片 → 渠道 → 集数 →
实际观看 end-to-end without any external network.

It is only registered when ``ANIME_E2E_FIXTURE=1`` (see
app/services/channels/registry.py), so production registries never see it.

Responsibilities (same as any ChannelProvider):
- ``search``: keyword -> standardized ChannelSearchResult list
- ``get_detail``: detail_ref -> ChannelDetail (with episode groups)
- ``get_streams``: episode_ref -> playable ChannelStream list

It does NOT aggregate, render, cache or play anything itself.
"""

from __future__ import annotations

from app.config import settings
from app.models import (
    ChannelDetail,
    ChannelEpisode,
    ChannelEpisodeGroup,
    ChannelSearchResult,
    ChannelStream,
)
from app.services.channels.base import ChannelProvider

#: Keywords that make the fixture hit. Kept intentionally generous so the
#: hermetic E2E can search in Chinese (the core UX promise) and still hit.
_FRIEREN_KEYS = ("frieren", "葬送", "芙莉莲", "芙莉")

FIXTURE_TITLE = "葬送的芙莉莲（E2E 测试源）"
FIXTURE_RAW_TITLE = "Sousou no Frieren"
FIXTURE_DETAIL_REF = "fixture:frieren"
FIXTURE_EPISODE_COUNT = 3


class FixtureChannel(ChannelProvider):
    """Deterministic local channel used by the Playwright E2E suite."""

    id = "fixture"
    name = "E2E Fixture"
    language = "zh"
    description = "本地 E2E 测试源（仅 ANIME_E2E_FIXTURE=1 时注册，不访问外网）"
    #: Front of the tab so the test never depends on another channel's health.
    priority = 1

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        kw = (keyword or "").strip().lower()
        if not any(key in kw for key in _FRIEREN_KEYS):
            return []
        return [
            ChannelSearchResult(
                channel=self.id,
                title=FIXTURE_TITLE,
                title_original=FIXTURE_RAW_TITLE,
                cover_url="",
                description="E2E fixture：一条确定性的本地播放链路。",
                year="2023",
                detail_ref=FIXTURE_DETAIL_REF,
            )
        ]

    async def get_detail(self, detail_ref: str) -> ChannelDetail:
        return ChannelDetail(
            channel=self.id,
            title=FIXTURE_TITLE,
            description="E2E fixture：用于验证 中文搜 → 卡片 → 渠道 → 集数 → 实际观看。",
            groups=[
                ChannelEpisodeGroup(
                    title="全 28 集（测试取 3 集）",
                    episodes=[
                        ChannelEpisode(title=f"第 {i} 集", episode_ref=f"fixture:ep:{i}")
                        for i in range(1, FIXTURE_EPISODE_COUNT + 1)
                    ],
                )
            ],
        )

    async def get_streams(self, episode_ref: str) -> list[ChannelStream]:
        return [
            ChannelStream(
                type="web",
                url=f"{settings.E2E_STREAM_BASE}/fixture.webm",
                quality="1080p",
                note="E2E fixture stream（本地 webm，经真实 StreamProxy 播放）",
            )
        ]
