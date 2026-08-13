"""Shared async HTTP client for channel providers.

All channel traffic goes through this client so timeouts, proxy and UA are
uniform. Providers must not create their own clients.
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.services.channels.base import ChannelError

#: Default desktop UA used unless a provider overrides it per request.
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        kwargs: dict = {
            "timeout": 8.0,
            "follow_redirects": True,
            "headers": {"User-Agent": DEFAULT_UA},
        }
        if settings.HTTP_PROXY:
            kwargs["proxy"] = settings.HTTP_PROXY
        _client = httpx.AsyncClient(**kwargs)
    return _client


async def request(
    channel: str,
    stage: str,
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    data: dict | None = None,
    json_body: dict | None = None,
    timeout: float | None = None,
) -> httpx.Response:
    """Perform one external request and raise ChannelError on transport/HTTP errors.

    Pass either ``data`` (form-encoded) or ``json_body`` (JSON-encoded) — never both.
    ``timeout`` overrides the shared 8s client timeout for this single request
    (httpx per-request option; the client stays shared). Documented exceptions:
    AnimeXin detail/stream pages need 20s (docs/RESOURCE_BACKUP_PLAN.md §2.6).
    """
    try:
        resp = await get_client().request(
            method,
            url,
            headers=headers,
            params=params,
            data=data,
            json=json_body,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp
    except httpx.HTTPError as exc:
        raise ChannelError(channel, stage, str(exc)) from exc
