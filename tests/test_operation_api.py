"""HTTP-boundary operation state and scan workflow tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from api.backend_context import BackendContext
from api.recipe_api import RecipeApiServer
from services.auth_service import AuthService
from services.inspection_store import InspectionStore
from services.run_service import RunService
from tests.support.fakes import FakeDatabaseService, FakePLCDataService, FakeRecipeService


class _PollerFake:
    def status(self):
        return {"connected": False, "running": False, "last_error": None, "last_poll_at": None}


class OperationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_directory.name) / "app.db"
        rows = [
            ("S122L", "MAT-001", "RUN-001", "D-001", "SER-001"),
            ("S122L", "MAT-001", "RUN-001", "D-001", "SER-002"),
        ]
        database = FakeDatabaseService({"RUN-001": rows})
        recipes = FakeRecipeService()
        inspection = InspectionStore(database_path, recipes)
        self.run_service = RunService(database, FakePLCDataService(), recipes, inspection)
        self.auth = AuthService(Path(self.temp_directory.name) / "users.db")
        context = BackendContext(
            object(), database, object(), self.run_service, _PollerFake(),
            inspection_store=inspection, recipe_service=recipes, auth_service=self.auth,
        )
        service = type("RecipeServiceFake", (), {"list": lambda _self, _search: []})()
        self.server = RecipeApiServer(service, self.auth, host="127.0.0.1", port=0, backend=context)
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
        status, body = self._request(
            "POST", "/api/auth/login", {"username": "admin", "password": "ChangeMe123!"}
        )
        self.assertEqual(status, 200)
        return body["token"]

    def test_scan_sequence_returns_authoritative_state_and_rejects_invalid_duplicates(self) -> None:
        token = self._token()
        status, body = self._request(
            "POST", "/api/operation/scan",
            {"lot_number": 1, "stage": "run", "value": " RUN-001 "}, token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["lots"][0]["run_no"], "RUN-001")
        self.assertEqual(body["lots"][0]["expected_count"], 2)

        status, _ = self._request(
            "POST", "/api/operation/scan",
            {"lot_number": 1, "stage": "inspection_lot", "value": "INSP-001"}, token,
        )
        self.assertEqual(status, 200)
        status, body = self._request(
            "POST", "/api/operation/scan",
            {"lot_number": 1, "stage": "inspection_point", "value": "SER-001"}, token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["lots"][0]["scanned_count"], 1)

        status, body = self._request(
            "POST", "/api/operation/scan",
            {"lot_number": 1, "stage": "serial", "value": "SER-002"}, token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["lots"][0]["scanned_count"], 2)

        status, error = self._request(
            "POST", "/api/operation/scan",
            {"lot_number": 1, "stage": "serial", "value": "SER-002"}, token,
        )
        self.assertEqual(status, 400)
        self.assertIn("ALREADY SCANNED", error["error"])

        status, error = self._request(
            "POST", "/api/operation/scan",
            {"lot_number": 1, "stage": "serial", "value": "NOT-IN-RUN"}, token,
        )
        self.assertEqual(status, 400)
        self.assertIn("INVALID SERIAL", error["error"])

    def test_operation_state_route_returns_backend_snapshot(self) -> None:
        token = self._token()
        status, body = self._request("GET", "/api/operation/state", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(len(body["lots"]), 4)
        self.assertIn("sql", body)
        self.assertIn("plc", body)


if __name__ == "__main__":
    unittest.main()

