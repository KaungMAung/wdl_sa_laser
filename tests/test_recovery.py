"""RunService recovery from Inspection_Current tests."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from models.tray_data import TrayData, TrayPartData
from services.inspection_store import InspectionStore
from services.run_service import RunService
from tests.support.fakes import FakeDatabaseService, FakePLCDataService, FakeRecipeService
from tests.test_clear_lot import _lot_payload


class RecoveryTests(unittest.TestCase):
    def test_recovery_reconstructs_active_state_without_new_start_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inspection.db"
            recipes = FakeRecipeService()
            store = InspectionStore(path, recipes)
            lot1_trays, lot1_state = _lot_payload(1, "SER-001", complete=False)
            lot2_trays, lot2_state = _lot_payload(2, "SER-002", complete=False)
            empty = tuple(TrayPartData(None, "", None, "NONE", "READY") for _ in range(7))
            trays = [*lot1_trays, *lot2_trays, *(TrayData(index, False, "", "", "", "", False, empty) for index in range(4, 8))]
            actor = {"username": "operator", "role": "Operator"}
            store.load_snapshot(trays, {1: lot1_state, 2: lot2_state}, actor)
            connection = sqlite3.connect(path)
            try:
                start_before = connection.execute("SELECT COUNT(*) FROM Inspection_Start").fetchone()[0]
                current_before = connection.execute("SELECT COUNT(*) FROM Inspection_Current").fetchone()[0]
            finally:
                connection.close()

            recovered = RunService(FakeDatabaseService(), FakePLCDataService(), recipes, store, actor)
            rows = recovered.recover()

            self.assertEqual(len(rows), current_before)
            self.assertTrue(recovered.batch_active)
            self.assertEqual(recovered.batch_lots, {1, 2})
            self.assertEqual(recovered.lot_states[1].scanned_serials, {"SER-001"})
            self.assertEqual(recovered.lot_states[2].scanned_serials, {"SER-002"})
            self.assertEqual(len(recovered.loaded_tray_data), 8)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM Inspection_Start").fetchone()[0], start_before)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM Inspection_Current").fetchone()[0], current_before)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
