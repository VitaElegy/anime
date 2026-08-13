"""AnimeXin channel — playable donghua backup source (WordPress + Dailymotion HLS).

AnimeXin (animexin.dev, formerly animexin.vip) is a donghua (Chinese animation)
WordPress site using the AnimeStream template. Search/detail/episode pages are
plain HTML served without Cloudflare, so the shared httpx client works. The
embedded players are mostly Dailymotion, whose HLS master requires a Chrome TLS
fingerprint (curl_cffi ``impersonate="chrome124"``) — declared as a documented
exception to CHANNEL_ARCHITECTURE §1.1 first in docs/RESOURCE_BACKUP_PLAN.md §2.6
before this implementation (same pattern as Miruro §2.5).

Verified playable 2026-08-13 (via Clash 7892): embed page -> dmInternalData
ts/v1st -> player/metadata -> qualities.auto[0].url (HLS master, four quality
variants; segments under vod*.cf.dmcdn.net).

Endpoint/selector shape referenced from
~/work/Project/_reference/aniyomi-extensions-archive (Apache-2.0):
    lib-multisrc/animestream  +  src/all/animexin
This is an independent implementation — only endpoints/selectors are referenced,
no code is copied.
"""

from __future__ import annotations

import html
import logging
import re
from urllib.parse import urlencode

from curl_cffi.requests import AsyncSession  # documented exception (docs §2.6)

from app.config import settings
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

BASE = "https://animexin.dev"
SEARCH_URL = f"{BASE}/page/1/"

#: Documented timeout exception (§2.6): detail/episode/embed pages are
#: 300–750KB and the shared 8s httpx timeout is not enough. The shared client
#: stays in use — only this request's timeout is raised via http.request().
SLOW_TIMEOUT = 20.0

DM_EMBED_BASE = "https://www.dailymotion.com/embed/video/"
DM_REFERER = "https://www.dailymotion.com/"
DM_ORIGIN = "https://www.dailymotion.com"
DM_METADATA_BASE = "https://www.dailymotion.com/player/metadata/video/"

#: Search result cards: <div class="listupd"><article class="bs">
#: <a href="https://animexin.dev/<slug>/" class="tip" title="Title">
#:   <img class="ts-post-image" src="..." title="...">
#: </a></article></div>
_TIP_ANCHOR_RE = re.compile(
    r"""<a\b(?=[^>]*class=['"][^'"]*\btip\b)[^>]*href=['"]([^'"]+)['"][^>]*>(.*?)</a>""",
    re.S,
)
_TITLE_ATTR_RE = re.compile(r"""\btitle=['"]([^'"]+)['"]""", re.S)
_IMG_RE = re.compile(r"""<img\b[^>]*\bsrc=['"]([^'"]+)['"]""", re.S)
_IMG_TITLE_RE = re.compile(r"""<img\b[^>]*\b(?:alt|title)=['"]([^'"]+)['"]""", re.S)

_PAGE_TITLE_RE = re.compile(r"<title>\s*([^<]*?)\s*</title>", re.S)
_TITLE_SUFFIX_RE = re.compile(r"\s*[-–—|]\s*AnimeXin\s*$", re.I)
#: Chinese title on the detail page: <span class="alter">无上神帝</span>
_CHINESE_TITLE_RE = re.compile(
    r"""<span[^>]*class=['"][^'"]*\balter\b[^'"]*['"][^>]*>\s*([^<]+?)\s*</span>""", re.S
)
_COVER_RE = re.compile(
    r"""<div[^>]*class=['"][^'"]*\bthumb\b[^'"]*['"][^>]*>\s*<img[^>]*src=['"]([^'"]+)['"]""",
    re.S,
)
_DESC_RE = re.compile(
    r"""<div[^>]*class=['"][^'"]*\bentry-content\b[^'"]*['"][^>]*>(.*?)</div>""", re.S
)
_MINDESC_RE = re.compile(
    r"""<div[^>]*class=['"][^'"]*\bmindesc\b[^'"]*['"][^>]*>(.*?)</div>""", re.S
)

#: Episode anchors: <a href="https://animexin.dev/<slug>-episode-626-.../">
#:   <div class="epl-num">626</div><div class="epl-title">Episode 626</div></a>
_EPISODE_RE = re.compile(
    r"""<a[^>]+href=['"]([^'"]+)['"][^>]*>.*?<div[^>]*class=['"][^'"]*\bepl-num\b[^'"]*['"][^>]*>\s*(\d+)\s*</div>""",
    re.S,
)
_EP_TITLE_RE = re.compile(
    r"""<div[^>]*class=['"][^'"]*\bepl-title\b[^'"]*['"][^>]*>\s*(.*?)\s*</div>""", re.S
)
_EP_NUM_RE = re.compile(r"episode\s*\d+", re.I)

_IFRAME_RE = re.compile(r"""<iframe[^>]+src=['"]([^'"]+)['"]""", re.S)
_DM_EMBED_RE = re.compile(r"^https?://(?:www\.)?dailymotion\.com/embed/video/([A-Za-z0-9_-]+)")
#: Dailymotion embed page carries dmInternalData with the signed ts/v1st tokens.
_TS_RE = re.compile(r'"ts"\s*:\s*(\d+)')
_V1ST_RE = re.compile(r'"v1st"\s*:\s*"([^"]+)"')

_TAG_RE = re.compile(r"<[^>]+>")


class AnimeXinChannel(ChannelProvider):
    """AnimeXin — donghua WordPress site + Dailymotion HLS (playable backup)."""

    id = "animexin"
    name = "AnimeXin"
    language = "en"
    description = "国漫/多语言字幕 + Dailymotion HLS 可播"
    priority = 56  # playable backup: after AnimeHeaven (55), before Miruro (58)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _abs(path: str) -> str:
        if not path:
            return ""
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{BASE}{path}" if path.startswith("/") else f"{BASE}/{path}"

    @staticmethod
    def _text(raw: str) -> str:
        return html.unescape(raw).strip()

    @classmethod
    def _strip_tags(cls, raw: str) -> str:
        text = _TAG_RE.sub(" ", raw)
        return " ".join(text.split())

    @classmethod
    def _synopsis(cls, body: str) -> str:
        """Extract the synopsis (.entry-content first, .mindesc fallback)."""
        raw = ""
        m = _DESC_RE.search(body)
        if m:
            raw = m.group(1)
        if len(cls._strip_tags(raw)) < 30:
            m2 = _MINDESC_RE.search(body)
            if m2:
                raw = m2.group(1)
        return cls._text(cls._strip_tags(raw))[:1000]

    # ------------------------------------------------------------------- search

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        resp = await http.request(
            self.id,
            "search",
            "GET",
            SEARCH_URL,
            params={"s": keyword},
            headers={"User-Agent": http.DEFAULT_UA, "Accept": "text/html,*/*"},
        )
        body = resp.text
        out: list[ChannelSearchResult] = []
        for m in _TIP_ANCHOR_RE.finditer(body):
            href = m.group(1)
            inner = m.group(2)
            title = ""
            tm = _TITLE_ATTR_RE.search(m.group(0))
            if tm:
                title = self._text(tm.group(1))
            if not title:
                im = _IMG_TITLE_RE.search(inner)
                if im:
                    title = self._text(im.group(1))
            if not title:
                continue
            cover = ""
            img = _IMG_RE.search(inner)
            if img:
                cover = self._abs(self._text(img.group(1)))
            out.append(
                ChannelSearchResult(
                    channel=self.id,
                    title=title,
                    title_original=title,
                    cover_url=cover,
                    detail_ref=self._abs(href),
                )
            )
        return out

    # ------------------------------------------------------------------- detail

    async def get_detail(self, detail_ref: str) -> ChannelDetail:
        if not detail_ref.startswith(("http://", "https://")):
            detail_ref = self._abs(detail_ref)
        resp = await http.request(
            self.id,
            "detail",
            "GET",
            detail_ref,
            timeout=SLOW_TIMEOUT,  # documented exception (§2.6)
            headers={"User-Agent": http.DEFAULT_UA, "Accept": "text/html,*/*"},
        )
        body = resp.text

        page_title = ""
        tm = _PAGE_TITLE_RE.search(body)
        if tm:
            page_title = _TITLE_SUFFIX_RE.sub("", self._text(tm.group(1))).strip()
        if not page_title:
            raise ChannelError(self.id, "detail", "no title in page", retryable=False)

        cn_title = ""
        cm = _CHINESE_TITLE_RE.search(body)
        if cm:
            cn_title = self._text(cm.group(1))
        title = cn_title or page_title

        cover = ""
        cov = _COVER_RE.search(body)
        if cov:
            cover = self._abs(self._text(cov.group(1)))

        desc = self._synopsis(body)
        if cn_title and cn_title != page_title:
            prefix = f"英文名：{page_title}"
            desc = f"{prefix}\n\n{desc}".strip() if desc else prefix

        episodes: list[tuple[int, ChannelEpisode]] = []
        seen: set[tuple[int, str]] = set()
        for em in _EPISODE_RE.finditer(body):
            href = em.group(1)
            try:
                num = int(em.group(2))
            except ValueError:
                continue
            abs_href = self._abs(href)
            # Skip malformed anchors (e.g. a trailing <li> whose <a> points at
            # the site root instead of an episode page — seen on SGE ep 630).
            if abs_href.rstrip("/") == BASE or href in ("", "#"):
                continue
            if (num, abs_href) in seen:
                continue
            seen.add((num, abs_href))
            ep_title = f"第{num}集"
            et = _EP_TITLE_RE.search(em.group(0))
            if et:
                extra = self._text(et.group(1))
                if extra and not _EP_NUM_RE.fullmatch(extra):
                    ep_title += f" · {extra}"
            episodes.append(
                (
                    num,
                    ChannelEpisode(
                        title=ep_title,
                        episode_ref=abs_href,
                        extra={"number": num},
                    ),
                )
            )
        episodes.sort(key=lambda item: item[0])

        group = ChannelEpisodeGroup(
            title="AnimeXin",
            episodes=[ep for _, ep in episodes],
        )
        return ChannelDetail(
            channel=self.id,
            title=title,
            cover_url=cover,
            description=desc[:1000],
            groups=[group] if group.episodes else [],
        )

    # ------------------------------------------------------------------ streams

    async def get_streams(self, episode_ref: str) -> list[ChannelStream]:
        if not episode_ref.startswith(("http://", "https://")):
            raise ChannelError(
                self.id, "streams", f"malformed episode_ref: {episode_ref!r}", retryable=False
            )
        resp = await http.request(
            self.id,
            "streams",
            "GET",
            episode_ref,
            timeout=SLOW_TIMEOUT,  # documented exception (§2.6)
            headers={"User-Agent": http.DEFAULT_UA, "Accept": "text/html,*/*"},
        )
        body = resp.text
        embed = next((s for s in _IFRAME_RE.findall(body) if s.startswith("http")), "")
        if not embed:
            raise ChannelError(self.id, "streams", "no embed iframe in episode page", retryable=False)
        dm = _DM_EMBED_RE.search(embed)
        if not dm:
            # v1 scope (§2.6): dood/gdriveplayer/youtube/ok.ru embeds are not
            # implemented — surface the official embed URL for the frontend.
            raise ChannelError(
                self.id,
                "streams",
                f"unsupported embed for v1: {embed}",
                retryable=False,
            )
        master = await self._dm_master(dm.group(1))
        return [
            ChannelStream(
                type="hls",
                url=master,
                headers={
                    "Referer": DM_REFERER,
                    "Origin": DM_ORIGIN,
                    "User-Agent": http.DEFAULT_UA,
                },
                note="AnimeXin · Dailymotion",
            )
        ]

    @staticmethod
    def _dm_tokens(embed_html: str) -> tuple[str, str] | None:
        """Extract (ts, v1st) from the Dailymotion embed page dmInternalData."""
        ts = _TS_RE.search(embed_html)
        v1st = _V1ST_RE.search(embed_html)
        if not ts or not v1st:
            return None
        return ts.group(1), v1st.group(1)

    async def _dm_master(self, video_id: str) -> str:
        """Resolve the Dailymotion HLS master (documented curl_cffi exception §2.6).

        Only a Chrome TLS fingerprint gets past Dailymotion's CDN (system curl /
        LibreSSL fails the handshake; newer Chrome fingerprints are 403'd), so
        this helper uses curl_cffi with ``impersonate="chrome124"``.
        """
        kwargs: dict = {
            "impersonate": "chrome124",
            "timeout": SLOW_TIMEOUT,
            "headers": {
                "User-Agent": http.DEFAULT_UA,
                "Accept": "text/html,*/*",
            },
        }
        if settings.HTTP_PROXY:
            kwargs["proxies"] = {"http": settings.HTTP_PROXY, "https": settings.HTTP_PROXY}
        try:
            async with AsyncSession(**kwargs) as client:
                embed_resp = await client.get(f"{DM_EMBED_BASE}{video_id}")
                embed_resp.raise_for_status()
                tokens = self._dm_tokens(embed_resp.text)
                if tokens is None:
                    raise ChannelError(self.id, "streams", f"no dm ts/v1st for {video_id}")
                ts, v1st = tokens
                query = urlencode(
                    {"locale": "en-US", "dmV1st": v1st, "dmTs": ts, "is_native_app": 0}
                )
                meta_resp = await client.get(
                    f"{DM_METADATA_BASE}{video_id}?{query}",
                    headers={
                        "Referer": DM_REFERER,
                        "Origin": DM_ORIGIN,
                        "Accept": "application/json",
                    },
                )
                meta_resp.raise_for_status()
                payload = meta_resp.json()
            qualities = (payload or {}).get("qualities") or {}
            auto = qualities.get("auto") or []
            if not auto or not auto[0].get("url"):
                raise ChannelError(self.id, "streams", f"no auto quality in dm metadata for {video_id}")
            return str(auto[0]["url"])
        except ChannelError:
            raise
        except Exception as exc:
            raise ChannelError(self.id, "streams", f"dailymotion extract failed: {exc}") from exc
