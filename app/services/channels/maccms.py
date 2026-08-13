"""Maccms (AppleCMS) 资源站家族 — direct-HLS Chinese backup channels.

Port of the interface pattern from the Miru extensions `360zy.com.js` /
`ikunzy.com.js` / `yhzy.cc.js` (https://github.com/miru-project/repo, MIT).
These resource sites expose the standard AppleCMS JSON API
`GET /api.php/provide/vod`:

- search: `?ac=detail&wd=<kw>&pg=<n>`  -> `{ list: [ { vod_id, vod_name,
  vod_pic, vod_remarks, ... } ] }`
- detail: `?ac=detail&ids=<id>`        -> `{ list: [ { vod_name, vod_pic,
  vod_content, vod_play_url } ] }`
- play:   `vod_play_url` =
  `"第01集$https://cdn/.../index.m3u8#第02集$https://cdn/.../index.m3u8"`

The episode URLs are direct HLS master playlists (no player page, no
Cloudflare on the primary domains) — verified playable 2026-08-13 via Clash
7892 (maowushi / bfikuncdn / wgslsw CDNs, MPEG-TS `47 40` magic).

Each concrete provider is a thin subclass carrying its mirror-domain list;
the shared base tries every domain and returns the first success (mirrors the
`Promise.any` behaviour of the Miru extensions, so a dead mirror never breaks
the channel).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from urllib.parse import urlencode

from app.models import (
    ChannelDetail,
    ChannelEpisode,
    ChannelEpisodeGroup,
    ChannelSearchResult,
    ChannelStream,
)
from app.services.channels import http
from app.services.channels.base import ChannelError, ChannelProvider

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Remove HTML tags/entities for human-readable description fields."""
    text = _TAG_RE.sub(" ", text or "")
    return re.sub(r"\s+", " ", text).strip()


class MaccmsChannel(ChannelProvider):
    """One AppleCMS resource site (search/detail/streams over the JSON API).

    Subclasses only declare ``id`` / ``name`` / ``domains`` / ``description``;
    the API shape is identical across the family.
    """

    #: mirror API hosts tried in parallel; first success wins (docs §2.8)
    domains: tuple[str, ...] = ()

    #: AppleCMS play-source hint. Miru extensions request the direct-m3u8
    #: source explicitly (e.g. ``from=jsm3u8``) so ``vod_play_url`` only
    #: carries m3u8 URLs instead of player-page links (docs §2.8).
    api_from: str | None = None

    #: per-request timeout for one mirror (docs §2.8: Miru uses 4-5s)
    _MIRROR_TIMEOUT = 5.0
    #: overall cap for the whole mirror race (registry search cap is 8s)
    _RACE_TIMEOUT = 7.5

    # ------------------------------------------------------------- helpers

    async def _api(self, stage: str, params: dict) -> dict:
        """Race all mirrors concurrently and return the first JSON payload.

        Raises ChannelError when every mirror fails or the race times out.
        """
        if not self.domains:
            raise ChannelError(self.id, stage, "no mirror domains configured", retryable=False)

        if self.api_from:
            params = {**params, "from": self.api_from}
        query = urlencode(params)
        pending = {
            asyncio.create_task(
                http.request(
                    self.id,
                    stage,
                    "GET",
                    f"https://{domain}/api.php/provide/vod?{query}",
                    timeout=self._MIRROR_TIMEOUT,
                )
            )
            for domain in self.domains
        }
        deadline = time.monotonic() + self._RACE_TIMEOUT
        last_error: Exception | None = None
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            done, pending = await asyncio.wait(
                pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                try:
                    resp = task.result()
                except Exception as exc:
                    # Consume the failure; keep racing the remaining mirrors.
                    last_error = exc if isinstance(exc, ChannelError) else exc
                    logger.debug("Maccms mirror failed for %s: %s", self.id, exc)
                    continue
                # Success: retrieve any other completed exceptions, then cancel
                # the still-pending mirrors so they cannot leak.
                for other in done:
                    other.exception()
                if pending:
                    for other in pending:
                        other.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                try:
                    return resp.json()
                except Exception as exc:
                    raise ChannelError(self.id, stage, f"invalid json: {exc}") from exc
        if pending:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        raise ChannelError(
            self.id,
            stage,
            str(last_error) if last_error else "all mirror domains timed out",
        )

    # ----------------------------------------------------------- contract

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        payload = await self._api("search", {"ac": "detail", "wd": keyword, "pg": page})
        out: list[ChannelSearchResult] = []
        for item in payload.get("list") or []:
            vid = item.get("vod_id")
            if vid is None:
                continue
            out.append(
                ChannelSearchResult(
                    channel=self.id,
                    title=str(item.get("vod_name") or ""),
                    title_original=str(item.get("vod_en") or item.get("vod_pinyin") or ""),
                    cover_url=str(item.get("vod_pic") or ""),
                    description=_strip_html(str(item.get("vod_content") or ""))[:300],
                    year=str(item.get("vod_year") or ""),
                    detail_ref=str(vid),
                    extra={"remarks": str(item.get("vod_remarks") or "")},
                )
            )
        return out

    @staticmethod
    def _is_direct_media(url: str) -> bool:
        """True for a directly playable media URL (m3u8/mp4), not a player page."""
        return bool(re.search(r"\.(m3u8|mp4)(?:[?#]|$)", url.lower()))

    def _parse_play_sources(
        self, vod_play_url: str, remarks: str = ""
    ) -> list[list[ChannelEpisode]]:
        """Split ``vod_play_url`` into per-source episode lists.

        AppleCMS packs multiple play sources into one string separated by
        ``$$$`` (e.g. ``jsyun$$$jsm3u8``). Miru extensions request the direct
        source via ``from=`` so the API normally returns one m3u8 source, but
        without that hint the first source may be player-page links
        (``/play/<id>``, an HTML page — not programmable). We therefore drop
        non-direct sources whenever at least one source carries real m3u8/mp4
        URLs; player pages are kept only as a last-resort fallback.
        """
        sources: list[list[ChannelEpisode]] = []
        for chunk in (vod_play_url or "").split("$$$"):
            episodes: list[ChannelEpisode] = []
            for piece in chunk.split("#"):
                piece = piece.strip()
                if "$" not in piece:
                    continue
                name, url = piece.split("$", 1)
                url = url.strip()
                if not url.startswith(("http://", "https://")):
                    continue
                episodes.append(
                    ChannelEpisode(
                        title=name.strip(),
                        episode_ref=url,
                        extra={"remarks": remarks} if remarks else {},
                    )
                )
            if episodes:
                sources.append(episodes)
        direct = [eps for eps in sources if any(self._is_direct_media(e.episode_ref) for e in eps)]
        if direct:
            sources = direct
        return sources

    async def get_detail(self, detail_ref: str) -> ChannelDetail:
        payload = await self._api("detail", {"ac": "detail", "ids": detail_ref})
        items = payload.get("list") or []
        if not items:
            raise ChannelError(self.id, "detail", "empty vod list", retryable=False)
        item = items[0]
        remarks = str(item.get("vod_remarks") or "")

        sources = self._parse_play_sources(str(item.get("vod_play_url") or ""), remarks)
        source_names = [name for name in (str(item.get("vod_play_from") or "")).split("$$$") if name]

        groups: list[ChannelEpisodeGroup] = []
        for index, episodes in enumerate(sources):
            # Single direct source keeps the neutral "线路" label (backwards
            # compatible); multiple sources get their AppleCMS source names.
            if len(sources) == 1:
                title = "线路"
            elif index < len(source_names) and source_names[index]:
                title = source_names[index]
            else:
                title = f"线路{index + 1}"
            groups.append(ChannelEpisodeGroup(title=title, episodes=episodes))

        return ChannelDetail(
            channel=self.id,
            title=str(item.get("vod_name") or ""),
            cover_url=str(item.get("vod_pic") or ""),
            description=_strip_html(str(item.get("vod_content") or item.get("vod_blurb") or ""))[:1000],
            groups=groups,
        )

    async def get_streams(self, episode_ref: str) -> list[ChannelStream]:
        if not episode_ref.startswith(("http://", "https://")):
            return []
        is_hls = ".m3u8" in episode_ref.lower()
        return [
            ChannelStream(
                type="hls" if is_hls else "mp4",
                url=episode_ref,
                quality="auto",
                format="m3u8" if is_hls else "mp4",
                headers={"Referer": f"https://{self.domains[0]}/", "User-Agent": http.DEFAULT_UA},
                note=self.name,
            )
        ]


class Ziyuan360Channel(MaccmsChannel):
    """360资源 — 360zy.com (verified playable 2026-08-13, maowushi CDN)."""

    id = "360zy"
    name = "360资源"
    description = "AppleCMS 直链 HLS 资源站（360资源）"
    domains = ("360zy.com", "360zy.net", "360zy.tv")
    priority = 59  # playable backup: after Miruro (58), before Kitsu (60)


class IKunChannel(MaccmsChannel):
    """iKun资源 — ikunzyapi.com family (verified playable 2026-08-13)."""

    id = "ikunzy"
    name = "iKun资源"
    description = "AppleCMS 直链 HLS 资源站（iKun资源）"
    domains = ("ikunzyapi.com", "ikunzy.com", "ikunzy.net", "ikunzy.org", "ikunzy.vip")
    priority = 59


class YinghuaChannel(MaccmsChannel):
    """樱花资源 — yhzy.cc (verified playable 2026-08-13, wgslsw/yhzybf CDN)."""

    id = "yhzy"
    name = "樱花资源"
    description = "AppleCMS 直链 HLS 资源站（樱花资源）"
    domains = ("yhzy.cc",)
    priority = 59


class JisuChannel(MaccmsChannel):
    """极速资源 — jisuzy.com family (verified playable 2026-08-13, vv.jisuzyv CDN).

    Miru extension requests ``from=jsm3u8`` so the API returns only the direct
    m3u8 source (the default ``jsyun`` source is a player page).
    """

    id = "jisuzy"
    name = "极速资源"
    description = "AppleCMS 直链 HLS 资源站（极速资源）"
    domains = ("jszyapi.com", "jisuzy.com")
    api_from = "jsm3u8"
    priority = 59


class SuboChannel(MaccmsChannel):
    """速播资源 — subozy.com family (verified playable 2026-08-13, xluuss CDN)."""

    id = "subozy"
    name = "速播资源"
    description = "AppleCMS 直链 HLS 资源站（速播资源）"
    domains = ("subocaiji.com", "subozy.com", "suboziyuan.com", "suboziyuan.net")
    api_from = "subm3u8"
    priority = 59


class BaofengChannel(MaccmsChannel):
    """暴风资源 — bfzyapi.com (verified playable 2026-08-13, rrcdnbf5/baofeng9 CDN).

    The CDN requires a Chrome TLS fingerprint (curl_cffi chrome124); the
    stream proxy routes these hosts through the fingerprint path (§2.8).
    """

    id = "bfzyapi"
    name = "暴风资源"
    description = "AppleCMS 直链 HLS 资源站（暴风资源）"
    domains = ("bfzyapi.com",)
    api_from = "bfzym3u8"
    priority = 59


class FeifanChannel(MaccmsChannel):
    """非凡资源 — ffzy.tv family (verified playable 2026-08-13, ffzy-plays CDN).

    Same Chrome-fingerprint CDN requirement as 暴风资源 (§2.8).
    """

    id = "ffzy"
    name = "非凡资源"
    description = "AppleCMS 直链 HLS 资源站（非凡资源）"
    domains = ("ffzy.tv", "ffzy1.tv", "ffzy2.tv", "ffzy3.tv", "ffzy4.tv", "ffzy5.tv")
    api_from = "ffm3u8"
    priority = 59
