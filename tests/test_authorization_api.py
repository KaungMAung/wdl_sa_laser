"""HTTP-boundary role authorization tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from api.recipe_api import RecipeApiServer
from services.auth_service import AuthService


class _RoleBackend:
    """Minimal backend façade for authorization-only route tests."""

    def operation_state(self):
        return {"lots": []}

    def plc_status(self):
        return {"connected": False}

    def sql_status(self):
        return {"connected": False}

    def settings(self):
        return {"database": {}, "plc": {}}


class AuthorizationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.auth = AuthService(Path(self.temp_directory.name) / "auth.db")
        admin = {"username": "admin", "role": "Admin"}
        self.auth.create_user("engineer", "engineer-secret", "Engineer", admin)
        self.auth.create_user("operator", "operator-secret", "Operator", admin)
        service = type("RecipeServiceFake", (), {"list": lambda _self, _search: []})()
        self.server = RecipeApiServer(service, self.auth, host="127.0.0.1", port=0, backend=_RoleBackend())
        self.server.start()
        self.base_url = f"http://{self.server.address[0]}:{self.server.address[1]}"

    def tearDown(self) -> None:
        self.server.stop()
        self.temp_directory.cleanup()

    def _request(self, method: str, path: str, token: str | None = None) -> tuple[int, dict]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        request = Request(self.base_url + path, headers=headers, method=method)
        try:
            with urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def _token(self, username: str, password: str) -> str:
        request = Request(
            self.base_url + "/api/auth/login",
            data=json.dumps({"username": username, "password": password}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))["token"]

    def test_production_routes_allow_all_roles(self) -> None:
        for username, password in (
            ("admin", "ChangeMe123!"),
            ("engineer", "engineer-secret"),
            ("operator", "operator-secret"),
        ):
            token = self._token(username, password)
            status, _ = self._request("GET", "/api/operation/state", token)
            self.assertEqual(status, 200, username)

    def test_recipe_and_settings_routes_allow_admin_and_engineer_only(self) -> None:
        for username, password in (("admin", "ChangeMe123!"), ("engineer", "engineer-secret")):
            token = self._token(username, password)
            recipe_status, _ = self._request("GET", "/api/recipes", token)
            settings_status, _ = self._request("GET", "/api/settings", token)
            self.assertEqual(recipe_status, 200, username)
            self.assertEqual(settings_status, 200, username)

        operator_token = self._token("operator", "operator-secret")
        recipe_status, _ = self._request("GET", "/api/recipes", operator_token)
        settings_status, _ = self._request("GET", "/api/settings", operator_token)
        self.assertEqual(recipe_status, 403)
        self.assertEqual(settings_status, 403)

    def test_user_management_is_admin_only(self) -> None:
        admin_status, _ = self._request("GET", "/api/users", self._token("admin", "ChangeMe123!"))
        engineer_status, _ = self._request("GET", "/api/users", self._token("engineer", "engineer-secret"))
        operator_status, _ = self._request("GET", "/api/users", self._token("operator", "operator-secret"))
        unauthenticated_status, _ = self._request("GET", "/api/users")
        self.assertEqual(admin_status, 200)
        self.assertEqual(engineer_status, 403)
        self.assertEqual(operator_status, 403)
        self.assertEqual(unauthenticated_status, 403)


if __name__ == "__main__":
    unittest.main()

