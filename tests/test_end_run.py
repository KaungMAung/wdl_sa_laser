"""Explicit End Run persistence/event tests."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from models.tray_data import TrayData, TrayPartData
from services.inspection_store import InspectionStore
from tests.support.fakes import FakeRecipeService
from tests.test_clear_lot import _lot_payload


class EndRunTests(unittest.TestCase):
    def test_end_run_requires_confirmation_then_finalizes_all_current_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inspection.db"
            store = InspectionStore(path, FakeRecipeService())
            lot1_trays, lot1_state = _lot_payload(1, "SER-001", complete=False)
            lot2_trays, lot2_state = _lot_payload(2, "SER-002", complete=True)
            empty = tuple(TrayPartData(None, "", None, "NONE", "READY") for _ in range(7))
            trays = [*lot1_trays, *lot2_trays, *(TrayData(index, False, "", "", "", "", False, empty) for index in range(4, 8))]
            actor = {"username": "operator", "role": "Operator"}
            store.load_snapshot(trays, {1: lot1_state, 2: lot2_state}, actor)

            self.assertEqual(store.end_run(actor, confirmed=False), (2, 1))
            self.assertEqual(len(store.active_rows()), 2)

            self.assertEqual(store.end_run(actor, confirmed=True), (2, 1))
            self.assertEqual(store.active_rows(), [])
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM Inspection_End").fetchone()[0], 2)
                run_ended = connection.execute("SELECT Event_Type, Run_ID, Lot_ID FROM Inspection_Event WHERE Event_Type='RUN_ENDED'").fetchall()
                self.assertEqual(len(run_ended), 1)
                self.assertIsNotNone(run_ended[0][1])
                self.assertIsNone(run_ended[0][2])
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM Inspection_Event WHERE Event_Type LIKE 'LOT_CLEARED%'").fetchone()[0], 0)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()

