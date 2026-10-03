"""Smoke tests proving the offline verification harness is usable."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from models.production_run import ProductionRecord, ProductionRun
from tests.support.fakes import (
    FakeDatabaseService,
    FakePLCDataService,
    FakeRecipeService,
    FakeLotState,
    isolated_inspection_store,
    make_trays,
)


class OfflineHarnessTests(unittest.TestCase):
    def test_fakes_are_deterministic_and_do_not_connect(self) -> None:
        rows = [("S122L", "MAT-001", "RUN-001", "D-001", "SER-001")]
        database = FakeDatabaseService({"RUN-001": rows})
        plc = FakePLCDataService(make_trays())
        recipe = FakeRecipeService({"MAT-001": {"polisher_recipe_id": 1}})

        self.assertEqual(database.fetch_run_rows("RUN-001"), rows)
        self.assertEqual(database.lookup_calls, ["RUN-001"])
        self.assertTrue(plc.check_connection())
        self.assertEqual(plc.poll_tray_data()[0].parts[0].serial_no, "SER-001")
        self.assertEqual(recipe.by_material("MAT-001")["polisher_recipe_id"], 1)

    def test_isolated_store_loads_one_disc_and_persists_poll_changes(self) -> None:
        production = ProductionRun(
            product_id="S122L",
            material_number="MAT-001",
            run_number="RUN-001",
            diamond_lot_code="D-001",
            records=(
                ProductionRecord("S122L", "MAT-001", "RUN-001", "D-001", "SER-001"),
            ),
            expected_serial_numbers=("SER-001",),
        )
        lot_state = FakeLotState("RUN-001", "INSP-001", "SER-001", production)
        identity = {
            (0, 0): {
                "serial_no": "SER-001",
                "material_no": "MAT-001",
                "diamond_lot_code": "D-001",
            }
        }

        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "isolated.db"
            store = isolated_inspection_store(database_path)
            initial_trays = make_trays(lot_code="D-001")
            snapshot = store.load_snapshot(initial_trays, {1: lot_state}, {"username": "test", "role": "Admin"})

            self.assertEqual(snapshot["new_discs"], 1)
            self.assertEqual(len(store.active_rows()), 1)
            self.assertEqual(len(store.rows_for_lot(1)), 1)

            changed_trays = make_trays(
                lot_code="D-001",
                status=2,
                result=1,
                status_text="PROCESSED",
                result_text="PASS",
            )
            mismatches = store.sync_poll(changed_trays, identity, {"username": "test", "role": "Admin"})

            self.assertEqual(mismatches, set())
            row = store.active_rows()[0]
            self.assertEqual(row["Status_Code"], 2)
            self.assertEqual(row["Status_Text"], "PROCESSED")
            self.assertEqual(row["Result_Code"], 1)
            self.assertEqual(row["Result_Text"], "PASS")
            self.assertEqual({event["Event_Type"] for event in self._events(database_path)}, {"LOAD_DATA", "STATUS_CHANGED", "RESULT_CHANGED"})

    @staticmethod
    def _events(database_path: Path) -> list[dict[str, object]]:
        import sqlite3

        connection = sqlite3.connect(database_path)
        try:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute("SELECT * FROM Inspection_Event")]
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
