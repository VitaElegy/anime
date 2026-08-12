"""Tests for the auth rate limiter + HttpOnly cookie support (P2-#12)."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.main import app
from app.routers.auth import AUTH_COOKIE_NAME
from app.services import database as db
from app.services.rate_limit import LOGIN_FAILURE_LIMITER, RateLimit, SlidingWindowLimiter
from fastapi.testclient import TestClient


class SlidingWindowLimiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_allows_up_to_capacity(self):
        limiter = SlidingWindowLimiter(RateLimit(capacity=3, window_seconds=60))
        for _ in range(3):
            self.assertTrue(await limiter.hit("alice"))

    async def test_rejects_past_capacity(self):
        limiter = SlidingWindowLimiter(RateLimit(capacity=2, window_seconds=60))
        self.assertTrue(await limiter.hit("bob"))
        self.assertTrue(await limiter.hit("bob"))
        self.assertFalse(await limiter.hit("bob"))

    async def test_separate_keys_have_separate_buckets(self):
        limiter = SlidingWindowLimiter(RateLimit(capacity=1, window_seconds=60))
        self.assertTrue(await limiter.hit("a"))
        self.assertFalse(await limiter.hit("a"))
        self.assertTrue(await limiter.hit("b"))

    async def test_reset_clears_bucket(self):
        limiter = SlidingWindowLimiter(RateLimit(capacity=1, window_seconds=60))
        await limiter.hit("carol")
        limiter.reset("carol")
        self.assertTrue(await limiter.hit("carol"))

    async def test_expired_hits_drop_off(self):
        limiter = SlidingWindowLimiter(RateLimit(capacity=1, window_seconds=0.01))
        self.assertTrue(await limiter.hit("dave"))
        self.assertFalse(await limiter.hit("dave"))
        await asyncio.sleep(0.02)
        self.assertTrue(await limiter.hit("dave"))


class LoginCookieAndRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tempdir.name) / "auth-test.db"
        db.init_db()
        self.client = TestClient(app)
        # Make sure previous test runs haven't poisoned the singleton.
        LOGIN_FAILURE_LIMITER.reset("login:testclient")

    def tearDown(self):
        self.client.close()
        db.DB_PATH = self.original_db_path
        self.tempdir.cleanup()
        LOGIN_FAILURE_LIMITER.reset("login:testclient")

    def _register(self, username: str, password: str = "goodpassword"):
        return self.client.post(
            "/api/auth/register",
            json={"username": username, "password": password},
        )

    def test_register_sets_auth_cookie(self):
        response = self._register("cookie_user")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(AUTH_COOKIE_NAME, response.cookies)
        # Cookie value should match the token returned in the body.
        self.assertEqual(response.cookies[AUTH_COOKIE_NAME], response.json()["token"])

    def test_me_endpoint_accepts_cookie_only_auth(self):
        register_response = self._register("cookie_only_user")
        self.assertEqual(register_response.status_code, 200)
        # Strip any Authorization header; rely purely on the cookie jar.
        me_response = self.client.get("/api/auth/me")
        self.assertEqual(me_response.status_code, 200, me_response.text)
        self.assertEqual(me_response.json()["username"], "cookie_only_user")

    def test_logout_clears_cookie(self):
        self._register("logout_user")
        logout_response = self.client.post("/api/auth/logout")
        self.assertEqual(logout_response.status_code, 200)
        # TestClient exposes the Set-Cookie header — look for a deletion
        # (empty value or Max-Age=0).
        set_cookie = logout_response.headers.get("set-cookie", "")
        self.assertIn(AUTH_COOKIE_NAME, set_cookie)

    def test_repeated_login_failures_get_throttled(self):
        self._register("throttle_target", password="correctpassword")
        # First 10 wrong-password attempts return 400; the 11th should be 429.
        for _ in range(10):
            bad = self.client.post(
                "/api/auth/login",
                json={"username": "throttle_target", "password": "wrongpassword"},
            )
            self.assertEqual(bad.status_code, 400, bad.text)
        throttled = self.client.post(
            "/api/auth/login",
            json={"username": "throttle_target", "password": "wrongpassword"},
        )
        self.assertEqual(throttled.status_code, 429, throttled.text)
        self.assertIn("Retry-After", throttled.headers)

    def test_successful_login_clears_failure_counter(self):
        self._register("reset_user", password="rightpassword")
        # Use up some of the budget with wrong passwords.
        for _ in range(5):
            self.client.post(
                "/api/auth/login",
                json={"username": "reset_user", "password": "wrongpassword"},
            )
        # A correct login resets the bucket, so the next 10 wrong tries are
        # allowed again before throttling kicks in.
        ok = self.client.post(
            "/api/auth/login",
            json={"username": "reset_user", "password": "rightpassword"},
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        # Verify budget is truly replenished.
        for _ in range(10):
            bad = self.client.post(
                "/api/auth/login",
                json={"username": "reset_user", "password": "wrongpassword"},
            )
            self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()
