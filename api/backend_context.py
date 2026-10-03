from __future__ import annotations

from typing import Any

from services.backend_poller import BackendPoller
from services.config_service import ConfigService
from services.database_service import DatabaseService
from services.plc_data_service import PLCDataService
from services.run_service import RunService


class BackendContext:
    """Small application façade used by HTTP handlers."""

    def __init__(self, config_service: ConfigService, database_service: DatabaseService,
                 plc_service: PLCDataService, run_service: RunService,
                 poller: BackendPoller, inspection_store=None,
                 recipe_service=None, auth_service=None) -> None:
        self.config_service = config_service
        self.database_service = database_service
        self.plc_service = plc_service
        self.run_service = run_service
        self.poller = poller
        self.inspection_store = inspection_store
        self.recipe_service = recipe_service
        self.auth_service = auth_service
        self.sql_connected: bool | None = None
        self.plc_connected: bool | None = None

    def health_status(self, recipe_service=None, auth_service=None) -> dict[str, object]:
        """Report backend construction readiness, independent of connectivity."""
        required = {
            "config_service": self.config_service,
            "database_service": self.database_service,
            "plc_service": self.plc_service,
            "run_service": self.run_service,
            "inspection_store": self.inspection_store,
            "recipe_service": recipe_service if recipe_service is not None else self.recipe_service,
            "auth_service": auth_service if auth_service is not None else self.auth_service,
            "backend_poller": self.poller,
        }
        missing = sorted(name for name, service in required.items() if service is None)
        return {"initialized": not missing, "missing_services": missing}

    def operation_state(self) -> dict[str, Any]:
        state = self.run_service.state_snapshot()
        state["sql"] = self.sql_status()
        state["plc"] = self.plc_status()
        return state

    def sql_status(self) -> dict[str, Any]:
        return {"connected": self.sql_connected}

    def plc_status(self) -> dict[str, Any]:
        status = self.poller.status()
        status["connected"] = self.plc_connected if self.plc_connected is not None else status["connected"]
        return status

    def test_sql(self) -> dict[str, Any]:
        try:
            self.database_service.test_connection()
        except Exception as error:
            self.sql_connected = False
            return {"connected": False, "error": str(error)}
        self.sql_connected = True
        return {"connected": True}

    def test_plc(self) -> dict[str, Any]:
        try:
            self.plc_service.check_connection()
        except Exception as error:
            self.plc_connected = False
            return {"connected": False, "error": str(error)}
        self.plc_connected = True
        return {"connected": True}

    def poll_status_changed(self, connected: bool) -> None:
        self.plc_connected = connected

    def settings(self) -> dict[str, Any]:
        db = self.database_service.config
        plc = self.plc_service.config
        return {
            "database": {"server": db.server, "database": db.database,
                         "driver": db.driver, "authentication": db.authentication,
                         "trust_server_certificate": db.trust_server_certificate,
                         "connection_timeout": db.connection_timeout},
            "plc": {"ip": plc.ip_address, "poll_interval_seconds": plc.poll_interval_seconds,
                    "connection_check_interval_seconds": plc.connection_check_interval_seconds},
        }

    def update_settings(self, database: dict[str, Any], plc: dict[str, Any]) -> dict[str, Any]:
        self.config_service.save_runtime_settings(database, plc)
        self.database_service.config = self.config_service.load_database_config()
        self.plc_service.config = self.config_service.load_plc_config()
        self.poller.interval_seconds = max(0.25, self.plc_service.config.poll_interval_seconds)
        return self.settings()
