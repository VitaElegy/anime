"""HTTP Range-aware streaming response for local video direct-play.

Starlette's default ``FileResponse`` answers every request with ``200 OK`` and
the full file body, which makes browser seeking in an ``<video>`` element very
painful: each seek re-downloads the entire asset from byte 0.

This module provides :func:`build_range_response`, a small helper that reads
the ``Range`` request header and returns either a ``206 Partial Content`` or a
normal ``200 OK`` streaming response, with proper ``Accept-Ranges``,
``Content-Range``, ``Content-Length``, ``ETag`` and ``Last-Modified`` headers.
"""

from __future__ import annotations

import hashlib
import re
from email.utils import formatdate
from pathlib import Path

from fastapi import HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse

# HTTP 416 is spelled ``HTTP_416_RANGE_NOT_SATISFIABLE`` in newer Starlette
# releases and ``HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE`` in older ones.
# The numeric value never changes — use the literal to stay quiet and
# version-independent.
_HTTP_416 = 416

# 1 MiB chunks. Large enough to keep syscalls low, small enough to keep
# per-request memory bounded even with many concurrent viewers.
_CHUNK_SIZE = 1024 * 1024

# Matches a single byte range. We deliberately do not support multi-range
# requests (e.g. "bytes=0-100, 200-300") — browsers basically never send them
# for <video> seeking, and supporting them would require multipart responses.
_RANGE_RE = re.compile(r"^bytes=(?P<start>\d*)-(?P<end>\d*)$", re.IGNORECASE)


def _file_etag(path: Path, stat_result) -> str:
    """Weak but stable ETag derived from (path, size, mtime).

    We intentionally keep this cheap — hashing the file contents would defeat
    the purpose on multi-GB videos.
    """
    token = f"{path.resolve()}|{stat_result.st_size}|{int(stat_result.st_mtime)}"
    digest = hashlib.md5(token.encode("utf-8")).hexdigest()
    return f'W/"{digest}"'


def _parse_range(header_value: str, file_size: int) -> tuple[int, int] | None:
    """Parse a single-range ``Range`` header value.

    Returns ``(start, end)`` inclusive, or ``None`` if the header is absent
    or cannot be understood. Raises :class:`HTTPException` 416 for ranges
    that are syntactically valid but unsatisfiable.
    """
    if not header_value:
        return None
    match = _RANGE_RE.match(header_value.strip())
    if not match:
        # Malformed Range — treat as if the client did not send one, per RFC 7233.
        return None

    raw_start = match.group("start")
    raw_end = match.group("end")

    if raw_start == "" and raw_end == "":
        return None

    if raw_start == "":
        # Suffix range: "bytes=-500" → last 500 bytes.
        suffix_len = int(raw_end)
        if suffix_len <= 0:
            raise HTTPException(
                status_code=_HTTP_416,
                detail="Invalid Range",
                headers={"Content-Range": f"bytes */{file_size}"},
            )
        start = max(0, file_size - suffix_len)
        end = file_size - 1
    else:
        start = int(raw_start)
        end = int(raw_end) if raw_end else file_size - 1

    if start >= file_size or end < start:
        raise HTTPException(
            status_code=_HTTP_416,
            detail="Invalid Range",
            headers={"Content-Range": f"bytes */{file_size}"},
        )
    # Clamp the upper bound in case the client asked for bytes past EOF.
    end = min(end, file_size - 1)
    return start, end


def _iter_file_chunks(path: Path, start: int, end: int, chunk_size: int = _CHUNK_SIZE):
    """Yield bytes from [start, end] inclusive, in blocks of ``chunk_size``."""
    remaining = end - start + 1
    with path.open("rb") as f:
        f.seek(start)
        while remaining > 0:
            block = f.read(min(chunk_size, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block


def build_range_response(
    request: Request,
    path: Path,
    *,
    media_type: str,
    filename: str | None = None,
) -> Response:
    """Return a ``206`` or ``200`` response honouring the ``Range`` request header.

    - ``206 Partial Content`` when the client sent a satisfiable ``Range``.
    - ``200 OK`` streaming the full file otherwise.
    - ``304 Not Modified`` when ``If-None-Match`` matches our ETag.
    - ``416 Range Not Satisfiable`` for malformed / out-of-bounds ranges.
    """
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    stat_result = path.stat()
    file_size = stat_result.st_size
    etag = _file_etag(path, stat_result)
    last_modified = formatdate(stat_result.st_mtime, usegmt=True)

    # Conditional GET — save bandwidth when the client already has a fresh copy.
    if_none_match = request.headers.get("if-none-match", "")
    if if_none_match and etag in {token.strip() for token in if_none_match.split(",")}:
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={
                "ETag": etag,
                "Last-Modified": last_modified,
                "Accept-Ranges": "bytes",
                "Cache-Control": "private, max-age=0, must-revalidate",
            },
        )

    parsed = _parse_range(request.headers.get("range", ""), file_size)

    base_headers = {
        "Accept-Ranges": "bytes",
        "ETag": etag,
        "Last-Modified": last_modified,
        "Cache-Control": "private, max-age=0, must-revalidate",
    }
    if filename:
        # Use ``inline`` so the browser plays it rather than downloading.
        # Per RFC 5987: HTTP headers must be ISO-8859-1 compatible. Any
        # non-ASCII characters (Chinese fansub filenames!) have to go through
        # the filename* extension using percent-encoded UTF-8. We also keep
        # an ASCII-safe fallback on filename= for older clients.
        from urllib.parse import quote as _urlquote

        ascii_fallback = filename.encode("ascii", errors="replace").decode("ascii").replace('"', "")
        encoded = _urlquote(filename, safe="")
        base_headers["Content-Disposition"] = (
            f"inline; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"
        )

    if parsed is None:
        base_headers["Content-Length"] = str(file_size)
        return StreamingResponse(
            _iter_file_chunks(path, 0, file_size - 1),
            status_code=status.HTTP_200_OK,
            media_type=media_type,
            headers=base_headers,
        )

    start, end = parsed
    base_headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    base_headers["Content-Length"] = str(end - start + 1)
    return StreamingResponse(
        _iter_file_chunks(path, start, end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=media_type,
        headers=base_headers,
    )
