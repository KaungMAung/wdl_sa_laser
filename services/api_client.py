"""Centralized HTTP client for the Phase 4 desktop client."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote_plus


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class BackendDisconnected(ApiError):
    pass


class ApiClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8765", timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token: str | None = None
        self.user: dict[str, Any] | None = None

    @property
    def authenticated(self) -> bool:
        return bool(self.token and self.user)

    def request(self, method: str, path: str, payload: Any = None, *, auth: bool = True) -> Any:
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(self.base_url + path, data=body, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw else None
        except HTTPError as error:
            try:
                details = json.loads(error.read().decode("utf-8"))
                message = details.get("error", str(error)) if isinstance(details, dict) else str(error)
            except Exception:
                message = str(error)
            if error.code == 401:
                self.token, self.user = None, None
            raise ApiError(message, error.code) from error
        except (URLError, TimeoutError, OSError) as error:
            raise BackendDisconnected(f"Backend disconnected: {error}") from error

    def login(self, username: str, password: str) -> dict[str, Any]:
        response = self.request("POST", "/api/auth/login", {"username": username, "password": password}, auth=False)
        self.token = response["token"]
        self.user = response["user"]
        return self.user

    def logout(self) -> None:
        if self.token:
            try:
                self.request("POST", "/api/auth/logout")
            except ApiError:
                # A lost backend must not prevent a local GUI logout.
                pass
            finally:
                self.token, self.user = None, None

    def me(self) -> dict[str, Any]:
        self.user = self.request("GET", "/api/auth/me")
        return self.user

    def operation_state(self) -> dict[str, Any]: return self.request("GET", "/api/operation/state")
    def scan(self, lot_number: int, stage: str, value: str) -> dict[str, Any]: return self.request("POST", "/api/operation/scan", {"lot_number": lot_number, "stage": stage, "value": value})
    def load_data(self) -> dict[str, Any]: return self.request("POST", "/api/operation/load-data", {})
    def clear_lot(self, lot_number: int, confirmed: bool = True) -> dict[str, Any]: return self.request("POST", "/api/operation/clear-lot", {"lot_number": lot_number, "confirmed": confirmed})
    def clear_all(self, confirmed: bool = True) -> dict[str, Any]: return self.request("POST", "/api/operation/clear-all", {"confirmed": confirmed})
    def end_run(self, confirmed: bool = True) -> dict[str, Any]: return self.request("POST", "/api/operation/end-run", {"confirmed": confirmed})
    def plc_status(self) -> dict[str, Any]: return self.request("GET", "/api/plc/status")
    def sql_status(self) -> dict[str, Any]: return self.request("GET", "/api/sql/status")
    def test_plc(self) -> dict[str, Any]: return self.request("POST", "/api/plc/test", {})
    def test_sql(self) -> dict[str, Any]: return self.request("POST", "/api/sql/test", {})
    def settings(self) -> dict[str, Any]: return self.request("GET", "/api/settings")
    def update_settings(self, database: dict[str, Any], plc: dict[str, Any]) -> dict[str, Any]: return self.request("PUT", "/api/settings", {"database": database, "plc": plc})
    def recipes(self, search: str = "") -> list[dict[str, Any]]: return self.request("GET", "/api/recipes" + (f"?search={quote_plus(search)}" if search else ""))
    def recipe(self, row_id: int) -> dict[str, Any]: return self.request("GET", f"/api/recipes/{row_id}")
    def create_recipe(self, payload: dict[str, Any]) -> dict[str, Any]: return self.request("POST", "/api/recipes", payload)
    def update_recipe(self, row_id: int, payload: dict[str, Any]) -> dict[str, Any]: return self.request("PUT", f"/api/recipes/{row_id}", payload)
    def delete_recipe(self, row_id: int) -> dict[str, Any]: return self.request("DELETE", f"/api/recipes/{row_id}")
    def users(self) -> list[dict[str, Any]]: return self.request("GET", "/api/users")
    def create_user(self, payload: dict[str, Any]) -> dict[str, Any]: return self.request("POST", "/api/users", payload)
    def update_user(self, row_id: int, payload: dict[str, Any]) -> dict[str, Any]: return self.request("PUT", f"/api/users/{row_id}", payload)
    def user_action(self, row_id: int, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]: return self.request("POST", f"/api/users/{row_id}/{action}", payload or {})
