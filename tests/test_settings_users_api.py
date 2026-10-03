"""HTTP-boundary Settings and user administration tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from api.backend_context import BackendContext
from api.recipe_api import RecipeApiServer
from services.auth_service import AuthService


class _Config:
    def __init__(self) -> None:
        self.server = "fake-server"
        self.database = "fake-db"
        self.driver = "Fake Driver"
        self.authentication = "windows"
        self.trust_server_certificate = True
        self.connection_timeout = 5
        self.connection_check_interval_seconds = 60
        self.ip_address = "192.0.2.10"
        self.poll_interval_seconds = 2
        self.status_mapping = {}
        self.result_mapping = {}


class _ConfigService:
    def __init__(self) -> None:
        self.saved: list[tuple[dict, dict]] = []
        self.database = _Config()
        self.plc = _Config()

    def save_runtime_settings(self, database, plc) -> None:
        self.saved.append((database, plc))

    def load_database_config(self):
        return self.database

    def load_plc_config(self):
        return self.plc


class _Database:
    def __init__(self) -> None:
        self.config = _Config()
        self.test_calls = 0

    def test_connection(self) -> None:
        self.test_calls += 1


class _PLC:
    def __init__(self) -> None:
        self.config = _Config()
        self.test_calls = 0

    def check_connection(self) -> bool:
        self.test_calls += 1
        return True


class _Poller:
    def __init__(self) -> None:
        self.interval_seconds = 2

    def status(self):
        return {"connected": True, "running": False, "last_error": None, "last_poll_at": None}


class _Run:
    def state_snapshot(self):
        return {"lots": []}


class SettingsUsersApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        root = Path(self.temp_directory.name)
        self.auth = AuthService(root / "users.db")
        self.config_service = _ConfigService()
        self.database = _Database()
        self.plc = _PLC()
        self.poller = _Poller()
        backend = BackendContext(
            self.config_service,
            self.database,
            self.plc,
            _Run(),
            self.poller,
            inspection_store=object(),
            recipe_service=object(),
            auth_service=self.auth,
        )
        service = type("RecipeServiceFake", (), {"list": lambda _self, _search: []})()
        self.server = RecipeApiServer(service, self.auth, host="127.0.0.1", port=0, backend=backend)
        self.server.start()
        self.base_url = f"http://{self.server.address[0]}:{self.server.address[1]}"

    def tearDown(self) -> None:
        self.server.stop()
        self.temp_directory.cleanup()

    def _request(self, method: str, path: str, payload: dict | None = None, token: str | None = None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def _token(self, username="admin", password="ChangeMe123!") -> str:
        status, body = self._request("POST", "/api/auth/login", {"username": username, "password": password})
        self.assertEqual(status, 200)
        return body["token"]

    def test_admin_settings_update_and_connection_tests_delegate_to_backend(self) -> None:
        token = self._token()
        status, settings = self._request("GET", "/api/settings", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(settings["database"]["database"], "fake-db")

        status, updated = self._request(
            "PUT", "/api/settings",
            {"database": {"database": "updated-db"}, "plc": {"poll_interval_seconds": 3}}, token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(self.config_service.saved), 1)
        self.assertEqual(self.config_service.saved[0][0]["database"], "updated-db")
        self.assertEqual(updated["database"]["database"], "fake-db")

        status, _ = self._request("POST", "/api/sql/test", token=token)
        self.assertEqual(status, 200)
        status, _ = self._request("POST", "/api/plc/test", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(self.database.test_calls, 1)
        self.assertEqual(self.plc.test_calls, 1)

    def test_admin_user_management_and_last_admin_protection(self) -> None:
        token = self._token()
        status, users = self._request("GET", "/api/users", token=token)
        self.assertEqual(status, 200)
        self.assertTrue(users)
        self.assertNotIn("password_hash", json.dumps(users))

        status, created = self._request(
            "POST", "/api/users",
            {"username": "engineer", "password": "engineer-secret", "role": "Engineer"}, token,
        )
        self.assertEqual(status, 201)
        self.assertNotIn("password_hash", json.dumps(created))
        user_id = created["id"]

        status, updated = self._request(
            "PUT", f"/api/users/{user_id}", {"username": "engineer2", "role": "Engineer", "is_active": True}, token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["username"], "engineer2")
        status, _ = self._request("POST", f"/api/users/{user_id}/reset-password", {"password": "new-secret"}, token)
        self.assertEqual(status, 200)
        status, _ = self._request("POST", f"/api/users/{user_id}/disable", token=token)
        self.assertEqual(status, 200)
        status, _ = self._request("POST", f"/api/users/{user_id}/enable", token=token)
        self.assertEqual(status, 200)

        admin_id = users[0]["id"]
        status, body = self._request("POST", f"/api/users/{admin_id}/disable", token=token)
        self.assertEqual(status, 400)
        self.assertIn("At least one active Admin", body["error"])

    def test_operator_cannot_change_settings_or_users(self) -> None:
        admin = {"username": "admin", "role": "Admin"}
        self.auth.create_user("operator", "operator-secret", "Operator", admin)
        token = self._token("operator", "operator-secret")
        settings_status, _ = self._request("GET", "/api/settings", token=token)
        users_status, _ = self._request("GET", "/api/users", token=token)
        self.assertEqual(settings_status, 403)
        self.assertEqual(users_status, 403)


if __name__ == "__main__":
    unittest.main()

