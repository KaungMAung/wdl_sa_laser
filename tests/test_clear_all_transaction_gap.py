"""Characterization of Clear All transaction scope."""

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


class _FailOnSecondClearStore(InspectionStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clear_calls = 0

    def clear_lot(self, lot_no, actor, confirmed):
        self.clear_calls += 1
        if self.clear_calls == 2:
            raise RuntimeError("injected second-lot clear failure")
        return super().clear_lot(lot_no, actor, confirmed)


class ClearAllTransactionGapTests(unittest.TestCase):
    def test_failure_between_lots_leaves_first_lot_committed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inspection.db"
            recipes = FakeRecipeService()
            store = _FailOnSecondClearStore(path, recipes)
            lot1_trays, lot1_state = _lot_payload(1, "SER-001", complete=False)
            lot2_trays, lot2_state = _lot_payload(2, "SER-002", complete=False)
            empty = tuple(TrayPartData(None, "", None, "NONE", "READY") for _ in range(7))
            trays = [*lot1_trays, *lot2_trays, *(TrayData(index, False, "", "", "", "", False, empty) for index in range(4, 8))]
            actor = {"username": "operator", "role": "Operator"}
            store.load_snapshot(trays, {1: lot1_state, 2: lot2_state}, actor)
            run_service = RunService(FakeDatabaseService(), FakePLCDataService(), recipes, store, actor)
            run_service.batch_active = True

            with self.assertRaisesRegex(RuntimeError, "second-lot clear failure"):
                run_service.clear_all_lots()

            self.assertEqual(len(store.rows_for_lot(1)), 0)
            self.assertEqual(len(store.rows_for_lot(2)), 1)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM Inspection_End").fetchone()[0], 1)
                event_types = [row[0] for row in connection.execute("SELECT Event_Type FROM Inspection_Event")]
            finally:
                connection.close()
            self.assertEqual(event_types.count("LOT_CLEARED_INCOMPLETE"), 1)
            self.assertNotIn("RUN_ENDED", event_types)


if __name__ == "__main__":
    unittest.main()

