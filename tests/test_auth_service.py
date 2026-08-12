"""Tests for the low-level auth service (password hashing, session TTL)."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from app.services import auth as auth_service
from app.services import database as db


class AuthServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tempdir.name) / "auth-service-test.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        self.tempdir.cleanup()

    def test_register_rejects_short_password(self):
        with self.assertRaises(ValueError):
            auth_service.register("alice_valid", "short")

    def test_register_rejects_invalid_username(self):
        with self.assertRaises(ValueError):
            auth_service.register("!!", "properpassword")

    def test_register_rejects_duplicate_username(self):
        auth_service.register("dupe_user", "properpassword")
        with self.assertRaises(ValueError):
            auth_service.register("dupe_user", "otherpassword")

    def test_login_succeeds_with_correct_credentials(self):
        auth_service.register("login_ok", "properpassword")
        result = auth_service.login("login_ok", "properpassword")
        self.assertEqual(result["user"]["username"], "login_ok")
        self.assertTrue(result["token"])
        self.assertGreater(result["expires_at"], int(time.time()))

    def test_login_rejects_wrong_password(self):
        auth_service.register("login_bad", "properpassword")
        with self.assertRaises(ValueError):
            auth_service.login("login_bad", "wrongpassword")

    def test_token_round_trip(self):
        result = auth_service.register("token_user", "properpassword")
        token = result["token"]
        resolved = auth_service.get_user_from_token(token)
        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved["username"], "token_user")

    def test_logout_invalidates_token(self):
        result = auth_service.register("logout_user", "properpassword")
        token = result["token"]
        self.assertIsNotNone(auth_service.get_user_from_token(token))
        self.assertTrue(auth_service.logout(token))
        self.assertIsNone(auth_service.get_user_from_token(token))

    def test_expired_session_is_rejected_and_purged(self):
        result = auth_service.register("expiring_user", "properpassword")
        token = result["token"]

        with db.get_conn() as conn:
            conn.execute(
                "UPDATE user_sessions SET expires_at = 1 WHERE token_hash = ?",
                (auth_service._token_hash(token),),
            )

        self.assertIsNone(auth_service.get_user_from_token(token))
        # And the expired row should be gone.
        with db.get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM user_sessions WHERE token_hash = ?",
                (auth_service._token_hash(token),),
            ).fetchone()["c"]
        self.assertEqual(count, 0)

    def test_password_hash_uses_different_salt_per_user(self):
        auth_service.register("user_a_salt", "sharedpassword")
        auth_service.register("user_b_salt", "sharedpassword")
        a = db.get_user_by_username("user_a_salt")
        b = db.get_user_by_username("user_b_salt")
        assert a is not None and b is not None
        self.assertNotEqual(a["password_salt"], b["password_salt"])
        # Identical passwords → different hashes (because of different salts).
        self.assertNotEqual(a["password_hash"], b["password_hash"])

    def test_username_is_normalised_to_lowercase(self):
        auth_service.register("CaseSensitive_User", "properpassword")
        # The stored row lives under the lowered form.
        self.assertIsNotNone(db.get_user_by_username("casesensitive_user"))
        # And login matches case-insensitively.
        result = auth_service.login("CaseSensitive_User", "properpassword")
        self.assertEqual(result["user"]["username"], "casesensitive_user")


class TokenHashDeterminismTests(unittest.TestCase):
    def test_hash_is_stable(self):
        self.assertEqual(auth_service._token_hash("abc"), auth_service._token_hash("abc"))

    def test_hash_differs_for_different_tokens(self):
        self.assertNotEqual(auth_service._token_hash("abc"), auth_service._token_hash("abd"))


if __name__ == "__main__":
    unittest.main()
