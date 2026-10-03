"""HTTP-boundary checks for the backend health contract."""

from __future__ import annotations

import json
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from api.backend_context import BackendContext
from api.recipe_api import RecipeApiServer


class ApiHealthTests(unittest.TestCase):
    @staticmethod
    def _server(context: BackendContext | None) -> RecipeApiServer:
        return RecipeApiServer(object(), object(), host="127.0.0.1", port=0, backend=context)

    @staticmethod
    def _get(server: RecipeApiServer) -> tuple[int, dict]:
        with urlopen(f"http://{server.address[0]}:{server.address[1]}/health", timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_is_ok_when_services_are_constructed_even_if_connections_are_down(self) -> None:
        context = BackendContext(
            object(), object(), object(), object(), object(),
            inspection_store=object(), recipe_service=object(), auth_service=object(),
        )
        context.sql_connected = False
        context.plc_connected = False
        server = self._server(context)
        server.start()
        try:
            status, body = self._get(server)
        finally:
            server.stop()

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["initialized"])
        self.assertEqual(body["missing_services"], [])

    def test_health_is_unavailable_when_required_service_is_missing(self) -> None:
        context = BackendContext(object(), object(), object(), object(), object())
        server = self._server(context)
        server.start()
        try:
            with self.assertRaises(HTTPError) as raised:
                self._get(server)
            self.assertEqual(raised.exception.code, 503)
            body = json.loads(raised.exception.read().decode("utf-8"))
        finally:
            server.stop()

        self.assertEqual(body["status"], "unhealthy")
        self.assertFalse(body["initialized"])
        self.assertIn("inspection_store", body["missing_services"])


if __name__ == "__main__":
    unittest.main()

