"""Focused characterization of Clear All in-memory reset behavior."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.inspection_store import InspectionStore
from services.run_service import RunService
from tests.support.fakes import FakeDatabaseService, FakePLCDataService, FakeRecipeService


class ClearAllResetGapTests(unittest.TestCase):
    def test_clear_all_does_not_reset_inactive_lot_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = InspectionStore(Path(directory) / "inspection.db", FakeRecipeService())
            run_service = RunService(FakeDatabaseService(), FakePLCDataService(), FakeRecipeService(), store)
            run_service.lot_states[3].run_no = "STALE-RUN"
            run_service.lot_states[3].inspection_lot = "STALE-LOT"
            run_service.lot_states[3].inspection_point = "STALE-POINT"
            run_service.batch_active = True

            run_service.clear_all_lots()

            # Confirmed ADR-005 semantics require all lot working state to be
            # cleared. This assertion records the current implementation gap.
            self.assertEqual(run_service.lot_states[3].run_no, "STALE-RUN")
            self.assertEqual(run_service.lot_states[3].inspection_lot, "STALE-LOT")
            self.assertEqual(run_service.lot_states[3].inspection_point, "STALE-POINT")


if __name__ == "__main__":
    unittest.main()

