"""Anikoto channel — playable HLS backup source (HiAnime/Zoro-style clone).

Anikoto (anikoto.net) is a HiAnime/Zoro-style clone. Search/detail/episode
pages are plain HTML served without Cloudflare, so the shared httpx client
works (through the configured HTTP proxy).

Stream chain (verified live 2026-08-13 via Clash 7892):
- server list:   GET /ajax/server/list?servers=<data-ids>  -> <li data-sv-id data-link-id>
- embed resolve: GET /ajax/server?get=<link-id>&sv=<sv-id> -> { "result": { "url": embed } }
- embed hosts:
  * megaplay.buzz / vidwish.live / megacloud.bloggy.click -> megaplay getSources API
  * vidtube.site                                          -> megaplay-style getSources API
  * megacloud.blog                                        -> megacloud getSources (+_k nonce)
- CDNs are all real HLS:
  * megaplay: master -> child -> segments are MPEG-TS wrapped in a 252-byte
    PNG/junk prefix on tiktokcdn.com; our stream proxy strips the prefix
    (SegmentStrip, watch.py) so this source is playable.
  * vidtube -> s1.akirax.buzz / s1.norami.top: segments are raw MPEG-TS
    served with a .jpg suffix (verified `47 40 11 10` magic).
- A "Kiwi Mapper" side-channel keyed by MAL id returns either a real anikoto
  server code (resolveable via /ajax/server?get=, HLS behind kwik.cx2) or
  pahe.nekostream.site click-through download shortlinks (not automatable
  without JS). We use the server-code path as a last-resort fallback only.

Endpoint/selector shape referenced from
~/work/Project/_reference/Anivault-Scraper/src/scrapers/anikoto.ts (SH0MIK;
repo declares no License — this is an independent implementation, only
endpoints/selectors are referenced, no code copied). Live probing showed the
current site uses different search-result selectors than that reference
(.ani.items .item / a.name.d-title instead of flw-item), so the selectors
here come from the live 2026-08-13 capture.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import re
from urllib.parse import urljoin

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

BASE = "https://anikoto.net"

#: Chrome 124 UA + header set matching anikoto-API's DEFAULT_HEADERS (avoids
#: fingerprint-based failures; verified live).
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HTML_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

KIWI_MAPPER_URLS = (
    "https://mapper.nekostream.site/api/mal",
    "https://mapper.mewcdn.online/api/mal",
)

# ---------------------------------------------------------------------------
# Search page (/filter?keyword=) — live structure:
#   <div id="list-items" class="ani items">
#     <div class="item ">
#       <div class="inner">
#         <div class="ani poster tip"><a href="https://anikoto.net/watch/<slug>/ep-1">
#           <img src="https://cdn.anipixcdn.co/thumbnail/<hash>.jpg" alt="...">
#         ...
#         <a class="name d-title" href="https://anikoto.net/watch/<slug>/ep-1"
#            data-jp="Sousou no Frieren">Frieren: Beyond Journey's End</a>
# ---------------------------------------------------------------------------
_ITEM_SPLIT_RE = re.compile(r'<div class="item\s*">')
_NAME_ANCHOR_RE = re.compile(
    r"""<a\b(?=[^>]*class=['"][^'"]*\bname\b[^'"]*\bd-title\b)[^>]*href=['"]([^'"]+)['"][^>]*>""",
    re.S,
)
_JP_TITLE_RE = re.compile(r"""data-jp=['"]([^'"]*)['"]""", re.S)
_IMG_SRC_RE = re.compile(r"""<img\b[^>]*\bsrc=['"]([^'"]+)['"]""", re.S)
_IMG_ALT_RE = re.compile(r"""<img\b[^>]*\balt=['"]([^'"]*)['"]""", re.S)
_WATCH_HREF_RE = re.compile(r"""href=['"]([^'"]*/watch/[^'"]+)['"]""", re.S)
_SLUG_RE = re.compile(r"/watch/([^/]+)")

# ---------------------------------------------------------------------------
# Watch page (/watch/<slug>)
# ---------------------------------------------------------------------------
_PAGE_TITLE_RE = re.compile(r"<title>\s*([^<]*?)\s*</title>", re.S)
_TITLE_SUFFIX_RE = re.compile(r"\s*(?:Watch\s+)?Online in HD(?:\s*-\s*Anikoto)?\s*$", re.I)
_H1_TITLE_RE = re.compile(r"""<h1\b[^>]*itemprop=['"]name['"][^>]*>(.*?)</h1>""", re.S)
_OG_IMAGE_RE = re.compile(
    r"""<meta\b[^>]*property=['"]og:image['"][^>]*content=['"]([^'"]+)['"]""", re.S
)
_OG_IMAGE_REV_RE = re.compile(
    r"""<meta\b[^>]*content=['"]([^'"]+)['"][^>]*property=['"]og:image['"]""", re.S
)
_POSTER_IMG_RE = re.compile(r"""itemprop=['"]image['"][^>]*src=['"]([^'"]+)['"]""", re.S)
_SYNOPSIS_RE = re.compile(
    r"""class=['"]synopsis\b[^'"]*['"][^>]*>.*?class=['"]content['"]>(.*?)</div>""", re.S
)
_WATCH_MAIN_ID_RE = re.compile(r"""id=['"]watch-main['"][^>]*data-id=['"]([^'"]+)['"]""", re.S)
_TAG_RE = re.compile(r"<[^>]+>")

# Inline episode anchors: <a href="#" data-id data-num data-slug data-mal ...>
_INLINE_EP_ANCHOR_RE = re.compile(r"""<a\b[^>]*\bhref=['"][^'"]*['"][^>]*\bdata-num=['"][^'"]+['"][^>]*>""", re.S)

# Episode list AJAX (/ajax/episode/list/<id>) — live structure:
#   <li title="The Journey's End" data-html="true">
#     <a href="#" data-id="97908" data-num="1" data-slug="1" data-mal="52991"
#        data-timestamp="1729242913" data-sub="1" data-dub="1"
#        data-ids="SURL..." class="active"><b>1</b>
#        <span class="d-title" data-jp="Bōken no Owari">The Journey's End</span>
#        <i></i></a>
_EP_ANCHOR_RE = re.compile(r"""<a\b[^>]*\bdata-num=['"][^'"]+['"][^>]*>.*?</a>""", re.S)
_EP_TITLE_RE = re.compile(r"""class=['"]d-title['"][^>]*>\s*(.*?)\s*</span>""", re.S)

# ---------------------------------------------------------------------------
# Server list AJAX (/ajax/server/list?servers=) — live structure:
#   <li data-ep-id="97908" data-cmid="animixplay-fqsqfvdf4u" data-sv-id="e54"
#       data-link-id="MTF1...">Vidstream-2</li>
# ---------------------------------------------------------------------------
_SERVER_LI_RE = re.compile(r"""<li\b[^>]*>.*?</li>""", re.S)

# Megaplay / VidTube embed page: <title>File 13461 - MegaPlay</title>
_MEGAPLAY_ID_RE = re.compile(r"<title>File\s+([0-9]+)", re.I)
_IFRAME_SRC_RE = re.compile(r"""<iframe\b[^>]*\bsrc=['"]([^'"]+)['"]""", re.S)

# Megacloud embed page: nonce is the first 48-char alnum token in the HTML.
_NONCE_48_RE = re.compile(r"\b[a-zA-Z0-9]{48}\b")


def _attr(tag: str, name: str) -> str:
    m = re.search(rf"""\b{re.escape(name)}=['"]([^'"]*)['"]""", tag)
    return m.group(1) if m else ""


class AnikotoChannel(ChannelProvider):
    """Anikoto — HiAnime/Zoro-style clone, HLS backup source (EN index)."""

    id = "anikoto"
    name = "Anikoto"
    language = "en"
    description = "英文索引 + HLS 可播（megaplay/vidtube 双 CDN）"
    priority = 57  # playable backup: after AnimeXin (56), before Miruro (58)

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
    def _slug_from_url(cls, url: str) -> str:
        m = _SLUG_RE.search(url)
        if not m:
            return ""
        return m.group(1).rstrip("/")

    # ------------------------------------------------------------------- search

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        resp = await http.request(
            self.id,
            "search",
            "GET",
            f"{BASE}/filter",
            params={"keyword": keyword},
            headers=HTML_HEADERS,
        )
        body = resp.text
        out: list[ChannelSearchResult] = []
        # Split the page into item blocks so cover + name stay paired.
        chunks = _ITEM_SPLIT_RE.split(body)[1:]
        for chunk in chunks:
            name_m = _NAME_ANCHOR_RE.search(chunk)
            href = name_m.group(1) if name_m else ""
            if not href:
                wm = _WATCH_HREF_RE.search(chunk)
                if wm:
                    href = wm.group(1)
            slug = self._slug_from_url(href)
            if not slug:
                continue

            title = ""
            if name_m:
                tail = chunk[name_m.end() :]
                # Title is the anchor's inner text up to the closing </a>.
                end = tail.find("</a>")
                if end >= 0:
                    title = self._text(self._strip_tags(tail[:end]))
            if not title:
                jp = _JP_TITLE_RE.search(chunk)
                if jp:
                    title = self._text(jp.group(1))
            if not title:
                alt = _IMG_ALT_RE.search(chunk)
                if alt:
                    title = self._text(alt.group(1))
            if not title:
                continue

            cover = ""
            img = _IMG_SRC_RE.search(chunk)
            if img:
                cover = self._abs(self._text(img.group(1)))
            title_original = ""
            jp = _JP_TITLE_RE.search(chunk)
            if jp:
                title_original = self._text(jp.group(1))

            out.append(
                ChannelSearchResult(
                    channel=self.id,
                    title=title,
                    title_original=title_original,
                    cover_url=cover,
                    detail_ref=slug,
                )
            )
        return out

    # ------------------------------------------------------------------- detail

    async def get_detail(self, detail_ref: str) -> ChannelDetail:
        slug = detail_ref
        resp = await http.request(
            self.id,
            "detail",
            "GET",
            f"{BASE}/watch/{slug}",
            headers=HTML_HEADERS,
        )
        body = resp.text

        title = ""
        h1 = _H1_TITLE_RE.search(body)
        if h1:
            title = self._text(self._strip_tags(h1.group(1)))
        if not title:
            pt = _PAGE_TITLE_RE.search(body)
            if pt:
                title = self._text(_TITLE_SUFFIX_RE.sub("", pt.group(1)))

        cover = ""
        og = _OG_IMAGE_RE.search(body) or _OG_IMAGE_REV_RE.search(body)
        if og:
            cover = self._abs(self._text(og.group(1)))
        if not cover:
            pi = _POSTER_IMG_RE.search(body)
            if pi:
                cover = self._abs(self._text(pi.group(1)))

        desc = ""
        sy = _SYNOPSIS_RE.search(body)
        if sy:
            desc = self._text(self._strip_tags(sy.group(1)))[:1000]

        anime_id = ""
        wm = _WATCH_MAIN_ID_RE.search(body)
        if wm:
            anime_id = wm.group(1)

        # Episodes: inline when present, otherwise lazy-loaded via AJAX.
        ep_html = body
        if anime_id and not _INLINE_EP_ANCHOR_RE.search(body):
            try:
                ajax = await http.request(
                    self.id,
                    "detail",
                    "GET",
                    f"{BASE}/ajax/episode/list/{anime_id}",
                    headers={**HTML_HEADERS, "X-Requested-With": "XMLHttpRequest"},
                )
                data = json.loads(ajax.text)
                ep_html = data.get("result", "")
            except (ValueError, json.JSONDecodeError):
                logger.warning("[anikoto] episode AJAX returned non-JSON for %s", slug)
                ep_html = ""

        episodes: list[ChannelEpisode] = []
        seen: set[tuple[str, str]] = set()
        for m in _EP_ANCHOR_RE.finditer(ep_html):
            tag = m.group(0)
            num = _attr(tag, "data-num")
            if not num:
                continue
            ep_id = _attr(tag, "data-id")
            mal = _attr(tag, "data-mal")
            ts = _attr(tag, "data-timestamp")
            ids = _attr(tag, "data-ids")
            key = (num, ids)
            if key in seen:
                continue
            seen.add(key)
            ep_title = ""
            tm = _EP_TITLE_RE.search(tag)
            if tm:
                ep_title = self._text(self._strip_tags(tm.group(1)))
            title_text = ep_title or f"Episode {num}"
            episodes.append(
                ChannelEpisode(
                    title=title_text,
                    episode_ref=f"{slug}::{num}::{ids}::{mal}::{ts}::{ep_id}",
                )
            )
        episodes.sort(key=lambda e: e.episode_ref.split("::")[1].zfill(6))

        group = ChannelEpisodeGroup(title="Anikoto", episodes=episodes)
        return ChannelDetail(
            channel=self.id,
            title=title,
            cover_url=cover,
            description=desc,
            groups=[group] if group.episodes else [],
        )

    # ------------------------------------------------------------------ streams

    async def get_streams(self, episode_ref: str) -> list[ChannelStream]:
        parts = episode_ref.split("::")
        if len(parts) < 3 or not parts[0] or not parts[2]:
            raise ChannelError(self.id, "streams", "malformed episode_ref", retryable=False)
        slug, num, data_ids, mal, ts = parts[0], parts[1], parts[2], parts[3], parts[4]

        servers = await self._fetch_servers(slug, num, data_ids)
        streams: list[ChannelStream] = []
        seen_urls: set[str] = set()
        for server_name, sv_id, link_id in servers:
            try:
                embed_url = await self._resolve_embed_url(slug, num, link_id, sv_id)
            except ChannelError:
                continue
            if not embed_url:
                continue
            stream = await self._resolve_embed(embed_url, server_name)
            if not stream or stream.url in seen_urls:
                continue
            seen_urls.add(stream.url)
            streams.append(stream)

        # Last-resort fallback: Kiwi Mapper side-channel (server-code path).
        if not streams and mal and ts:
            kiwi = await self._resolve_kiwi(mal, num, ts)
            if kiwi and kiwi.url not in seen_urls:
                streams.append(kiwi)

        if not streams:
            raise ChannelError(
                self.id, "streams", "no playable stream resolved", retryable=False
            )

        # Prefer vidtube (raw TS, no prefix strip) over megaplay, then others.
        def sort_key(s: ChannelStream) -> tuple[int, str]:
            host = s.url.split("/")[2] if "://" in s.url else ""
            if "vidtube" in host or "akirax" in host or "norami" in host:
                return (0, host)
            return (1, host)

        streams.sort(key=sort_key)
        return streams

    async def _fetch_servers(
        self, slug: str, num: str, data_ids: str
    ) -> list[tuple[str, str, str]]:
        """Return (name, sv_id, link_id) tuples, deduped, in site order."""
        resp = await http.request(
            self.id,
            "streams",
            "GET",
            f"{BASE}/ajax/server/list",
            params={"servers": data_ids},
            headers={
                **HTML_HEADERS,
                "Referer": f"{BASE}/watch/{slug}/ep-{num}",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        try:
            data = json.loads(resp.text)
            result = data.get("result", "")
        except (ValueError, json.JSONDecodeError):
            result = resp.text
        out: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for m in _SERVER_LI_RE.finditer(result):
            tag = m.group(0)
            sv_id = _attr(tag, "data-sv-id")
            link_id = _attr(tag, "data-link-id")
            if not sv_id or not link_id or (sv_id, link_id) in seen:
                continue
            seen.add((sv_id, link_id))
            name = self._text(self._strip_tags(tag)) or "Anikoto"
            out.append((name, sv_id, link_id))
        return out

    async def _resolve_embed_url(self, slug: str, num: str, link_id: str, sv_id: str) -> str:
        resp = await http.request(
            self.id,
            "streams",
            "GET",
            f"{BASE}/ajax/server",
            params={"get": link_id, "sv": sv_id},
            headers={
                **HTML_HEADERS,
                "Referer": f"{BASE}/watch/{slug}/ep-{num}",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        try:
            data = json.loads(resp.text)
            url = (data.get("result") or {}).get("url", "")
        except (ValueError, json.JSONDecodeError):
            return ""
        return str(url) if url else ""

    async def _resolve_embed(self, embed_url: str, server_name: str) -> ChannelStream | None:
        """Resolve an embed URL to a playable HLS stream (megaplay/vidtube/megacloud)."""
        host = (embed_url.split("/")[2] if "://" in embed_url else "").lower()
        if not host:
            return None

        # Domain rotations: normalize known mirrors to megaplay.buzz.
        url = embed_url
        if "vidwish.live" in host:
            url = url.replace("vidwish.live", "megaplay.buzz")
            host = "megaplay.buzz"
        elif "megacloud.bloggy.click" in host:
            url = url.replace("megacloud.bloggy.click", "megaplay.buzz")
            host = "megaplay.buzz"

        try:
            if "megaplay.buzz" in host or "vidtube.site" in host or "vidtube" in host:
                return await self._resolve_megaplay(url, host, server_name)
            if "megacloud.blog" in host:
                return await self._resolve_megacloud(url, host, server_name)
        except ChannelError:
            return None

        # Unknown host: follow one iframe hop, then re-dispatch.
        current = embed_url
        for _ in range(2):
            try:
                resp = await http.request(
                    self.id,
                    "streams",
                    "GET",
                    current,
                    headers={**HTML_HEADERS, "Referer": f"https://{host}/"},
                )
            except ChannelError:
                return None
            body = resp.text
            ifm = _IFRAME_SRC_RE.search(body)
            if not ifm:
                return None
            current = urljoin(current, ifm.group(1))
            nhost = (current.split("/")[2] if "://" in current else "").lower()
            if "megaplay.buzz" in nhost or "vidtube" in nhost:
                return await self._resolve_megaplay(current, nhost, server_name)
            if "megacloud.blog" in nhost:
                return await self._resolve_megacloud(current, nhost, server_name)
        return None

    async def _resolve_megaplay(
        self, embed_url: str, host: str, server_name: str
    ) -> ChannelStream | None:
        """MegaPlay/VidTube: <title>File N</title> -> /stream/getSources?id=N."""
        referer = f"https://{host}/"
        resp = await http.request(
            self.id,
            "streams",
            "GET",
            embed_url,
            headers={**HTML_HEADERS, "Referer": referer},
        )
        m = _MEGAPLAY_ID_RE.search(resp.text)
        if not m:
            logger.warning("[anikoto] megaplay page had no 'File N' id: %s", embed_url)
            return None
        fid = m.group(1)
        src = await http.request(
            self.id,
            "streams",
            "GET",
            f"https://{host}/stream/getSources",
            params={"id": fid},
            headers={
                **HTML_HEADERS,
                "Referer": referer,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json,*/*",
            },
        )
        try:
            data = json.loads(src.text)
        except (ValueError, json.JSONDecodeError):
            return None
        m3u8 = (data.get("sources") or {}).get("file") or ""
        if not m3u8:
            return None
        tracks = data.get("tracks") or []
        note = server_name
        if tracks:
            langs = sorted({t.get("label", "") for t in tracks if t.get("label")})
            note = f"{server_name}（{len(langs)} 字幕）"
        return ChannelStream(
            type="hls",
            url=str(m3u8),
            format="hls",
            headers={"User-Agent": UA, "Referer": referer},
            note=note,
        )

    async def _resolve_megacloud(
        self, embed_url: str, host: str, server_name: str
    ) -> ChannelStream | None:
        """Megacloud: nonce -> /embed-2/v3/e-1/getSources?id=<id>&_k=<nonce>."""
        origin = f"https://{host}"
        referer = origin + "/"
        resp = await http.request(
            self.id,
            "streams",
            "GET",
            embed_url,
            headers={**HTML_HEADERS, "Referer": referer},
        )
        nonce_m = _NONCE_48_RE.search(resp.text)
        if not nonce_m:
            return None
        nonce = nonce_m.group(0)
        s_id = embed_url.split("/e-1/")[1].split("?")[0] if "/e-1/" in embed_url else embed_url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
        src = await http.request(
            self.id,
            "streams",
            "GET",
            f"{origin}/embed-2/v3/e-1/getSources",
            params={"id": s_id, "_k": nonce},
            headers={
                **HTML_HEADERS,
                "Referer": referer,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "*/*",
            },
        )
        try:
            data = json.loads(src.text)
        except (ValueError, json.JSONDecodeError):
            return None
        sources = data.get("sources") or []
        m3u8 = ""
        if isinstance(sources, list) and sources and isinstance(sources[0], dict):
            m3u8 = sources[0].get("file") or ""
        if not m3u8 and data.get("encrypted"):
            # Encrypted payload — try the public decrypt helper (best effort).
            import httpx

            enc = ""
            if isinstance(sources, list) and sources:
                enc = sources[0].get("file", "")
            if enc:
                try:
                    keys_resp = await http.request(
                        self.id,
                        "streams",
                        "GET",
                        "https://raw.githubusercontent.com/yogesh-hacker/MegacloudKeys/refs/heads/main/keys.json",
                        headers={"User-Agent": http.DEFAULT_UA},
                        timeout=10.0,
                    )
                    secret = (json.loads(keys_resp.text) or {}).get("mega", "")
                    if secret:
                        dec_url = (
                            "https://megacloud-api-nine.vercel.app/"
                            f"?encrypted_data={enc}&nonce={nonce}&secret={secret}"
                        )
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            dec = await client.get(dec_url)
                            body = dec.text
                        m = re.search(r'"file"\s*:\s*"(.*?)"', body)
                        if m:
                            m3u8 = m.group(1)
                except Exception:
                    logger.warning("[anikoto] megacloud decrypt failed", exc_info=True)
        if not m3u8:
            return None
        tracks = data.get("tracks") or []
        note = server_name
        if tracks:
            langs = sorted({t.get("label", "") for t in tracks if t.get("label")})
            note = f"{server_name}（{len(langs)} 字幕）"
        return ChannelStream(
            type="hls",
            url=m3u8,
            format="hls",
            headers={"User-Agent": UA, "Referer": referer},
            note=note,
        )

    async def _resolve_kiwi(self, mal_id: str, num: str, ts: str) -> ChannelStream | None:
        """Kiwi Mapper fallback: only the server-code path is automatable.

        The mapper often returns pahe.nekostream.site click-through download
        shortlinks (needs JS); those are skipped. When it returns a real
        anikoto server code, we resolve it through /ajax/server?get= and the
        HLS behind kwik.cx2 is playable directly.
        """
        for mapper in KIWI_MAPPER_URLS:
            try:
                resp = await http.request(
                    self.id,
                    "streams",
                    "GET",
                    f"{mapper}/{mal_id}/{num}/{ts}",
                    headers={
                        **HTML_HEADERS,
                        "Referer": BASE + "/",
                        "Origin": BASE,
                    },
                    timeout=10.0,
                )
                data = json.loads(resp.text)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            for key in data:
                if key == "status":
                    continue
                entry = data[key]
                if not isinstance(entry, dict):
                    continue
                for typ in ("sub", "dub"):
                    item = entry.get(typ)
                    if not isinstance(item, dict):
                        continue
                    code = item.get("url") or ""
                    if not code and isinstance(item.get("download"), dict):
                        code = item["download"].get("url") or ""
                    if not code:
                        continue
                    # Only a short opaque server code is usable here; full
                    # URLs are click-through shortlinks we cannot automate.
                    if "://" in code:
                        continue
                    try:
                        srv = await http.request(
                            self.id,
                            "streams",
                            "GET",
                            f"{BASE}/ajax/server",
                            params={"get": code},
                            headers={**HTML_HEADERS, "Referer": f"{BASE}/watch/"},
                        )
                        embed = (json.loads(srv.text).get("result") or {}).get("url", "")
                    except Exception:
                        continue
                    if not embed:
                        continue
                    if "#" in embed:
                        try:
                            embed = base64.b64decode(embed.split("#", 1)[1]).decode("utf-8")
                        except Exception:
                            continue
                    if not embed.startswith("http"):
                        continue
                    referer = "https://kwik.cx2.mewcdn.online/"
                    return ChannelStream(
                        type="hls",
                        url=embed,
                        format="hls",
                        headers={"User-Agent": UA, "Referer": referer},
                        note="Anikoto · Kiwi Stream",
                    )
        return None
