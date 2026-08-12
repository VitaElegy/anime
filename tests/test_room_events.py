"""Tests for the in-process room event pub/sub hub."""

from __future__ import annotations

import asyncio
import unittest

from app.services import room_events


class RoomEventsHubTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_reaches_active_subscriber(self):
        async with room_events.subscription("room-a") as queue:
            await room_events.publish("room-a", "room_state", {"hello": "world"})
            message = await asyncio.wait_for(queue.get(), timeout=0.5)
            self.assertEqual(message, {"type": "room_state", "data": {"hello": "world"}})

    async def test_publish_fans_out_to_multiple_subscribers(self):
        async with (
            room_events.subscription("room-b") as queue_a,
            room_events.subscription("room-b") as queue_b,
        ):
            await room_events.publish("room-b", "room_message", {"body": "hi"})
            msg_a = await asyncio.wait_for(queue_a.get(), timeout=0.5)
            msg_b = await asyncio.wait_for(queue_b.get(), timeout=0.5)
            self.assertEqual(msg_a, msg_b)
            self.assertEqual(msg_a["type"], "room_message")

    async def test_publish_ignores_other_rooms(self):
        async with room_events.subscription("room-c") as queue:
            await room_events.publish("room-d", "room_state", {"x": 1})
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.1)

    async def test_unsubscribe_cleans_up_bucket(self):
        async with room_events.subscription("room-e"):
            self.assertEqual(room_events.subscriber_count("room-e"), 1)
        self.assertEqual(room_events.subscriber_count("room-e"), 0)

    async def test_full_queue_drops_oldest_entry(self):
        async with room_events.subscription("room-f") as queue:
            # Pre-fill past capacity.
            for i in range(80):
                await room_events.publish("room-f", "room_state", {"n": i})
            collected: list[int] = []
            for _ in range(queue.qsize()):
                collected.append((await queue.get())["data"]["n"])
            # We expect to have lost the oldest entries (the exact cut depends
            # on internal buffer depth) but to have seen the final one.
            self.assertIn(79, collected)
            self.assertLess(len(collected), 80)


class FormatSSETests(unittest.TestCase):
    def test_wire_format(self):
        frame = room_events.format_sse("room_state", {"room_id": "abc", "n": 1})
        decoded = frame.decode("utf-8")
        self.assertTrue(decoded.startswith("event: room_state\n"))
        self.assertIn('"room_id":"abc"', decoded)
        self.assertTrue(decoded.endswith("\n\n"))

    def test_unicode_passthrough(self):
        frame = room_events.format_sse("room_message", {"body": "你好"})
        self.assertIn("你好", frame.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
