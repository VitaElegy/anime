"""Persistent JSON response cache with stale-while-revalidate support."""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable

from app.services import database as db

logger = logging.getLogger(__name__)

Producer = Callable[[], Awaitable[object]]
_refresh_tasks: dict[str, asyncio.Task] = {}


def make_cache_key(namespace: str, **params) -> str:
    raw = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


def _is_fresh(entry: dict | None) -> bool:
    return bool(entry and entry["expires_at"] > int(time.time()))


async def _refresh(
    *,
    cache_key: str,
    cache_group: str,
    ttl_seconds: int,
    producer: Producer,
):
    try:
        payload = await producer()
        if payload is not None:
            db.set_response_cache(cache_key, cache_group, payload, ttl_seconds)
    except Exception as exc:
        logger.warning("Background cache refresh failed for %s: %s", cache_key, exc)
    finally:
        _refresh_tasks.pop(cache_key, None)


def schedule_refresh(
    *,
    cache_key: str,
    cache_group: str,
    ttl_seconds: int,
    producer: Producer,
):
    task = _refresh_tasks.get(cache_key)
    if task and not task.done():
        return
    _refresh_tasks[cache_key] = asyncio.create_task(
        _refresh(
            cache_key=cache_key,
            cache_group=cache_group,
            ttl_seconds=ttl_seconds,
            producer=producer,
        )
    )


async def get_or_set_json(
    *,
    cache_key: str,
    cache_group: str,
    ttl_seconds: int,
    producer: Producer,
    force_refresh: bool = False,
    allow_stale: bool = True,
):
    entry = db.get_response_cache(cache_key)
    if not force_refresh and _is_fresh(entry):
        return entry["payload"]

    if not force_refresh and entry and allow_stale:
        schedule_refresh(
            cache_key=cache_key,
            cache_group=cache_group,
            ttl_seconds=ttl_seconds,
            producer=producer,
        )
        return entry["payload"]

    payload = await producer()
    if payload is not None:
        db.set_response_cache(cache_key, cache_group, payload, ttl_seconds)
    elif entry and allow_stale:
        return entry["payload"]
    return payload


def get_cached_json(cache_key: str):
    entry = db.get_response_cache(cache_key)
    if not entry:
        return None
    return entry["payload"]


async def warm_json(
    *,
    cache_key: str,
    cache_group: str,
    ttl_seconds: int,
    producer: Producer,
):
    payload = await producer()
    if payload is not None:
        db.set_response_cache(cache_key, cache_group, payload, ttl_seconds)
    return payload
