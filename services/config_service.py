from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    server: str
    database: str
    driver: str
    authentication: str
    trust_server_certificate: bool
    connection_timeout: int
    connection_check_interval_seconds: float

    @property
    def connection_string(self) -> str:
        parts = [
            f"DRIVER={{{self.driver}}}",
            f"SERVER={self.server}",
            f"DATABASE={self.database}",
        ]
        if self.authentication.lower() == "windows":
            parts.append("Trusted_Connection=yes")
        else:
            raise ValueError(
                "Only Windows authentication is supported by this Phase 1 configuration."
            )
        parts.append(
            "TrustServerCertificate="
            + ("yes" if self.trust_server_certificate else "no")
        )
        return ";".join(parts) + ";"


@dataclass(frozen=True, slots=True)
class PLCConfig:
    ip_address: str
    poll_interval_seconds: float
    connection_check_interval_seconds: float
    status_mapping: dict[str, str]
    result_mapping: dict[str, str]


class ConfigService:
    def __init__(self, config_path: Path | None = None) -> None:
        project_root = Path(__file__).resolve().parents[1]
        self.config_path = config_path or project_root / "config" / "config.yaml"

    def load_database_config(self) -> DatabaseConfig:
        with self.config_path.open("r", encoding="utf-8") as config_file:
            data: dict[str, Any] = yaml.safe_load(config_file) or {}

        database = data.get("database")
        if not isinstance(database, dict):
            raise ValueError("Missing 'database' section in config/config.yaml")

        required = ("server", "database", "driver", "authentication")
        missing = [name for name in required if not str(database.get(name, "")).strip()]
        if missing:
            raise ValueError(
                "Missing database configuration value(s): " + ", ".join(missing)
            )

        connection_check_interval = float(
            database.get("connection_check_interval_seconds", 60)
        )
        if connection_check_interval <= 0:
            raise ValueError("Database connection check interval must be positive")
        return DatabaseConfig(
            server=str(database["server"]).strip(),
            database=str(database["database"]).strip(),
            driver=str(database["driver"]).strip(),
            authentication=str(database["authentication"]).strip(),
            trust_server_certificate=_as_bool(
                database.get("trust_server_certificate", True)
            ),
            connection_timeout=int(database.get("connection_timeout", 5)),
            connection_check_interval_seconds=connection_check_interval,
        )

    def load_plc_config(self) -> PLCConfig:
        with self.config_path.open("r", encoding="utf-8") as config_file:
            data: dict[str, Any] = yaml.safe_load(config_file) or {}

        plc = data.get("plc")
        if not isinstance(plc, dict):
            raise ValueError("Missing 'plc' section in config/config.yaml")
        ip_address = str(plc.get("ip", plc.get("ip_address", ""))).strip()
        if not ip_address:
            raise ValueError("Missing PLC configuration value: ip_address")
        poll_interval = float(plc.get("poll_interval_seconds", 2))
        connection_check_interval = float(
            plc.get(
                "connection_check_interval_seconds",
                plc.get("reconnect_interval_seconds", 60),
            )
        )
        if poll_interval <= 0 or connection_check_interval <= 0:
            raise ValueError("PLC polling and connection check intervals must be positive")
        return PLCConfig(
            ip_address=ip_address,
            poll_interval_seconds=poll_interval,
            connection_check_interval_seconds=connection_check_interval,
            status_mapping=_string_mapping(plc.get("status_mapping", {})),
            result_mapping=_string_mapping(plc.get("result_mapping", {})),
        )

    def save_runtime_settings(self, database: dict[str, Any], plc: dict[str, Any]) -> None:
        with self.config_path.open("r", encoding="utf-8") as config_file:
            data: dict[str, Any] = yaml.safe_load(config_file) or {}
        data.setdefault("database", {}).update(database)
        data.setdefault("plc", {}).update(plc)
        with self.config_path.open("w", encoding="utf-8") as config_file:
            yaml.safe_dump(data, config_file, sort_keys=False)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "1", "on"}


def _string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("PLC Result/Status mappings must be key/value objects")
    return {str(key).strip(): str(label).strip() for key, label in value.items()}
