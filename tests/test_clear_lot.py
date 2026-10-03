"""Clear Lot persistence and confirmation tests."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from models.production_run import ProductionRecord, ProductionRun
from models.tray_data import TrayData, TrayPartData
from services.inspection_store import InspectionStore
from tests.support.fakes import FakeLotState, FakeRecipeService


def _lot_payload(lot_number: int, serial: str, complete: bool) -> tuple[TrayData, FakeLotState]:
    tray_index = (lot_number - 1) * 2
    status = 2 if complete else None
    status_text = "PROCESSED" if complete else "READY"
    parts = (TrayPartData(None, serial, status, "NONE", status_text),) + tuple(
        TrayPartData(None, "", None, "NONE", "READY") for _ in range(6)
    )
    empty = tuple(TrayPartData(None, "", None, "NONE", "READY") for _ in range(7))
    record = ProductionRecord("S122L", "MAT-001", f"RUN-{lot_number:03d}", f"D-{lot_number:03d}", serial)
    production = ProductionRun(record.product_id, record.material_number, record.run_number, record.diamond_lot_code, (record,), (serial,))
    state = FakeLotState(record.run_number, f"INSP-{lot_number:03d}", serial, production)
    tray = TrayData(tray_index, False, record.run_number, "", record.diamond_lot_code, record.material_number, True, parts)
    other = TrayData(tray_index + 1, False, "", "", "", "", False, empty)
    return (tray, other), state


class ClearLotTests(unittest.TestCase):
    @staticmethod
    def _events(path: Path) -> list[str]:
        connection = sqlite3.connect(path)
        try:
            return [row[0] for row in connection.execute("SELECT Event_Type FROM Inspection_Event ORDER BY rowid")]
        finally:
            connection.close()

    def test_incomplete_clear_requires_confirmation_and_preserves_other_lot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inspection.db"
            store = InspectionStore(path, FakeRecipeService())
            lot1_trays, lot1_state = _lot_payload(1, "SER-001", complete=False)
            lot2_trays, lot2_state = _lot_payload(2, "SER-002", complete=False)
            trays = [*lot1_trays, *lot2_trays, *(TrayData(index, False, "", "", "", "", False, tuple(TrayPartData(None, "", None, "NONE", "READY") for _ in range(7))) for index in range(4, 8))]
            store.load_snapshot(trays, {1: lot1_state, 2: lot2_state}, {"username": "operator", "role": "Operator"})

            self.assertEqual(store.clear_lot(1, {"username": "operator", "role": "Operator"}, confirmed=False), (1, 1))
            self.assertEqual(len(store.rows_for_lot(1)), 1)
            self.assertEqual(store.clear_lot(1, {"username": "operator", "role": "Operator"}, confirmed=True), (1, 1))

            self.assertEqual(len(store.rows_for_lot(1)), 0)
            self.assertEqual(len(store.rows_for_lot(2)), 1)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM Inspection_End").fetchone()[0], 1)
            finally:
                connection.close()
            self.assertIn("LOT_CLEARED_INCOMPLETE", self._events(path))
            self.assertNotIn("RUN_ENDED", self._events(path))

    def test_complete_clear_records_lot_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inspection.db"
            store = InspectionStore(path, FakeRecipeService())
            lot_trays, state = _lot_payload(1, "SER-001", complete=True)
            trays = [*lot_trays, *(TrayData(index, False, "", "", "", "", False, tuple(TrayPartData(None, "", None, "NONE", "READY") for _ in range(7))) for index in range(2, 8))]
            store.load_snapshot(trays, {1: state}, {"username": "operator", "role": "Operator"})
            self.assertEqual(store.clear_lot(1, {"username": "operator", "role": "Operator"}, confirmed=True), (1, 0))
            self.assertIn("LOT_CLEARED", self._events(path))
            self.assertNotIn("LOT_CLEARED_INCOMPLETE", self._events(path))


if __name__ == "__main__":
    unittest.main()

