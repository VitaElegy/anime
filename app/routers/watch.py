"""Online watch channels API + playback stream proxy.

Contract: docs/CHANNEL_ARCHITECTURE.md §4.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlencode, urljoin, urlparse

import httpx
from curl_cffi.requests import AsyncSession as CurlAsyncSession
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from app.config import settings
from app.models import ChannelDetail, ChannelInfo, ChannelSearchResult, ChannelStream
from app.services.channels import http as channel_http
from app.services.channels.base import ChannelError
from app.services.channels.registry import registry

logger = logging.getLogger(__name__)
router = APIRouter()

#: Host suffixes the stream proxy is allowed to forward. Keeps the proxy from
#: becoming an open SSRF relay; add entries here when registering new channels.
_ALLOWED_STREAM_HOSTS = (
    "agedm.org",
    "aqdstatic.com",
    "libvio.com",
    "zzzhls.com",
    "alicdn.com",
    "aliyuncs.com",
    "chaoxing.com",
    "yhdmjx.com",
    "bilibili.com",
    "bilivideo.com",
    "hdslb.com",
    "akamaized.net",
    # Anilibria (direct HLS, no proxy needed)
    "anilibria.top",
    "cache.libria.fun",
    # AnimeHeaven direct mp4 CDN (ct./ck. subdomains covered by the suffix match)
    "animeheaven.me",
    # Miruro AniDBApp HLS CDN (hls.anidb.app covered by the suffix match)
    "anidb.app",
    # AnimeXin -> Dailymotion HLS (master cdndirector.dailymotion.com +
    # sub-lists/segments under vod*.cf.dmcdn.net; suffix match covers both)
    "dailymotion.com",
    "dmcdn.net",
    "cf.dmcdn.net",
    # Gogoanime / megaplay chain
    "gogoanime.is",
    "gogoanime.me.uk",
    "megaplay.buzz",
    "megap.mikora.top",
    "ncdn.mewstream.buzz",
    "megap.akirax.buzz",
    "akirax.buzz",
    "shiora.top",
    "shiora.site",
    "norami.top",
    "lostproject.club",
    # Gogoanime segment CDNs (real MPEG-TS disguised as .jpg/.html/...)
    "trycloud.pro",
    "watching.onl",
    # Megaplay obfuscated segments: real MPEG-TS served with a 252-byte PNG
    # prefix (player strips it client-side via newclient.min.js SegmentStrip).
    "tiktokcdn.com",
    "ibyteimg.com",
    "ipstatp.com",
)



def _host_allowed(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    suffixes = _ALLOWED_STREAM_HOSTS
    if settings.E2E_FIXTURE:
        # Hermetic E2E mode only: allow the locally served fixture webm so the
        # test plays through the REAL stream proxy (Range/headers/rewrite)
        # without weakening SSRF protection in production (env-gated).
        suffixes = suffixes + ("127.0.0.1", "localhost")
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes)


#: Dailymotion host suffixes. Its CDN requires a Chrome TLS fingerprint
#: (curl_cffi chrome124); the shared httpx client gets 403 (docs §2.6).
_DM_HOST_MARKERS = ("dailymotion.com", "dmcdn.net")


def _is_dailymotion_host(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return any(host == marker or host.endswith(f".{marker}") for marker in _DM_HOST_MARKERS)


#: Host markers of megaplay's obfuscated segments. The server serves real
#: MPEG-TS payloads wrapped in a short PNG/junk prefix (default 252 bytes);
#: the official player strips it via newclient.min.js SegmentStrip
#: (stripBytes/STRIP_BYTES, default 252). Matches the player's default regex
#: ``/ibyteimg\.com|tiktokcdn\.com|ipstatp\.com|yoot\.trycloud\.pro/i``.
_STRIP_HOST_MARKERS = ("tiktokcdn", "ibyteimg", "ipstatp", "trycloud")

#: Bytes to drop from the head of obfuscated segment responses.
_STRIP_BYTES = 252

_URI_TAG_RE = re.compile(r'URI="([^"]+)"')


def _should_strip_prefix(url: str) -> bool:
    """True when the response body is a real segment wrapped in a junk prefix."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(marker in host for marker in _STRIP_HOST_MARKERS)


def _build_proxy_url(target: str, referer: str = "", ua: str = "") -> str:
    """Build a same-origin stream-proxy URL for a manifest or segment URI."""
    # URL fragments (#cell=... Dailymotion cache hints, #t=... player seeks)
    # are never sent to the upstream server; dropping them keeps the proxied
    # target byte-identical to what the CDN expects.
    target = target.split("#", 1)[0]
    params = {"url": target}
    if referer:
        params["referer"] = referer
    if ua:
        params["ua"] = ua
    return f"/api/watch/proxy/stream?{urlencode(params)}"


def rewrite_hls_playlist(text: str, base_url: str, referer: str = "", ua: str = "") -> str:
    """Normalize a proxied HLS playlist so hls.js can actually play it.

    Every URI (plain lines and ``URI="..."`` attributes) is resolved against
    the playlist's own base URL and rewritten to a same-origin stream-proxy
    URL, so relative manifests (e.g. Gogoanime mirrors emit
    ``index-f1-v1-a1.m3u8``) and obfuscated segment URLs keep flowing through
    the proxy with the right Referer/UA and no CORS. Nothing is dropped: the
    "tiktokcdn ad" segments are actually the real MPEG-TS payloads (PNG-wrapped
    with a 252-byte prefix); the proxy strips that prefix per segment.
    """
    lines = text.splitlines()
    out: list[str] = []
    for line in lines:
        if line.startswith("#"):
            if 'URI="' in line:
                line = _URI_TAG_RE.sub(
                    lambda m: f'URI="{_build_proxy_url(urljoin(base_url, m.group(1)), referer, ua)}"',
                    line,
                )
            out.append(line)
            continue
        if line.strip():
            abs_uri = urljoin(base_url, line.strip())
            out.append(_build_proxy_url(abs_uri, referer, ua))
    return "\n".join(out)


@router.get("/channels", response_model=list[ChannelInfo], summary="List online watch channels + health")
async def list_channels():
    return registry.list_channels()


@router.get("/search", response_model=list[ChannelSearchResult], summary="Aggregated channel search")
async def search_channels(
    q: str = Query(..., min_length=1, description="Chinese/Japanese/English keyword"),
    page: int = Query(1, ge=1),
):
    return await registry.search(q, page)


def _stream_response(
    upstream,
    url: str,
    referer: str,
    ua: str,
    range_header: str | None,
    strip_prefix: bool,
) -> Response:
    """Turn an upstream response into a proxied stream Response.

    ``upstream`` only needs httpx/curl_cffi-compatible ``status_code``,
    ``headers``, ``content`` and ``text``. HLS manifests are rewritten to
    same-origin proxy URLs; obfuscated segments get their junk prefix peeled.
    """
    content_type = upstream.headers.get("content-type") or "application/octet-stream"
    body = upstream.content
    if b"#EXTM3U" in body[:64] or "mpegurl" in content_type.lower():
        body = rewrite_hls_playlist(upstream.text, url, referer, ua).encode("utf-8")
    elif strip_prefix and len(body) > _STRIP_BYTES:
        # Peel the obfuscation prefix; the remaining payload is raw MPEG-TS.
        body = body[_STRIP_BYTES:]
        content_type = "video/mp2t"
    out_headers: dict[str, str] = {}
    if range_header and not strip_prefix and upstream.status_code == 206:
        content_range = upstream.headers.get("content-range")
        if content_range:
            out_headers["Content-Range"] = content_range
    out_headers["Cache-Control"] = "no-cache"
    return Response(content=body, status_code=upstream.status_code, media_type=content_type, headers=out_headers)


async def _fetch_dailymotion(url: str, referer: str, ua: str, range_header: str | None):
    """Fetch a Dailymotion HLS resource via curl_cffi chrome124 (§2.6 exception).

    Dailymotion's CDN requires BOTH the curl_cffi Chrome 124 TLS fingerprint
    and a dailymotion.com Referer (verified 2026-08-13: shared httpx gets 403,
    chrome124 + non-DM referer gets 403, chrome124 + DM referer gets 200). The
    caller's referer is intentionally ignored for DM hosts — it may be the
    embedding site (e.g. animexin.dev) which the CDN rejects.
    """
    headers: dict[str, str] = {
        "Referer": "https://www.dailymotion.com/",
        "Origin": "https://www.dailymotion.com",
        "User-Agent": ua or channel_http.DEFAULT_UA,
    }
    if range_header:
        headers["Range"] = range_header
    kwargs: dict = {
        "impersonate": "chrome124",
        "timeout": 20.0,
        "headers": headers,
    }
    if settings.HTTP_PROXY:
        kwargs["proxies"] = {"http": settings.HTTP_PROXY, "https": settings.HTTP_PROXY}
    try:
        async with CurlAsyncSession(**kwargs) as client:
            upstream = await client.get(url)
            upstream.raise_for_status()
        return upstream
    except Exception as exc:
        logger.warning("Dailymotion proxy upstream error for %s: %s", url[:80], exc)
        raise HTTPException(status_code=502, detail=f"upstream error: {exc}") from exc


@router.get("/proxy/stream", summary="Proxy m3u8/segments with channel headers (Range supported)")
async def proxy_stream(
    request: Request,
    url: str = Query(..., description="Absolute http(s) stream URL"),
    referer: str = Query("", description="Referer header required by the source"),
    ua: str = Query("", description="User-Agent header required by the source"),
):
    if not _host_allowed(url):
        raise HTTPException(status_code=403, detail="blocked stream host")

    strip_prefix = _should_strip_prefix(url)
    range_header = request.headers.get("range")

    if _is_dailymotion_host(url):
        upstream = await _fetch_dailymotion(url, referer, ua, None if strip_prefix else range_header)
        return _stream_response(upstream, url, referer, ua, range_header, strip_prefix)

    headers: dict[str, str] = {}
    if referer:
        headers["Referer"] = referer
    if ua:
        headers["User-Agent"] = ua
    if range_header and not strip_prefix:
        headers["Range"] = range_header

    try:
        upstream = await channel_http.get_client().get(url, headers=headers)
        upstream.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Stream proxy upstream error for %s: %s", url[:80], exc)
        raise HTTPException(status_code=502, detail=f"upstream error: {exc}") from exc

    return _stream_response(upstream, url, referer, ua, range_header, strip_prefix)


@router.get("/{channel}/external", summary="Official external URL for external channels")
async def channel_external(channel: str, ref: str = Query(..., description="detail_ref")):
    url = registry.external_url(channel, ref)
    if not url:
        raise HTTPException(status_code=404, detail="no external url for this channel/ref")
    return {"url": url}


@router.get("/{channel}/detail", response_model=ChannelDetail, summary="Channel detail + episode groups")
async def channel_detail(channel: str, ref: str = Query(..., description="detail_ref")):
    try:
        return await registry.detail(channel, ref)
    except LookupError:
        raise HTTPException(status_code=404, detail="unknown channel") from None
    except ChannelError as exc:
        logger.warning("Channel %s detail failed: %s", channel, exc)
        return ChannelDetail(channel=channel, title="")


@router.get("/{channel}/streams", response_model=list[ChannelStream], summary="Resolve playable streams for an episode")
async def channel_streams(channel: str, ref: str = Query(..., description="episode_ref")):
    try:
        return await registry.streams(channel, ref)
    except LookupError:
        raise HTTPException(status_code=404, detail="unknown channel") from None
    except ChannelError as exc:
        logger.warning("Channel %s streams failed: %s", channel, exc)
        return []
