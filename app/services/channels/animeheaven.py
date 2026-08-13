"""AnimeHeaven channel — playable mp4 backup source (no Cloudflare).

AnimeHeaven is a free English-index anime site that serves direct mp4 links:
- search: GET /fastsearch.php?xhr=1&s=<keyword>  -> HTML anchors /anime.php?<id>
- detail: GET /anime.php?<id>                    -> title/cover/desc + gate keys
- streams: GET /gate.php with Cookie key=<episode_ref> + Referer
             -> <video><source src='.../video.mp4?<key>&<token>' type='video/mp4'>

Verified playable 2026-08-13 (range GET 206, real MP4; HEAD hangs -> use Range).
Endpoint/selector shape referenced from
~/work/Project/_reference/Anivault-Scraper/src/scrapers/animeheaven.ts (SH0MIK);
this is an independent implementation — only endpoints/selectors are referenced.
Chinese keywords are expanded to English/romaji by the registry before search
(docs/CHANNEL_ARCHITECTURE.md §1.2).
"""

from __future__ import annotations

import html
import logging
import re

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

BASE = "https://animeheaven.me"
TITLE_SUFFIX = " Anime | AnimeHeaven.Me"

#: Search result anchors: <a class='ac' href='/anime.php?<id>'>...</a>
_SEARCH_ANCHOR_RE = re.compile(
    r"""<a[^>]+href=['"](?:https?://[^'"]*)?/anime\.php\?([a-zA-Z0-9]+)['"][^>]*>(.*?)</a>""",
    re.S,
)
_FASTNAME_RE = re.compile(r"class=['\"]fastname['\"]>([^<]*)<", re.S)
_IMG_ALT_RE = re.compile(r"<img[^>]*alt=['\"]([^'\"]*)['\"]", re.S)
_IMG_SRC_RE = re.compile(r"<img[^>]*src=['\"]([^'\"]*)['\"]", re.S)

_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.S)
_POSTER_RE = re.compile(r"class=['\"]posterimg['\"][^>]*src=['\"]([^'\"]+)['\"]")
_DESC_RE = re.compile(r"infodes c['\"]>(.*?)</div>", re.S)

#: Episode anchors: <a ... onmouseover='gateh("<key>")' onclick='gatea("<key>")'
#: href='gate.php'> ... <div class=' watch2 bc '>28</div> ...
_EPISODE_RE = re.compile(
    r"""<a[^>]*gate[ha]\(['\"]([a-f0-9]+)['\"]\)[^>]*>.*?class=['\"]\s*watch2\s+bc\s*['\"]>(\d+)</div>""",
    re.S,
)

#: Stream sources inside gate.php: <source src='https://ct.../video.mp4?...'
_SOURCE_RE = re.compile(r"<source src=['\"]([^'\"]+)['\"]\s+type=['\"]video/mp4['\"]", re.S)


class AnimeHeavenChannel(ChannelProvider):
    """AnimeHeaven — English index, direct mp4 (no CF, no decryption)."""

    id = "animeheaven"
    name = "AnimeHeaven"
    language = "en"
    description = "英文索引 + 直链 mp4（无 Cloudflare）"
    priority = 55  # playable backup: before Kitsu (60) in the channel tab

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

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        resp = await http.request(
            self.id,
            "search",
            "GET",
            f"{BASE}/fastsearch.php",
            params={"xhr": 1, "s": keyword},
            headers={"User-Agent": http.DEFAULT_UA, "Accept": "text/html,*/*"},
        )
        body = resp.text
        out: list[ChannelSearchResult] = []
        for m in _SEARCH_ANCHOR_RE.finditer(body):
            aid = m.group(1)
            inner = m.group(2)
            name = _FASTNAME_RE.search(inner)
            if name:
                title = self._text(name.group(1))
            else:
                alt = _IMG_ALT_RE.search(inner)
                title = self._text(alt.group(1)) if alt else ""
            if not title:
                continue
            cover = ""
            img = _IMG_SRC_RE.search(inner)
            if img:
                cover = self._abs(self._text(img.group(1)))
            out.append(
                ChannelSearchResult(
                    channel=self.id,
                    title=title,
                    title_original=title,
                    cover_url=cover,
                    detail_ref=aid,
                )
            )
        return out

    async def get_detail(self, detail_ref: str) -> ChannelDetail:
        # AnimeHeaven reads the id from the query string, not a named param:
        # /anime.php?<id>. Build the URL directly to avoid percent-encoding.
        resp = await http.request(
            self.id,
            "detail",
            "GET",
            f"{BASE}/anime.php?{detail_ref}",
            headers={"User-Agent": http.DEFAULT_UA, "Accept": "text/html,*/*"},
        )
        body = resp.text

        title_m = _TITLE_RE.search(body)
        title = self._text(title_m.group(1).replace(TITLE_SUFFIX, "")) if title_m else ""
        if not title:
            raise ChannelError(self.id, "detail", "no title in page", retryable=False)

        poster_m = _POSTER_RE.search(body)
        cover = self._abs(self._text(poster_m.group(1))) if poster_m else ""
        desc_m = _DESC_RE.search(body)
        desc = self._text(desc_m.group(1)) if desc_m else ""

        episodes: list[tuple[int, str]] = []
        for em in _EPISODE_RE.finditer(body):
            key, num = em.group(1), int(em.group(2))
            if (num, key) not in episodes:
                episodes.append((num, key))
        episodes.sort(key=lambda item: item[0])

        group = ChannelEpisodeGroup(
            title="AnimeHeaven",
            episodes=[
                ChannelEpisode(title=f"第{num}集", episode_ref=key)
                for num, key in episodes
            ],
        )
        return ChannelDetail(
            channel=self.id,
            title=title,
            cover_url=cover,
            description=desc[:500],
            groups=[group] if group.episodes else [],
        )

    async def get_streams(self, episode_ref: str) -> list[ChannelStream]:
        resp = await http.request(
            self.id,
            "streams",
            "GET",
            f"{BASE}/gate.php",
            headers={
                "User-Agent": http.DEFAULT_UA,
                "Referer": f"{BASE}/",
                "Accept": "text/html,*/*",
                "Cookie": f"key={episode_ref}",
            },
        )
        body = resp.text
        sources = [self._text(s) for s in _SOURCE_RE.findall(body)]
        if not sources:
            raise ChannelError(self.id, "streams", "no video source in gate page", retryable=False)
        primary = next((s for s in sources if "/video.mp4" in s), sources[0])
        return [
            ChannelStream(
                type="mp4",
                url=primary,
                format="mp4",
                headers={"User-Agent": http.DEFAULT_UA, "Referer": f"{BASE}/"},
                note="AnimeHeaven",
            )
        ]
