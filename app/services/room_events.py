"""In-process publish/subscribe hub for Watch Room SSE events.

Scope and limitations
---------------------
This is an intentionally small, single-process fan-out. Each subscriber gets
its own ``asyncio.Queue``; publishers push JSON-serialisable dicts; the SSE
endpoint drains its queue and formats each entry as ``event: <type>\\n
data: <json>\\n\\n`` per the EventSource protocol.

Running the API under ``uvicorn --workers N > 1`` will split subscribers
across workers, so a state change published in worker A is invisible to
subscribers connected to worker B. That's a P2+ concern — solving it properly
needs Redis pub/sub (or an external broker) and is explicitly out of scope
here. Nothing in this module will silently do the wrong thing under multi-
worker: subscribers just won't see events they'd get in single-worker mode.

Event types currently emitted:

- ``room_state``   — room playback state was mutated (owner action)
- ``room_message`` — a chat message was posted to the room
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# Per-subscriber queues, keyed by ``room_id``. A subscriber that falls more
# than this many events behind is assumed to be gone — we drop the oldest
# entries rather than grow unbounded.
_MAX_QUEUE_DEPTH = 64

_subscribers: dict[str, set[asyncio.Queue[dict]]] = defaultdict(set)
_lock = asyncio.Lock()


async def _subscribe(room_id: str) -> asyncio.Queue[dict]:
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=_MAX_QUEUE_DEPTH)
    async with _lock:
        _subscribers[room_id].add(queue)
    return queue


async def _unsubscribe(room_id: str, queue: asyncio.Queue[dict]) -> None:
    async with _lock:
        bucket = _subscribers.get(room_id)
        if bucket is None:
            return
        bucket.discard(queue)
        if not bucket:
            _subscribers.pop(room_id, None)


@asynccontextmanager
async def subscription(room_id: str) -> AsyncIterator[asyncio.Queue[dict]]:
    """Async context manager yielding a queue of events for ``room_id``."""
    queue = await _subscribe(room_id)
    try:
        yield queue
    finally:
        await _unsubscribe(room_id, queue)


async def publish(room_id: str, event_type: str, payload: dict) -> None:
    """Fan out ``(event_type, payload)`` to every active subscriber.

    Silently drops payloads for queues that are already full — better to lose
    an update on a slow client than stall the publisher for everyone else.
    """
    async with _lock:
        bucket = list(_subscribers.get(room_id, ()))
    if not bucket:
        return

    message = {"type": event_type, "data": payload}
    for queue in bucket:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            # Drop the oldest entry and retry; if that still fails the
            # subscriber is effectively dead.
            try:
                queue.get_nowait()
                queue.put_nowait(message)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                logger.debug("Dropping SSE event for stalled subscriber (room=%s)", room_id)


def publish_threadsafe(room_id: str, event_type: str, payload: dict) -> None:
    """Fire-and-forget variant callable from sync code paths.

    Schedules :func:`publish` on the running loop if there is one; silently
    no-ops otherwise (e.g. during sync unit tests that don't spin up a loop).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(publish(room_id, event_type, payload))


def format_sse(event_type: str, payload: dict) -> bytes:
    """Encode a single event in the EventSource wire format."""
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_type}\ndata: {data}\n\n".encode()


def subscriber_count(room_id: str) -> int:
    """Non-async snapshot used for diagnostics / tests."""
    return len(_subscribers.get(room_id, ()))
