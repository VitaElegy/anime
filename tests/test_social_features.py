import time
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services import database as db


class SocialFeatureFlowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tempdir.name) / "social-test.db"
        db.init_db()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        db.DB_PATH = self.original_db_path
        self.tempdir.cleanup()

    def register_user(self, username: str) -> tuple[int, dict[str, str]]:
        response = self.client.post(
            "/api/auth/register",
            json={"username": username, "password": "pass123456"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        return int(payload["user"]["id"]), {"Authorization": f"Bearer {payload['token']}"}

    def create_room(self, headers: dict[str, str], name: str) -> str:
        response = self.client.post(
            "/api/watch/rooms",
            headers=headers,
            json={"name": name, "host_name": name},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["room_id"]

    def befriend(self, sender_headers: dict[str, str], target_headers: dict[str, str], target_username: str) -> int:
        request_response = self.client.post(
            "/api/social/friends/requests",
            headers=sender_headers,
            json={"username": target_username},
        )
        self.assertEqual(request_response.status_code, 200, request_response.text)
        request_id = int(request_response.json()["request_id"])
        accept_response = self.client.post(
            f"/api/social/friends/requests/{request_id}/accept",
            headers=target_headers,
        )
        self.assertEqual(accept_response.status_code, 200, accept_response.text)
        return request_id

    def heartbeat_room(self, headers: dict[str, str], room_id: str, room_name: str):
        response = self.client.post(
            "/api/social/presence",
            headers=headers,
            json={
                "room_id": room_id,
                "room_name": room_name,
                "page": "watch_room",
                "status_text": "正在同看",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def age_room(self, room_id: str, seconds_ago: int):
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE watch_rooms SET updated_at = ? WHERE room_id = ?",
                (int(time.time()) - seconds_ago, room_id),
            )

    def test_room_invitation_and_room_chat_flow(self):
        _, alice_headers = self.register_user("alice_room")
        bob_id, bob_headers = self.register_user("bob_room")

        room_id = self.create_room(alice_headers, "Invite Room")
        self.befriend(alice_headers, bob_headers, "bob_room")

        invite_response = self.client.post(
            f"/api/social/rooms/{room_id}/invite",
            headers=alice_headers,
            json={"friend_user_id": bob_id, "message": "一起看吧"},
        )
        self.assertEqual(invite_response.status_code, 200, invite_response.text)
        invitation_id = int(invite_response.json()["invitation_id"])

        lobby_response = self.client.get("/api/social/lobby", headers=bob_headers)
        self.assertEqual(lobby_response.status_code, 200, lobby_response.text)
        incoming = lobby_response.json()["incoming_room_invitations"]
        self.assertTrue(any(item["invitation_id"] == invitation_id for item in incoming))

        accept_response = self.client.post(
            f"/api/social/room-invitations/{invitation_id}/accept",
            headers=bob_headers,
        )
        self.assertEqual(accept_response.status_code, 200, accept_response.text)
        self.assertEqual(accept_response.json()["status"], "accepted")

        send_message_response = self.client.post(
            f"/api/watch/rooms/{room_id}/messages",
            headers=alice_headers,
            json={"body": "hello watch room"},
        )
        self.assertEqual(send_message_response.status_code, 200, send_message_response.text)

        room_messages_response = self.client.get(
            f"/api/watch/rooms/{room_id}/messages",
            headers=bob_headers,
        )
        self.assertEqual(room_messages_response.status_code, 200, room_messages_response.text)
        messages = room_messages_response.json()
        self.assertTrue(any(item["body"] == "hello watch room" for item in messages))

    def test_remove_friend_clears_pending_invites_and_readd_requires_new_approval(self):
        _, alice_headers = self.register_user("alice_retry")
        bob_id, bob_headers = self.register_user("bob_retry")

        room_id = self.create_room(alice_headers, "Retry Room")
        self.befriend(alice_headers, bob_headers, "bob_retry")

        invite_response = self.client.post(
            f"/api/social/rooms/{room_id}/invite",
            headers=alice_headers,
            json={"friend_user_id": bob_id, "message": "先邀请你"},
        )
        self.assertEqual(invite_response.status_code, 200, invite_response.text)

        remove_response = self.client.delete(f"/api/social/friends/{bob_id}", headers=alice_headers)
        self.assertEqual(remove_response.status_code, 200, remove_response.text)

        lobby_response = self.client.get("/api/social/lobby", headers=bob_headers)
        self.assertEqual(lobby_response.status_code, 200, lobby_response.text)
        self.assertEqual(lobby_response.json()["incoming_room_invitations"], [])

        readd_response = self.client.post(
            "/api/social/friends/requests",
            headers=alice_headers,
            json={"username": "bob_retry"},
        )
        self.assertEqual(readd_response.status_code, 200, readd_response.text)
        self.assertEqual(readd_response.json()["status"], "pending")

        second_lobby_response = self.client.get("/api/social/lobby", headers=bob_headers)
        self.assertEqual(second_lobby_response.status_code, 200, second_lobby_response.text)
        self.assertEqual(len(second_lobby_response.json()["incoming_requests"]), 1)

    def test_room_invitation_validations(self):
        alice_id, alice_headers = self.register_user("alice_validate")
        bob_id, bob_headers = self.register_user("bob_validate")
        carol_id, _ = self.register_user("carol_validate")

        room_id = self.create_room(alice_headers, "Validation Room")
        other_room_id = self.create_room(alice_headers, "Another Room")
        self.befriend(alice_headers, bob_headers, "bob_validate")

        self.heartbeat_room(bob_headers, room_id, "Validation Room")

        already_inside_response = self.client.post(
            f"/api/social/rooms/{room_id}/invite",
            headers=alice_headers,
            json={"friend_user_id": bob_id, "message": "已经在房间里"},
        )
        self.assertEqual(already_inside_response.status_code, 400, already_inside_response.text)
        self.assertEqual(already_inside_response.json()["detail"], "好友已经在这个房间里")

        self.heartbeat_room(bob_headers, other_room_id, "Another Room")

        self_invite_response = self.client.post(
            f"/api/social/rooms/{room_id}/invite",
            headers=alice_headers,
            json={"friend_user_id": alice_id, "message": "self"},
        )
        self.assertEqual(self_invite_response.status_code, 400, self_invite_response.text)
        self.assertEqual(self_invite_response.json()["detail"], "不能邀请自己")

        non_friend_response = self.client.post(
            f"/api/social/rooms/{room_id}/invite",
            headers=alice_headers,
            json={"friend_user_id": carol_id, "message": "not friend"},
        )
        self.assertEqual(non_friend_response.status_code, 400, non_friend_response.text)
        self.assertEqual(non_friend_response.json()["detail"], "只能邀请好友进入房间")

        long_message_response = self.client.post(
            f"/api/social/rooms/{room_id}/invite",
            headers=alice_headers,
            json={"friend_user_id": bob_id, "message": "x" * 241},
        )
        self.assertEqual(long_message_response.status_code, 400, long_message_response.text)
        self.assertEqual(long_message_response.json()["detail"], "邀请留言请控制在 240 字以内")

    def test_message_length_validations(self):
        _, alice_headers = self.register_user("alice_message_limit")
        bob_id, bob_headers = self.register_user("bob_message_limit")

        room_id = self.create_room(alice_headers, "Message Limit Room")
        self.befriend(alice_headers, bob_headers, "bob_message_limit")

        direct_message_response = self.client.post(
            f"/api/social/friends/{bob_id}/messages",
            headers=alice_headers,
            json={"body": "d" * 801},
        )
        self.assertEqual(direct_message_response.status_code, 400, direct_message_response.text)
        self.assertEqual(direct_message_response.json()["detail"], "消息请控制在 800 字以内")

        room_message_response = self.client.post(
            f"/api/watch/rooms/{room_id}/messages",
            headers=alice_headers,
            json={"body": "r" * 1001},
        )
        self.assertEqual(room_message_response.status_code, 400, room_message_response.text)
        self.assertEqual(room_message_response.json()["detail"], "消息请控制在 1000 字以内")

    def test_presence_heartbeat_uses_canonical_room_name(self):
        _, alice_headers = self.register_user("alice_presence")
        room_id = self.create_room(alice_headers, "Canonical Room")

        heartbeat_response = self.client.post(
            "/api/social/presence",
            headers=alice_headers,
            json={
                "room_id": room_id,
                "room_name": "Fake Room Name",
                "page": "watch_room",
                "status_text": "正在同看",
            },
        )
        self.assertEqual(heartbeat_response.status_code, 200, heartbeat_response.text)
        self.assertEqual(heartbeat_response.json()["current_room_name"], "Canonical Room")

        lobby_response = self.client.get("/api/social/lobby", headers=alice_headers)
        self.assertEqual(lobby_response.status_code, 200, lobby_response.text)
        payload = lobby_response.json()
        self.assertEqual(payload["online_users"][0]["current_room_name"], "Canonical Room")
        target_room = next(item for item in payload["rooms"] if item["room_id"] == room_id)
        self.assertEqual(target_room["participant_count"], 1)
        self.assertEqual(target_room["participant_usernames"], ["alice_presence"])

    def test_presence_heartbeat_rejects_unknown_room(self):
        _, alice_headers = self.register_user("alice_presence_invalid")

        heartbeat_response = self.client.post(
            "/api/social/presence",
            headers=alice_headers,
            json={
                "room_id": "ghost-room",
                "room_name": "Ghost",
                "page": "watch_room",
                "status_text": "正在同看",
            },
        )
        self.assertEqual(heartbeat_response.status_code, 400, heartbeat_response.text)
        self.assertEqual(heartbeat_response.json()["detail"], "房间不存在")

    def test_logged_in_user_must_enter_room_before_remote_room_actions(self):
        alice_id, alice_headers = self.register_user("alice_room_guard")
        bob_id, bob_headers = self.register_user("bob_room_guard")
        carol_id, carol_headers = self.register_user("carol_room_guard")

        room_id = self.create_room(alice_headers, "Guard Room")
        self.befriend(alice_headers, bob_headers, "bob_room_guard")
        self.befriend(bob_headers, carol_headers, "carol_room_guard")

        room_message_response = self.client.post(
            f"/api/watch/rooms/{room_id}/messages",
            headers=bob_headers,
            json={"body": "I should not be able to send this yet"},
        )
        self.assertEqual(room_message_response.status_code, 403, room_message_response.text)
        self.assertEqual(room_message_response.json()["detail"], "请先进入房间后再操作")

        room_state_response = self.client.put(
            f"/api/watch/rooms/{room_id}/state",
            headers=bob_headers,
            json={"paused": False, "position_seconds": 12},
        )
        self.assertEqual(room_state_response.status_code, 403, room_state_response.text)
        self.assertEqual(room_state_response.json()["detail"], "请先进入房间后再操作")

        room_invite_response = self.client.post(
            f"/api/social/rooms/{room_id}/invite",
            headers=bob_headers,
            json={"friend_user_id": carol_id, "message": "remote invite"},
        )
        self.assertEqual(room_invite_response.status_code, 403, room_invite_response.text)
        self.assertEqual(room_invite_response.json()["detail"], "请先进入房间后再操作")

        self.heartbeat_room(bob_headers, room_id, "Guard Room")

        allowed_message_response = self.client.post(
            f"/api/watch/rooms/{room_id}/messages",
            headers=bob_headers,
            json={"body": "现在我已经进房间了"},
        )
        self.assertEqual(allowed_message_response.status_code, 200, allowed_message_response.text)

        allowed_state_response = self.client.put(
            f"/api/watch/rooms/{room_id}/state",
            headers=bob_headers,
            json={"paused": False, "position_seconds": 18},
        )
        self.assertEqual(allowed_state_response.status_code, 200, allowed_state_response.text)

        allowed_invite_response = self.client.post(
            f"/api/social/rooms/{room_id}/invite",
            headers=bob_headers,
            json={"friend_user_id": carol_id, "message": "joined invite"},
        )
        self.assertEqual(allowed_invite_response.status_code, 200, allowed_invite_response.text)
        self.assertEqual(allowed_invite_response.json()["recipient_user_id"], carol_id)

        owner_state_response = self.client.put(
            f"/api/watch/rooms/{room_id}/state",
            headers=alice_headers,
            json={"paused": True, "position_seconds": 24},
        )
        self.assertEqual(owner_state_response.status_code, 200, owner_state_response.text)
        self.assertEqual(owner_state_response.json()["owner_user_id"], alice_id)

    def test_lobby_cleanup_deletes_old_empty_owned_rooms(self):
        _, alice_headers = self.register_user("alice_cleanup_owned")
        room_id = self.create_room(alice_headers, "Owned Cleanup Room")
        self.age_room(room_id, 180)

        lobby_response = self.client.get("/api/social/lobby", headers=alice_headers)
        self.assertEqual(lobby_response.status_code, 200, lobby_response.text)
        room_ids = {item["room_id"] for item in lobby_response.json()["rooms"]}
        self.assertNotIn(room_id, room_ids)
        self.assertIsNone(db.get_watch_room(room_id))

    def test_lobby_cleanup_keeps_recent_owned_rooms_before_first_join(self):
        _, alice_headers = self.register_user("alice_recent_owned")
        room_id = self.create_room(alice_headers, "Recent Owned Room")

        lobby_response = self.client.get("/api/social/lobby", headers=alice_headers)
        self.assertEqual(lobby_response.status_code, 200, lobby_response.text)
        room_ids = {item["room_id"] for item in lobby_response.json()["rooms"]}
        self.assertIn(room_id, room_ids)
        self.assertIsNotNone(db.get_watch_room(room_id))

    def test_lobby_cleanup_keeps_active_rooms_even_if_room_state_is_old(self):
        _, alice_headers = self.register_user("alice_active_owned")
        room_id = self.create_room(alice_headers, "Active Owned Room")
        self.heartbeat_room(alice_headers, room_id, "Active Owned Room")
        self.age_room(room_id, 600)

        lobby_response = self.client.get("/api/social/lobby", headers=alice_headers)
        self.assertEqual(lobby_response.status_code, 200, lobby_response.text)
        room_map = {item["room_id"]: item for item in lobby_response.json()["rooms"]}
        self.assertIn(room_id, room_map)
        self.assertEqual(room_map[room_id]["participant_count"], 1)
        self.assertIsNotNone(db.get_watch_room(room_id))

    def test_lobby_cleanup_gives_anonymous_rooms_a_longer_idle_grace_period(self):
        create_response = self.client.post(
            "/api/watch/rooms",
            json={"name": "Anonymous Cleanup Room", "host_name": "anon"},
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        room_id = create_response.json()["room_id"]
        self.age_room(room_id, 180)

        lobby_response = self.client.get("/api/social/lobby")
        self.assertEqual(lobby_response.status_code, 200, lobby_response.text)
        room_ids = {item["room_id"] for item in lobby_response.json()["rooms"]}
        self.assertIn(room_id, room_ids)
        self.assertIsNotNone(db.get_watch_room(room_id))


if __name__ == "__main__":
    unittest.main()
