"""HTTP-boundary Recipe CRUD tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from api.recipe_api import RecipeApiServer
from services.auth_service import AuthService
from services.recipe_service import RecipeService


class RecipeApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        root = Path(self.temp_directory.name)
        self.service = RecipeService(root / "recipes.db", root / "missing.xlsx")
        self.auth = AuthService(root / "users.db")
        self.server = RecipeApiServer(self.service, self.auth, host="127.0.0.1", port=0)
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

    def _token(self) -> str:
        status, body = self._request("POST", "/api/auth/login", {"username": "admin", "password": "ChangeMe123!"})
        self.assertEqual(status, 200)
        return body["token"]

    def test_recipe_crud_duplicate_and_material_lookup(self) -> None:
        token = self._token()
        status, created = self._request(
            "POST", "/api/recipes",
            {"material_no": "000123", "polisher_recipe_id": 5, "engraver_recipe_id": 12, "recipe_name": "TEST", "carrier_type": "CT"},
            token,
        )
        self.assertEqual(status, 201)
        row_id = created["id"]
        self.assertEqual(created["material_no"], "000123")
        self.assertEqual(created["polisher_recipe_id"], 5)
        self.assertNotIn("password_hash", json.dumps(created))

        status, listed = self._request("GET", "/api/recipes?search=TEST", token=token)
        self.assertEqual(status, 200)
        self.assertEqual([row["material_no"] for row in listed], ["000123"])

        status, lookup = self._request("GET", f"/api/recipes/by-material/{quote('000123')}", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(lookup["engraver_recipe_id"], 12)

        status, duplicate = self._request(
            "POST", "/api/recipes",
            {"material_no": "000123", "polisher_recipe_id": 6}, token,
        )
        self.assertEqual(status, 409)
        self.assertIn("already exists", duplicate["error"])

        status, updated = self._request(
            "PUT", f"/api/recipes/{row_id}",
            {"material_no": "000123", "polisher_recipe_id": 6, "engraver_recipe_id": 13, "recipe_name": "UPDATED", "carrier_type": "CJ"},
            token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["polisher_recipe_id"], 6)
        self.assertEqual(updated["recipe_name"], "UPDATED")

        status, deleted = self._request("DELETE", f"/api/recipes/{row_id}", token=token)
        self.assertEqual(status, 200)
        self.assertTrue(deleted["deleted"])
        status, _ = self._request("GET", f"/api/recipes/by-material/{quote('000123')}", token=token)
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()

