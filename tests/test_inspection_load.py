"""Inspection Start/Current/Event load transaction tests."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from models.production_run import ProductionRecord, ProductionRun
from models.tray_data import TrayData, TrayPartData
from services.inspection_store import InspectionStore
from tests.support.fakes import FakeLotState, FakeRecipeService


def _two_disc_trays() -> list[TrayData]:
    parts = (
        TrayPartData(None, "SER-001", None, "NONE", "READY"),
        TrayPartData(None, "SER-002", None, "NONE", "READY"),
        *(TrayPartData(None, "", None, "NONE", "READY") for _ in range(5)),
    )
    empty = tuple(TrayPartData(None, "", None, "NONE", "READY") for _ in range(7))
    return [
        TrayData(0, False, "RUN-001", "", "D-001", "MAT-001", True, parts),
        *(TrayData(index, False, "", "", "", "", False, empty) for index in range(1, 8)),
    ]


def _lot_state() -> FakeLotState:
    records = (
        ProductionRecord("S122L", "MAT-001", "RUN-001", "D-001", "SER-001"),
        ProductionRecord("S122L", "MAT-001", "RUN-001", "D-001", "SER-002"),
    )
    production = ProductionRun("S122L", "MAT-001", "RUN-001", "D-001", records, ("SER-001", "SER-002"))
    return FakeLotState("RUN-001", "INSP-001", "SER-001", production)


class _FailingEventStore(InspectionStore):
    @staticmethod
    def _event(*_args, **_kwargs):
        raise RuntimeError("injected event failure")


class InspectionLoadTests(unittest.TestCase):
    @staticmethod
    def _counts(path: Path) -> dict[str, int]:
        connection = sqlite3.connect(path)
        try:
            return {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("Inspection_Start", "Inspection_Current", "Inspection_Event")
            }
        finally:
            connection.close()

    def test_load_creates_matching_start_current_and_load_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inspection.db"
            store = InspectionStore(path, FakeRecipeService())
            result = store.load_snapshot(
                _two_disc_trays(), {1: _lot_state()}, {"username": "operator", "role": "Operator"}
            )

            self.assertEqual(result["new_discs"], 2)
            self.assertEqual(self._counts(path), {"Inspection_Start": 2, "Inspection_Current": 2, "Inspection_Event": 2})
            connection = sqlite3.connect(path)
            connection.row_factory = sqlite3.Row
            try:
                start = connection.execute("SELECT * FROM Inspection_Start ORDER BY Part_Index").fetchall()
                current = connection.execute("SELECT * FROM Inspection_Current ORDER BY Part_Index").fetchall()
                events = connection.execute("SELECT Event_Type, Username, Role FROM Inspection_Event").fetchall()
            finally:
                connection.close()
            self.assertEqual([row["Serial_No"] for row in start], ["SER-001", "SER-002"])
            self.assertEqual([row["Serial_No"] for row in current], ["SER-001", "SER-002"])
            self.assertEqual([row["Disc_ID"] for row in start], [row["Disc_ID"] for row in current])
            self.assertEqual({row["Event_Type"] for row in events}, {"LOAD_DATA"})
            self.assertTrue(all(row["Username"] == "operator" and row["Role"] == "Operator" for row in events))

    def test_load_failure_rolls_back_start_current_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inspection.db"
            store = _FailingEventStore(path, FakeRecipeService())
            with self.assertRaisesRegex(RuntimeError, "injected event failure"):
                store.load_snapshot(
                    _two_disc_trays(), {1: _lot_state()}, {"username": "operator", "role": "Operator"}
                )
            self.assertEqual(self._counts(path), {"Inspection_Start": 0, "Inspection_Current": 0, "Inspection_Event": 0})


if __name__ == "__main__":
    unittest.main()

