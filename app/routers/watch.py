"""Online watch channels API + playback stream proxy.

Contract: docs/CHANNEL_ARCHITECTURE.md §4.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

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
    # Gogoanime / megaplay chain
    "gogoanime.is",
    "gogoanime.me.uk",
    "megaplay.buzz",
    "megap.mikora.top",
    "ncdn.mewstream.buzz",
    "megap.akirax.buzz",
    "shiora.top",
    "norami.top",
    "lostproject.club",
    # Gogoanime segment CDNs (real MPEG-TS disguised as .jpg/.html/...)
    "trycloud.pro",
    "watching.onl",
)


def _host_allowed(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in _ALLOWED_STREAM_HOSTS)


#: Hosts whose HLS playlists may contain ad segments (tiktokcdn images).
#: The proxy rewrites those playlists on the fly so hls.js only sees video.
_HLS_SANITIZE_HOSTS = (
    "megap.mikora.top",
    "ncdn.mewstream.buzz",
    "megap.akirax.buzz",
    "shiora.top",
    "norami.top",
    "lostproject.club",
)

#: Host markers of known ad networks inside proxied playlists.
_AD_HOST_MARKERS = ("tiktokcdn",)


def _needs_hls_sanitize(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in _HLS_SANITIZE_HOSTS)


def _is_ad_uri(line: str) -> bool:
    if not line.startswith(("http://", "https://")):
        return False
    host = (urlparse(line).hostname or "").lower()
    return any(marker in host for marker in _AD_HOST_MARKERS)


def sanitize_hls_playlist(text: str) -> str:
    """Drop EXTINF+URI pairs pointing at ad hosts from an HLS playlist.

    Some mirror servers (e.g. megap.mikora.top) prepend/interleave tiktokcdn
    image segments into their variant playlists; hls.js would try to mux them
    as video and fail. We keep every other line untouched so relative segment
    URLs and tags survive verbatim.
    """
    lines = text.splitlines()
    out: list[str] = []
    for line in lines:
        if _is_ad_uri(line):
            # Also drop the EXTINF/comment lines that belong to this ad pair.
            while out and (out[-1].startswith("#EXTINF") or out[-1].startswith("#EXT-X-DISCONTINUITY")):
                out.pop()
            continue
        out.append(line)
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


@router.get("/proxy/stream", summary="Proxy m3u8/segments with channel headers (Range supported)")
async def proxy_stream(
    request: Request,
    url: str = Query(..., description="Absolute http(s) stream URL"),
    referer: str = Query("", description="Referer header required by the source"),
    ua: str = Query("", description="User-Agent header required by the source"),
):
    if not _host_allowed(url):
        raise HTTPException(status_code=403, detail="blocked stream host")

    headers: dict[str, str] = {}
    if referer:
        headers["Referer"] = referer
    if ua:
        headers["User-Agent"] = ua
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    try:
        upstream = await channel_http.get_client().get(url, headers=headers)
        upstream.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Stream proxy upstream error for %s: %s", url[:80], exc)
        raise HTTPException(status_code=502, detail=f"upstream error: {exc}") from exc

    content_type = upstream.headers.get("content-type") or "application/octet-stream"
    body = upstream.content
    if _needs_hls_sanitize(url) and (b"#EXTM3U" in body[:64] or "mpegurl" in content_type.lower()):
        body = sanitize_hls_playlist(upstream.text).encode("utf-8")
    out_headers: dict[str, str] = {}
    if range_header and upstream.status_code == 206:
        content_range = upstream.headers.get("content-range")
        if content_range:
            out_headers["Content-Range"] = content_range
    out_headers["Cache-Control"] = "no-cache"
    return Response(content=body, status_code=upstream.status_code, media_type=content_type, headers=out_headers)


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
