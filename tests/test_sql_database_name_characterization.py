"""Characterization of configured versus hard-coded SQL database names."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services.config_service import DatabaseConfig
from services.database_service import DatabaseService


class _Cursor:
    def __init__(self, capture: dict) -> None:
        self.capture = capture

    def execute(self, sql, parameter):
        self.capture["sql"] = sql
        self.capture["parameter"] = parameter
        return self

    def fetchall(self):
        return []

    def fetchone(self):
        return (1,)


class _Connection:
    def __init__(self, capture: dict) -> None:
        self.capture = capture

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return _Cursor(self.capture)


class SqlDatabaseNameCharacterizationTests(unittest.TestCase):
    def test_lookup_query_ignores_configured_database_name(self) -> None:
        capture: dict = {}
        config = DatabaseConfig(
            server="fake-server",
            database="ConfiguredDb",
            driver="Fake Driver",
            authentication="windows",
            trust_server_certificate=True,
            connection_timeout=5,
            connection_check_interval_seconds=60,
        )
        service = DatabaseService(config)
        with patch("services.database_service.pyodbc.connect", return_value=_Connection(capture)) as connect:
            self.assertEqual(service.fetch_run_rows("RUN-001"), [])

        connect.assert_called_once_with(config.connection_string, timeout=5)
        self.assertEqual(capture["parameter"], "RUN-001")
        self.assertIn("[workflow-u-woodlands-sg-new]", capture["sql"])
        self.assertNotIn("[ConfiguredDb]", capture["sql"])


if __name__ == "__main__":
    unittest.main()

