"""HTTP-boundary authentication and in-memory session tests."""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, build_opener, urlopen

from api.recipe_api import RecipeApiServer
from services.auth_service import AuthService


class AuthApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.auth = AuthService(Path(self.temp_directory.name) / "auth.db")
        self.auth.create_user(
            "operator",
            "operator-secret",
            "Operator",
            {"username": "admin", "role": "Admin"},
        )
        self.auth.create_user(
            "inactive",
            "inactive-secret",
            "Operator",
            {"username": "admin", "role": "Admin"},
        )
        inactive = next(user for user in self.auth.list_users({"username": "admin", "role": "Admin"}) if user["username"] == "inactive")
        self.auth.set_active(inactive["id"], False, {"username": "admin", "role": "Admin"})
        self.server = RecipeApiServer(object(), self.auth, host="127.0.0.1", port=0)
        self.server.start()
        self.base_url = f"http://{self.server.address[0]}:{self.server.address[1]}"

    def tearDown(self) -> None:
        self.server.stop()
        self.temp_directory.cleanup()

    @staticmethod
    def _decode(response) -> dict:
        return json.loads(response.read().decode("utf-8"))

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        headers: dict[str, str] | None = None,
        opener=None,
    ) -> tuple[int, dict, object]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=body,
            headers={"Content-Type": "application/json", **(headers or {})},
            method=method,
        )
        open_url = opener.open if opener is not None else urlopen
        try:
            response = open_url(request, timeout=2)
            return response.status, self._decode(response), response
        except HTTPError as error:
            return error.code, self._decode(error), error

    def test_valid_login_bearer_and_cookie_sessions(self) -> None:
        status, login, response = self._request(
            "POST", "/api/auth/login", {"username": "operator", "password": "operator-secret"}
        )
        self.assertEqual(status, 200)
        self.assertIn("token", login)
        self.assertEqual(login["user"]["username"], "operator")
        login_json = json.dumps(login).lower()
        self.assertNotIn("operator-secret", login_json)
        self.assertNotIn("password_hash", login_json)
        token = login["token"]

        status, current, _ = self._request(
            "GET", "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(current["username"], "operator")

        cookie_jar = CookieJar()
        cookie_opener = build_opener(__import__("urllib.request", fromlist=["HTTPCookieProcessor"]).HTTPCookieProcessor(cookie_jar))
        status, cookie_login, _ = self._request(
            "POST", "/api/auth/login", {"username": "operator", "password": "operator-secret"}, opener=cookie_opener
        )
        self.assertEqual(status, 200)
        self.assertTrue(cookie_jar)
        status, cookie_current, _ = self._request("GET", "/api/auth/me", opener=cookie_opener)
        self.assertEqual(status, 200)
        self.assertEqual(cookie_current["username"], "operator")
        self.assertNotEqual(cookie_login["token"], token)
        self.assertIsNotNone(response)

    def test_invalid_and_inactive_logins_are_rejected_without_secret_logging(self) -> None:
        secret = "incorrect-secret"
        logger = logging.getLogger("services.auth_service")
        with self.assertLogs(logger, level="INFO") as captured:
            status, body, _ = self._request(
                "POST", "/api/auth/login", {"username": "operator", "password": secret}
            )
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "Invalid username or password")
        self.assertNotIn(secret, "\n".join(captured.output))
        self.assertNotIn("password_hash", json.dumps(body).lower())

        status, body, _ = self._request(
            "POST", "/api/auth/login", {"username": "inactive", "password": "inactive-secret"}
        )
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "Invalid username or password")
        self.assertNotIn("password_hash", json.dumps(body).lower())

    def test_logout_invalidates_bearer_and_cookie_sessions(self) -> None:
        status, login, _ = self._request(
            "POST", "/api/auth/login", {"username": "operator", "password": "operator-secret"}
        )
        self.assertEqual(status, 200)
        token = login["token"]
        status, _, _ = self._request(
            "POST", "/api/auth/logout", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(status, 200)
        status, _, _ = self._request(
            "GET", "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(status, 403)

        cookie_jar = CookieJar()
        from urllib.request import HTTPCookieProcessor

        cookie_opener = build_opener(HTTPCookieProcessor(cookie_jar))
        status, _, _ = self._request(
            "POST", "/api/auth/login", {"username": "operator", "password": "operator-secret"}, opener=cookie_opener
        )
        self.assertEqual(status, 200)
        status, _, _ = self._request("POST", "/api/auth/logout", opener=cookie_opener)
        self.assertEqual(status, 200)
        status, _, _ = self._request("GET", "/api/auth/me", opener=cookie_opener)
        self.assertEqual(status, 403)

    def test_expired_session_is_rejected_with_deterministic_clock(self) -> None:
        issued_at = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
        expired_at = issued_at + timedelta(hours=8, seconds=1)
        with patch("services.auth_service.datetime") as clock:
            clock.now.side_effect = [issued_at, expired_at]
            status, login, _ = self._request(
                "POST", "/api/auth/login", {"username": "operator", "password": "operator-secret"}
            )
            self.assertEqual(status, 200)
            self.assertEqual(login["expires_at"], (issued_at + timedelta(hours=8)).isoformat())
            status, _, _ = self._request(
                "GET", "/api/auth/me", headers={"Authorization": f"Bearer {login['token']}"}
            )
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
