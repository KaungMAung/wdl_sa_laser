"""Clear All persistence/event and in-memory reset characterization."""

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


class ClearAllTests(unittest.TestCase):
    def test_clear_all_finalizes_active_lots_without_run_ended(self) -> None:
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

            run_service = RunService(FakeDatabaseService(), FakePLCDataService(), recipes, store, actor)
            run_service.loaded_tray_data = trays
            run_service.batch_active = True
            run_service.batch_lots = {1, 2}
            run_service.pending_batch_lots = {1, 2}
            run_service.lot_states[3].run_no = "STALE-INACTIVE-LOT"

            run_service.clear_all_lots()

            self.assertFalse(run_service.batch_active)
            self.assertEqual(store.active_rows(), [])
            self.assertEqual(len(store.rows_for_lot(1)), 0)
            self.assertEqual(len(store.rows_for_lot(2)), 0)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM Inspection_End").fetchone()[0], 2)
                event_types = [row[0] for row in connection.execute("SELECT Event_Type FROM Inspection_Event")]
            finally:
                connection.close()
            self.assertEqual(event_types.count("LOT_CLEARED_INCOMPLETE"), 2)
            self.assertNotIn("RUN_ENDED", event_types)

            # Confirmed semantics require every lot's working state to reset;
            # this records the current implementation gap without fixing it.
            self.assertEqual(run_service.lot_states[3].run_no, "STALE-INACTIVE-LOT")


if __name__ == "__main__":
    unittest.main()
