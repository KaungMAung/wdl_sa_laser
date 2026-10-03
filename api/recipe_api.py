from __future__ import annotations

import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, unquote, urlparse

from services.recipe_service import (
    RecipeConflictError,
    RecipeService,
    RecipeValidationError,
)
from services.auth_service import AuthError, AuthService, AuthorizationError

LOGGER = logging.getLogger(__name__)


class _Handler(BaseHTTPRequestHandler):
    """Recipe mapping REST endpoints keyed by SKU / Material No."""

    service: RecipeService
    auth: AuthService
    backend = None

    def log_message(self, format: str, *args) -> None:
        LOGGER.info("Recipe API: " + format, *args)

    def _send(self, status: int, payload) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _token(self) -> str:
        authorization = self.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            return authorization[7:].strip()
        cookies = self.headers.get("Cookie", "")
        for item in cookies.split(";"):
            key, _, value = item.strip().partition("=")
            if key == "lasermaker_session": return value
        return ""

    def _require(self, *roles):
        return self.auth.require(self._token(), *roles)

    def _backend_require(self, *roles):
        return self.auth.require(self._token(), *roles)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError) as error:
            raise RecipeValidationError("Request body must be valid JSON") from error
        if not isinstance(body, dict):
            raise RecipeValidationError("Request body must be a JSON object")
        return body

    def _save_arguments(self, body: dict) -> tuple:
        return (
            body.get("material_no", ""),
            body.get("polisher_recipe_id"),
            body.get("engraver_recipe_id"),
            body.get("recipe_name", ""),
            body.get("carrier_type", ""),
            body.get("prod_name", ""),
            body.get("engraved_name", ""),
        )

    def do_GET(self) -> None:  # noqa: N802 - Qt/http.server API name
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        try:
            if path == "/health":
                health = (
                    self.backend.health_status(self.service, self.auth)
                    if self.backend is not None
                    else {"initialized": False, "missing_services": ["backend_context"]}
                )
                if not health["initialized"]:
                    self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"status": "unhealthy", **health})
                    return
                self._send(HTTPStatus.OK, {"status": "ok", **health})
                return
            if self.backend is not None and path in {
                "/api/system/status", "/api/operation/state", "/api/plc/status",
                "/api/sql/status", "/api/settings",
            }:
                self._backend_require("Admin", "Engineer", "Operator")
                if path == "/api/system/status":
                    self._send(HTTPStatus.OK, {"status": "ok", "operation": self.backend.operation_state()})
                elif path == "/api/operation/state":
                    self._send(HTTPStatus.OK, self.backend.operation_state())
                elif path == "/api/plc/status":
                    self._send(HTTPStatus.OK, self.backend.plc_status())
                elif path == "/api/sql/status":
                    self._send(HTTPStatus.OK, self.backend.sql_status())
                else:
                    self._backend_require("Admin", "Engineer")
                    self._send(HTTPStatus.OK, self.backend.settings())
                return
            if path == "/api/auth/me":
                self._send(HTTPStatus.OK, self._require("Admin", "Engineer", "Operator"))
                return
            if path == "/api/users":
                actor = self._require("Admin")
                self._send(HTTPStatus.OK, self.auth.list_users(actor))
                return
            if path == "/api/recipes":
                self._require("Admin", "Engineer")
                search = parse_qs(parsed.query).get("search", [""])[0]
                self._send(HTTPStatus.OK, self.service.list(search))
                return
            if path.startswith("/api/recipes/by-material/"):
                self._require("Admin", "Engineer", "Operator")
                material_no = unquote(path[len("/api/recipes/by-material/") :])
                row = self.service.by_material(material_no)
                self._send(
                    HTTPStatus.OK if row else HTTPStatus.NOT_FOUND,
                    row or {"error": f"No recipe mapping for Material No. {material_no}"},
                )
                return
            row_id = self._id(path)
            if row_id is not None:
                self._require("Admin", "Engineer")
                row = self.service.get(row_id)
                self._send(
                    HTTPStatus.OK if row else HTTPStatus.NOT_FOUND,
                    row or {"error": "Recipe mapping not found"},
                )
                return
            self._send(HTTPStatus.NOT_FOUND, {"error": "Not found"})
        except AuthorizationError as error:
            self._send(HTTPStatus.FORBIDDEN, {"error": str(error)})
        except Exception as error:
            LOGGER.exception("Recipe API GET failed")
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        if path == "/api/auth/login":
            try:
                body=self._body(); token,user,expires=self.auth.login(body.get("username",""),body.get("password","")); payload=json.dumps({"token":token,"user":user,"expires_at":expires.isoformat()}).encode(); self.send_response(HTTPStatus.OK); self.send_header("Content-Type","application/json"); self.send_header("Set-Cookie",f"lasermaker_session={token}; HttpOnly; SameSite=Strict; Path=/"); self.send_header("Content-Length",str(len(payload))); self.end_headers(); self.wfile.write(payload)
            except AuthError as error:self._send(HTTPStatus.UNAUTHORIZED,{"error":str(error)})
            return
        if self.backend is not None and path in {
            "/api/auth/logout", "/api/operation/scan", "/api/operation/load-data",
            "/api/operation/clear-lot", "/api/operation/clear-all",
            "/api/operation/end-run", "/api/plc/test", "/api/sql/test",
        }:
            try:
                if path == "/api/auth/logout":
                    self.auth.logout(self._token()); self._send(HTTPStatus.OK, {"logged_out": True}); return
                actor = self._backend_require("Admin", "Engineer", "Operator")
                body = self._body()
                if path == "/api/operation/scan":
                    result = self.backend.run_service.scan(int(body.get("lot_number")), str(body.get("stage", "")), str(body.get("value", "")))
                elif path == "/api/operation/load-data":
                    result = self.backend.run_service.load_data()
                elif path == "/api/operation/clear-lot":
                    result = {"result": self.backend.run_service.clear_lot(int(body.get("lot_number")), bool(body.get("confirmed", False))), "state": self.backend.operation_state()}
                elif path == "/api/operation/clear-all":
                    self.backend.run_service.clear_all_lots(); result = self.backend.operation_state()
                elif path == "/api/operation/end-run":
                    result = {"result": self.backend.run_service.end_run(bool(body.get("confirmed", False))), "state": self.backend.operation_state()}
                elif path == "/api/plc/test":
                    self._backend_require("Admin", "Engineer")
                    result = self.backend.test_plc()
                elif path == "/api/sql/test":
                    self._backend_require("Admin", "Engineer")
                    result = self.backend.test_sql()
                else:
                    result = None
                if result is not None:
                    self._send(HTTPStatus.OK, result); return
            except AuthorizationError as error:
                self._send(HTTPStatus.FORBIDDEN, {"error": str(error)}); return
            except Exception as error:
                LOGGER.exception("Backend API POST failed")
                self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)}); return
        if path == "/api/auth/logout":
            self.auth.logout(self._token()); self._send(HTTPStatus.OK,{"logged_out":True}); return
        if path == "/api/users":
            try:
                actor=self._require("Admin"); body=self._body(); self._send(HTTPStatus.CREATED,self.auth.create_user(body.get("username",""),body.get("password",""),body.get("role","Operator"),actor))
            except (AuthError,AuthorizationError) as error:self._send(HTTPStatus.BAD_REQUEST,{"error":str(error)})
            return
        if path.startswith("/api/users/"):
            try:
                actor=self._require("Admin"); parts=path.split("/"); user_id=int(parts[3]); action=parts[4] if len(parts)>4 else ""; body=self._body()
                if action=="reset-password":self.auth.reset_password(user_id,body.get("password",""),actor); result={"reset":True}
                elif action=="enable":result=self.auth.set_active(user_id,True,actor)
                elif action=="disable":result=self.auth.set_active(user_id,False,actor)
                else:raise AuthError("Unknown user action")
                self._send(HTTPStatus.OK,result)
            except (AuthError,AuthorizationError,ValueError) as error:self._send(HTTPStatus.BAD_REQUEST,{"error":str(error)})
            return
        if path != "/api/recipes":
            self._send(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        try:
            actor=self._require("Admin", "Engineer")
            created = self.service.create(*self._save_arguments(self._body()))
            self.auth.audit(actor["username"],"recipe_created",created["material_no"])
            self._send(HTTPStatus.CREATED, created)
        except RecipeConflictError as error:
            self._send(HTTPStatus.CONFLICT, {"error": str(error)})
        except RecipeValidationError as error:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except Exception as error:
            LOGGER.exception("Recipe API POST failed")
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

    def do_PUT(self) -> None:  # noqa: N802
        path=urlparse(self.path).path.rstrip("/")
        if self.backend is not None and path == "/api/settings":
            try:
                actor = self._backend_require("Admin", "Engineer")
                body = self._body()
                result = self.backend.update_settings(body.get("database", {}), body.get("plc", {}))
                self.auth.audit(actor["username"], "settings_changed", "SQL and PLC configuration")
                self._send(HTTPStatus.OK, result)
            except AuthorizationError as error:
                self._send(HTTPStatus.FORBIDDEN, {"error": str(error)})
            except Exception as error:
                self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        if path.startswith("/api/users/"):
            try:
                actor=self._require("Admin"); user_id=int(path.split("/")[3]); body=self._body(); self._send(HTTPStatus.OK,self.auth.update_user(user_id,body.get("username",""),body.get("role","Operator"),body.get("is_active",True),actor))
            except (AuthError,AuthorizationError,ValueError) as error:self._send(HTTPStatus.BAD_REQUEST,{"error":str(error)})
            return
        row_id = self._id(path)
        if row_id is None:
            self._send(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        try:
            actor=self._require("Admin", "Engineer")
            updated = self.service.update(row_id, *self._save_arguments(self._body()))
            self.auth.audit(actor["username"],"recipe_updated",updated["material_no"])
            self._send(HTTPStatus.OK, updated)
        except KeyError as error:
            self._send(HTTPStatus.NOT_FOUND, {"error": str(error)})
        except RecipeConflictError as error:
            self._send(HTTPStatus.CONFLICT, {"error": str(error)})
        except RecipeValidationError as error:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except Exception as error:
            LOGGER.exception("Recipe API PUT failed")
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

    def do_DELETE(self) -> None:  # noqa: N802
        row_id = self._id(urlparse(self.path).path.rstrip("/"))
        if row_id is None:
            self._send(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        try:
            actor=self._require("Admin", "Engineer")
            if self.service.delete(row_id):
                self.auth.audit(actor["username"],"recipe_deleted",str(row_id))
                self._send(HTTPStatus.OK, {"deleted": True, "id": row_id})
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "Recipe mapping not found"})
        except Exception as error:
            LOGGER.exception("Recipe API DELETE failed")
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

    @staticmethod
    def _id(path: str) -> int | None:
        parts = path.split("/")
        if len(parts) == 4 and parts[1:3] == ["api", "recipes"]:
            try:
                return int(parts[3])
            except ValueError:
                return None
        return None


class RecipeApiServer:
    def __init__(
        self, service: RecipeService, auth: AuthService, host: str = "127.0.0.1", port: int = 8765,
        backend=None,
    ) -> None:
        self.server = ThreadingHTTPServer((host, port), _Handler)
        self.server.RequestHandlerClass.service = service
        self.server.RequestHandlerClass.auth = auth
        self.server.RequestHandlerClass.backend = backend
        self.thread = Thread(target=self.server.serve_forever, name="recipe-api", daemon=True)

    @property
    def address(self) -> tuple[str, int]:
        return self.server.server_address[0], self.server.server_address[1]

    def start(self) -> None:
        self.thread.start()
        LOGGER.info("Recipe API listening on http://%s:%d", *self.address)

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
