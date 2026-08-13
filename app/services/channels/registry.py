"""Channel registry — registration, health tracking and graceful degradation.

See docs/CHANNEL_ARCHITECTURE.md §1.8.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Iterable

from app.config import settings
from app.models import ChannelDetail, ChannelInfo, ChannelSearchResult, ChannelStream
from app.services import response_cache
from app.services.channels.age import AgeChannel
from app.services.channels.anilibria import AnilibriaChannel
from app.services.channels.animeheaven import AnimeHeavenChannel
from app.services.channels.base import ChannelError, ChannelProvider
from app.services.channels.bilibili_channel import BilibiliChannel
from app.services.channels.fixture import FixtureChannel
from app.services.channels.gogoanime import GogoanimeChannel
from app.services.channels.kitsu import KitsuChannel
from app.services.channels.libvio import LibvioChannel
from app.services.channels.shikimori import ShikimoriChannel
from app.services.channels.zzzfun import ZzzfunChannel
from app.services.keyword_expand import expand_keywords, normalize_title_key

logger = logging.getLogger(__name__)

FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 120

# Cache TTLs from docs/CHANNEL_ARCHITECTURE.md §1.7.
SEARCH_TTL_SECONDS = 300
SEARCH_AGGREGATE_TIMEOUT_SECONDS = 8.0
DETAIL_TTL_SECONDS = 600
STREAM_TTL_SECONDS = 120

# Keyword expansion bounds (docs §1.2): try at most this many alternatives per
# provider so a broad expansion cannot explode into N×M upstream requests.
MAX_ALTERNATIVES = 4
# Final safety net ONLY: offline expansion strategies (title map / local DB)
# never await, so they return instantly; the sole network layer (Bangumi) is
# bounded inside keyword_expand.py (2s). This outer cap exists purely to guard
# against unexpected hangs (e.g. a stuck local DB lock).
EXPAND_TIMEOUT_SECONDS = 6.0


async def _expand_keywords(keyword: str) -> list[str]:
    """Expand the user keyword, falling back to just the original on any error."""
    try:
        alternatives = await asyncio.wait_for(expand_keywords(keyword), timeout=EXPAND_TIMEOUT_SECONDS)
    except Exception:
        alternatives = []
    if keyword not in alternatives:
        alternatives.insert(0, keyword)
    return alternatives[:MAX_ALTERNATIVES]


class ChannelRegistry:
    """Holds every channel provider and routes aggregated calls to healthy ones."""

    def __init__(self) -> None:
        self._providers: dict[str, ChannelProvider] = {}
        self._failures: dict[str, int] = {}
        self._cooldown_until: dict[str, float] = {}
        # In-memory stream cache only — resolved URLs are short-lived and must
        # not be persisted (docs §1.7).
        self._stream_cache: dict[str, tuple[float, list[dict]]] = {}

    # ------------------------------------------------------------------ setup

    def register(self, provider: ChannelProvider) -> None:
        self._providers[provider.id] = provider

    def register_all(self, providers: Iterable[ChannelProvider]) -> None:
        for provider in providers:
            self.register(provider)

    def get(self, channel_id: str) -> ChannelProvider | None:
        return self._providers.get(channel_id)

    # ----------------------------------------------------------------- health

    def is_healthy(self, provider: ChannelProvider) -> bool:
        if not provider.enabled:
            return False
        if self._failures.get(provider.id, 0) >= FAILURE_THRESHOLD:
            # Circuit is open until the cooldown expires; after that a single
            # success closes it again.
            return time.monotonic() >= self._cooldown_until.get(provider.id, 0.0)
        return True

    def _mark_failure(self, channel_id: str) -> None:
        count = self._failures.get(channel_id, 0) + 1
        self._failures[channel_id] = count
        if count >= FAILURE_THRESHOLD:
            self._cooldown_until[channel_id] = time.monotonic() + COOLDOWN_SECONDS
            logger.warning("Channel %s marked unhealthy (cooldown %ss)", channel_id, COOLDOWN_SECONDS)

    def _mark_success(self, channel_id: str) -> None:
        self._failures.pop(channel_id, None)
        self._cooldown_until.pop(channel_id, None)

    def list_channels(self) -> list[ChannelInfo]:
        """All providers ordered by tab priority (docs §1.2): main 0-50 first,
        backup 60+ after, disabled last. Stable within a priority by name."""
        ordered = sorted(
            self._providers.values(),
            key=lambda p: (p.priority, p.name),
        )
        return [provider.info(healthy=self.is_healthy(provider)) for provider in ordered]

    # ------------------------------------------------------------- aggregation

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        """Run search on all healthy channels in parallel, skipping failures.

        The keyword is first expanded (Chinese/Japanese → English/Romaji
        alternatives, docs §1.2), then every healthy provider is queried per
        alternative. Results are deduped per channel by normalized title and
        cached for SEARCH_TTL_SECONDS (docs §1.7).
        """
        alternatives = await _expand_keywords(keyword)
        results: list[ChannelSearchResult] = []
        # Dual-key dedup (docs §1.2): a hit is a duplicate when the SAME
        # channel returns the same opaque detail_ref (e.g. AnimeHeaven returns
        # both "Sousou no Frieren" and "Frieren: Beyond Journey's End" for one
        # anime) OR the same normalized title (keyword-expansion variants).
        seen_refs: set[tuple[str, str]] = set()
        seen_titles: set[tuple[str, str]] = set()

        async def _run(provider: ChannelProvider) -> None:
            if not provider.supports_search or not self.is_healthy(provider):
                return
            succeeded = False
            failed = False
            for alt in alternatives:
                cache_key = response_cache.make_cache_key(
                    "channel.search.v1",
                    channel=provider.id,
                    keyword=alt,
                    page=page,
                )
                try:
                    payload = await response_cache.get_or_set_json(
                        cache_key=cache_key,
                        cache_group="channel.search",
                        ttl_seconds=SEARCH_TTL_SECONDS,
                        producer=lambda p=provider, a=alt: _search_producer(p, a, page),
                    )
                    succeeded = True
                    for item in payload or []:
                        try:
                            hit = ChannelSearchResult.model_validate(item)
                        except Exception:
                            logger.warning("Channel %s returned an invalid search hit", provider.id)
                            continue
                        ref_key = (hit.channel, hit.detail_ref)
                        title_key = (hit.channel, normalize_title_key(hit.title))
                        if ref_key not in seen_refs and title_key not in seen_titles:
                            seen_refs.add(ref_key)
                            seen_titles.add(title_key)
                            results.append(hit)
                except ChannelError as exc:
                    failed = True
                    logger.warning("Channel %s search failed (%s): %s", provider.id, alt, exc)
                except Exception:
                    failed = True
                    logger.exception("Channel %s search crashed (%s)", provider.id, alt)
            if succeeded:
                self._mark_success(provider.id)
            elif failed:
                self._mark_failure(provider.id)

        tasks = [asyncio.create_task(_run(p)) for p in self._providers.values()]
        done, pending = await asyncio.wait(tasks, timeout=SEARCH_AGGREGATE_TIMEOUT_SECONDS)
        for task in pending:
            task.cancel()
        # _run swallows its own exceptions, but drain done tasks anyway so a
        # stray exception can never surface as "Task exception was never retrieved".
        for task in done:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                task.exception()
        # Main sources first, backup sources later (docs §1.2). Within the same
        # priority keep a deterministic title order.
        results.sort(key=lambda r: (self._priority_of(r.channel), r.title))
        return results

    async def detail(self, channel_id: str, detail_ref: str) -> ChannelDetail:
        provider = self._require_healthy(channel_id)
        if provider.external or not provider.supports_detail:
            return ChannelDetail(channel=channel_id, title=detail_ref)
        cache_key = response_cache.make_cache_key(
            "channel.detail.v1",
            channel=channel_id,
            ref=detail_ref,
        )
        try:
            payload = await response_cache.get_or_set_json(
                cache_key=cache_key,
                cache_group="channel.detail",
                ttl_seconds=DETAIL_TTL_SECONDS,
                producer=lambda p=provider, r=detail_ref: _detail_producer(p, r),
            )
            self._mark_success(channel_id)
            return ChannelDetail.model_validate(payload)
        except ChannelError:
            self._mark_failure(channel_id)
            raise

    async def streams(self, channel_id: str, episode_ref: str) -> list[ChannelStream]:
        provider = self._require_healthy(channel_id)
        if provider.external or not provider.supports_streams:
            return []
        cache_key = f"channel.streams.v1:{channel_id}:{episode_ref}"
        now = time.monotonic()
        cached = self._stream_cache.get(cache_key)
        if cached is not None and now - cached[0] < STREAM_TTL_SECONDS:
            return [ChannelStream.model_validate(item) for item in cached[1]]
        try:
            streams = await provider.get_streams(episode_ref)
            self._mark_success(channel_id)
            self._stream_cache[cache_key] = (now, [s.model_dump(mode="json") for s in streams])
            return streams
        except ChannelError:
            self._mark_failure(channel_id)
            raise

    def external_url(self, channel_id: str, detail_ref: str) -> str:
        provider = self._providers.get(channel_id)
        if provider is None:
            return ""
        return provider.external_url(detail_ref)

    def _priority_of(self, channel_id: str) -> int:
        provider = self._providers.get(channel_id)
        return provider.priority if provider is not None else 100

    def _require_healthy(self, channel_id: str) -> ChannelProvider:
        provider = self._providers.get(channel_id)
        if provider is None:
            raise LookupError(channel_id)
        if not self.is_healthy(provider):
            raise ChannelError(channel_id, "health", "channel is in cooldown", retryable=False)
        return provider


async def _search_producer(provider: ChannelProvider, keyword: str, page: int) -> list[dict]:
    hits = await provider.search(keyword, page)
    return [hit.model_dump(mode="json") for hit in hits]


async def _detail_producer(provider: ChannelProvider, detail_ref: str) -> dict:
    detail = await provider.get_detail(detail_ref)
    return detail.model_dump(mode="json")


#: Process-wide singleton used by the API layer.
registry = ChannelRegistry()
if settings.E2E_FIXTURE:
    # Hermetic E2E mode (docs/E2E_TESTING.md): replace the whole registry with
    # the deterministic fixture provider so tests never depend on external
    # sites, and nothing leaks real channels into the fixture run.
    registry.register_all([FixtureChannel()])
else:
    registry.register_all(
        [
            AgeChannel(),
            LibvioChannel(),
            ZzzfunChannel(),
            AnilibriaChannel(),
            AnimeHeavenChannel(),
            GogoanimeChannel(),
            BilibiliChannel(),
            KitsuChannel(),
            ShikimoriChannel(),
        ]
    )
