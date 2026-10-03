"""Inspection Current status/result change persistence tests."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from models.tray_data import TrayData, TrayPartData
from services.inspection_store import InspectionStore
from tests.test_inspection_load import _lot_state, _two_disc_trays
from tests.support.fakes import FakeRecipeService


def _poll_trays(status1=None, result1=None, status2=None, result2=None) -> list[TrayData]:
    parts = (
        TrayPartData(result1, "SER-001", status1, "PASS" if result1 is not None else "NONE", "PROCESSED" if status1 is not None else "READY"),
        TrayPartData(result2, "SER-002", status2, "PASS" if result2 is not None else "NONE", "PROCESSED" if status2 is not None else "READY"),
        *(TrayPartData(None, "", None, "NONE", "READY") for _ in range(5)),
    )
    empty = tuple(TrayPartData(None, "", None, "NONE", "READY") for _ in range(7))
    return [
        TrayData(0, False, "RUN-001", "", "D-001", "MAT-001", True, parts),
        *(TrayData(index, False, "", "", "", "", False, empty) for index in range(1, 8)),
    ]


class InspectionPollTests(unittest.TestCase):
    @staticmethod
    def _event_types(path: Path) -> list[str]:
        connection = sqlite3.connect(path)
        try:
            return [row[0] for row in connection.execute("SELECT Event_Type FROM Inspection_Event ORDER BY rowid")]
        finally:
            connection.close()

    def test_only_changed_disc_fields_are_updated_and_logged(self) -> None:
        identities = {
            (0, 0): {"serial_no": "SER-001", "material_no": "MAT-001", "diamond_lot_code": "D-001"},
            (0, 1): {"serial_no": "SER-002", "material_no": "MAT-001", "diamond_lot_code": "D-001"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inspection.db"
            store = InspectionStore(path, FakeRecipeService())
            store.load_snapshot(_two_disc_trays(), {1: _lot_state()}, {"username": "operator", "role": "Operator"})

            mismatches = store.sync_poll(_poll_trays(status1=2, result2=1), identities, {"username": "operator", "role": "Operator"})
            self.assertEqual(mismatches, set())
            self.assertEqual(self._event_types(path), ["LOAD_DATA", "LOAD_DATA", "STATUS_CHANGED", "RESULT_CHANGED"])
            first, second = store.active_rows()
            self.assertEqual((first["Status_Code"], first["Result_Code"]), (2, None))
            self.assertEqual((second["Status_Code"], second["Result_Code"]), (None, 1))

            store.sync_poll(_poll_trays(status1=2, result2=1), identities, {"username": "operator", "role": "Operator"})
            self.assertEqual(self._event_types(path), ["LOAD_DATA", "LOAD_DATA", "STATUS_CHANGED", "RESULT_CHANGED"])

            store.sync_poll(_poll_trays(status1=2, result1=1, status2=2, result2=1), identities, {"username": "operator", "role": "Operator"})
            self.assertEqual(
                self._event_types(path),
                ["LOAD_DATA", "LOAD_DATA", "STATUS_CHANGED", "RESULT_CHANGED", "RESULT_CHANGED", "STATUS_CHANGED"],
            )
            first, second = store.active_rows()
            self.assertEqual((first["Status_Code"], first["Result_Code"]), (2, 1))
            self.assertEqual((second["Status_Code"], second["Result_Code"]), (2, 1))


if __name__ == "__main__":
    unittest.main()

