"""Persistent JSON response cache with stale-while-revalidate support.

As of P2-#13 this module also maintains a tiny process-local L1 in front of
SQLite. Fresh entries are served straight from memory, which drops the
per-request cost of hot endpoints (calendar/schedule) from "sqlite open +
row fetch + json decode" to a dict lookup. The L1 never serves stale data —
once an entry's ``expires_at`` is in the past we evict locally and let the
SQLite path (still with stale-while-revalidate semantics) take over.
"""

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

# L1 cache: ``cache_key -> (expires_at_epoch, payload)``. We intentionally
# do NOT cap the size — the number of distinct cache keys in this app is
# bounded by the number of endpoint × (query param) combinations, which in
# practice stays in the low hundreds.
_l1_cache: dict[str, tuple[int, object]] = {}


def make_cache_key(namespace: str, **params) -> str:
    raw = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


def _is_fresh(entry: dict | None) -> bool:
    return bool(entry and entry["expires_at"] > int(time.time()))


def _l1_get(cache_key: str) -> object | None:
    entry = _l1_cache.get(cache_key)
    if entry is None:
        return None
    expires_at, payload = entry
    if expires_at <= int(time.time()):
        _l1_cache.pop(cache_key, None)
        return None
    return payload


def _l1_set(cache_key: str, payload: object, expires_at: int) -> None:
    _l1_cache[cache_key] = (expires_at, payload)


def _l1_invalidate(cache_key: str) -> None:
    _l1_cache.pop(cache_key, None)


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
            _l1_set(cache_key, payload, int(time.time()) + max(ttl_seconds, 0))
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
    # L1 fast path for fresh entries only — stale-while-revalidate decisions
    # stay in the SQLite layer so cross-process L1 mismatches can't make
    # a request think its copy is fresher than it really is.
    if not force_refresh:
        cached = _l1_get(cache_key)
        if cached is not None:
            return cached

    entry = db.get_response_cache(cache_key)
    if not force_refresh and _is_fresh(entry):
        _l1_set(cache_key, entry["payload"], int(entry["expires_at"]))
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
        _l1_set(cache_key, payload, int(time.time()) + max(ttl_seconds, 0))
    elif entry and allow_stale:
        return entry["payload"]
    return payload


def get_cached_json(cache_key: str):
    cached = _l1_get(cache_key)
    if cached is not None:
        return cached
    entry = db.get_response_cache(cache_key)
    if not entry:
        return None
    if _is_fresh(entry):
        _l1_set(cache_key, entry["payload"], int(entry["expires_at"]))
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
        _l1_set(cache_key, payload, int(time.time()) + max(ttl_seconds, 0))
    return payload


def invalidate(cache_key: str) -> None:
    """Drop a key from both the L1 and SQLite layers."""
    _l1_invalidate(cache_key)
    db.delete_response_cache(cache_key)


def clear_l1_for_tests() -> None:
    """Exposed for unit tests — never call from production code."""
    _l1_cache.clear()
