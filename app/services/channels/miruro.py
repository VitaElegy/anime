"""Miruro channel — playable HLS backup source (AniList + Miruro pipe).

Miruro (miruro.tv) is an open-source frontend. Its metadata comes from AniList
GraphQL (open, no Cloudflare), while episodes and streams come from Miruro's own
``/api/secure/pipe`` endpoint (Cloudflare-gated). The pipe REQUIRES a Chrome TLS
fingerprint (curl_cffi ``impersonate="chrome110"``), so this provider is an
**explicit documented exception** to CHANNEL_ARCHITECTURE §1.1 "providers must
not create their own HTTP client" — declared first in
docs/RESOURCE_BACKUP_PLAN.md §2.5 before implementation.

Reference implementation studied (independent implementation — only endpoints /
payload shapes are referenced):
    ~/work/Project/_reference/Miruro-API (walterwhite-69/Miruro-API v3.0)

Verified playable 2026-08-13: pewe provider -> hls.anidb.app HLS
(1080/720/360, real MPEG-TS segments, Referer https://anidb.app/).
Chinese keywords are expanded to English/romaji by the registry before search
(docs/CHANNEL_ARCHITECTURE.md §1.2).
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import re

from curl_cffi.requests import AsyncSession  # documented exception (docs §2.5)

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

ANILIST_URL = "https://graphql.anilist.co"
PIPE_URL = "https://www.miruro.tv/api/secure/pipe"
PIPE_TIMEOUT = 15.0

#: Miruro provider preference order. pewe (AniDBApp HLS) verified 2026-08-13;
#: ally (Animedao upstream) returns 444/502 and is deliberately last.
PROVIDER_PREFERENCE = ("pewe", "bee", "kiwi", "hop", "bonk", "moo", "ally")

#: Expose at most this many provider groups in the episode picker (frontend
#: renders one section per group natively — gives the user redundancy without
#: flooding the UI with 7 identical episode lists).
MAX_GROUPS = 3

SEARCH_GQL = """
query ($search: String, $page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
      id
      title { romaji english native }
      coverImage { large extraLarge }
      format
      episodes
      averageScore
      seasonYear
    }
  }
}
"""

#: Full browser header set required to pass Cloudflare on the pipe endpoint
#: (mirrors what the Miruro web player sends; sec-fetch / sec-ch-ua matter).
PIPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.miruro.tv/",
    "Origin": "https://www.miruro.tv",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "cors",
    "sec-fetch-dest": "empty",
    "sec-ch-ua": '"Chromium";v="110", "Not A(Brand";v="24", "Google Chrome";v="110"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

_EPISODE_NUM_RE = re.compile(r"episode\s*(\d+)", re.I)


def _b64url(data: bytes) -> str:
    """URL-safe base64 without padding (Miruro pipe encoding)."""
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _decode_episode_id(raw: str) -> str:
    """Decode a pipe episode id (base64url of ``upstream:realId:number``)."""
    try:
        padded = raw + "=" * (4 - len(raw) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode()
    except Exception:
        return raw
    return decoded if ":" in decoded else raw


def _decode_pipe_response(encoded: str) -> dict:
    """Decode a pipe response (gzip + base64url JSON)."""
    try:
        padded = encoded + "=" * (4 - len(encoded) % 4)
        compressed = base64.urlsafe_b64decode(padded)
        return json.loads(gzip.decompress(compressed).decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"failed to decode pipe response: {exc}") from exc


class MiruroChannel(ChannelProvider):
    """Miruro — AniList search + pipe episodes/streams (playable HLS)."""

    id = "miruro"
    name = "Miruro"
    language = "en"
    description = "AniList 元数据 + AniDB HLS 可播（需绕 Cloudflare）"
    priority = 58  # playable backup: after AnimeHeaven (55), before Kitsu (60)

    @staticmethod
    async def _pipe(stage: str, payload: dict) -> dict:
        """Call the Miruro secure pipe (documented curl_cffi exception, §2.5).

        The pipe sits behind Cloudflare: only a Chrome TLS fingerprint gets
        through, so we use curl_cffi here instead of the shared httpx client.
        """
        encoded = _b64url(json.dumps(payload, separators=(",", ":")).encode())
        kwargs: dict = {
            "impersonate": "chrome110",
            "headers": PIPE_HEADERS,
            "timeout": PIPE_TIMEOUT,
        }
        if settings.HTTP_PROXY:
            kwargs["proxies"] = {
                "http": settings.HTTP_PROXY,
                "https": settings.HTTP_PROXY,
            }
        try:
            async with AsyncSession(**kwargs) as client:
                resp = await client.get(f"{PIPE_URL}?e={encoded}")
            if resp.status_code != 200:
                raise ChannelError("miruro", stage, f"pipe http {resp.status_code}")
            return _decode_pipe_response(resp.text.strip())
        except ChannelError:
            raise
        except Exception as exc:
            raise ChannelError("miruro", stage, str(exc)) from exc

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        resp = await http.request(
            self.id,
            "search",
            "POST",
            ANILIST_URL,
            json_body={
                "query": SEARCH_GQL,
                "variables": {"search": keyword, "page": page, "perPage": 20},
            },
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ChannelError(self.id, "search", f"invalid json: {exc}") from exc
        media = ((payload or {}).get("data") or {}).get("Page") or {}
        out: list[ChannelSearchResult] = []
        for item in media.get("media") or []:
            aid = item.get("id")
            if aid is None:
                continue
            titles = item.get("title") or {}
            romaji = titles.get("romaji") or ""
            english = titles.get("english") or ""
            native = titles.get("native") or ""
            title = english or romaji or native
            if not title:
                continue
            cover = (item.get("coverImage") or {}).get("large") or ""
            if not cover:
                cover = (item.get("coverImage") or {}).get("extraLarge") or ""
            out.append(
                ChannelSearchResult(
                    channel=self.id,
                    title=title,
                    title_original=romaji or native,
                    cover_url=cover,
                    year=str(item.get("seasonYear") or ""),
                    detail_ref=str(aid),
                    extra={
                        "format": item.get("format") or "",
                        "episodes": item.get("episodes"),
                        "averageScore": item.get("averageScore"),
                    },
                )
            )
        return out

    async def get_detail(self, detail_ref: str) -> ChannelDetail:
        try:
            aid = int(detail_ref)
        except (TypeError, ValueError):
            raise ChannelError(
                self.id, "detail", f"invalid anilist id: {detail_ref!r}", retryable=False
            ) from None
        data = await self._pipe(
            "detail",
            {
                "path": "episodes",
                "method": "GET",
                "query": {"anilistId": aid},
                "body": None,
                "version": "0.1.0",
            },
        )
        providers = data.get("providers") or {}
        groups: list[ChannelEpisodeGroup] = []
        for pname in PROVIDER_PREFERENCE:
            if len(groups) >= MAX_GROUPS:
                break
            provider = providers.get(pname) or {}
            episodes = ((provider.get("episodes") or {}).get("sub")) or []
            if not episodes:
                continue
            items: list[ChannelEpisode] = []
            for ep in sorted(episodes, key=lambda e: e.get("number") or 0):
                number = ep.get("number")
                title = str(ep.get("title") or "").strip()
                raw_id = str(ep.get("id") or "")
                decoded = _decode_episode_id(raw_id)
                ep_title = f"第 {number} 集"
                # Skip generic "Episode N" titles (redundant with the number).
                if title and not _EPISODE_NUM_RE.fullmatch(title):
                    ep_title += f" · {title}"
                items.append(
                    ChannelEpisode(
                        title=ep_title,
                        episode_ref=f"{pname}:sub:{aid}:{decoded}",
                        extra={"number": number},
                    )
                )
            groups.append(ChannelEpisodeGroup(title=f"{pname} · 字幕", episodes=items))
        return ChannelDetail(channel=self.id, groups=groups)

    async def get_streams(self, episode_ref: str) -> list[ChannelStream]:
        # episode_ref = f"{provider}:{category}:{anilist_id}:{decoded_id}" (§2.5)
        head, _, rest = episode_ref.partition(":")
        if not head or ":" not in rest:
            raise ChannelError(
                self.id, "streams", f"malformed episode_ref: {episode_ref!r}", retryable=False
            )
        category, _, tail = rest.partition(":")
        try:
            aid_s, decoded_id = tail.split(":", 1)
            aid = int(aid_s)
        except (TypeError, ValueError):
            raise ChannelError(
                self.id, "streams", f"malformed episode_ref: {episode_ref!r}", retryable=False
            ) from None
        data = await self._pipe(
            "streams",
            {
                "path": "sources",
                "method": "GET",
                "query": {
                    "episodeId": _b64url(decoded_id.encode()),
                    "provider": head,
                    "category": category,
                    "anilistId": aid,
                },
                "body": None,
                "version": "0.1.0",
            },
        )
        streams = data.get("streams") or []
        hls = [s for s in streams if (s.get("type") or "") == "hls"]
        if not hls:
            raise ChannelError(self.id, "streams", "no playable hls stream")
        # Prefer the verified AniDBApp HLS host, then any HLS.
        preferred = [s for s in hls if "anidb.app" in str(s.get("url") or "")]
        picked = (preferred or hls)[0]
        url = str(picked.get("url") or "")
        if not url:
            raise ChannelError(self.id, "streams", "empty hls url")
        referer = str(picked.get("referer") or "https://anidb.app/")
        return [
            ChannelStream(
                type="hls",
                url=url,
                headers={"Referer": referer, "User-Agent": http.DEFAULT_UA},
                note=f"Miruro · {head}",
            )
        ]
