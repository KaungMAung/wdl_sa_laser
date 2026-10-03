"""Small dependency fakes used by offline service tests.

These fakes intentionally implement only the public methods needed by tests;
they never open a PLC or SQL Server connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from models.tray_data import TrayData, TrayPartData
from services.inspection_store import InspectionStore


class FakeDatabaseService:
    """Deterministic replacement for DatabaseService PO lookup."""

    def __init__(self, rows_by_run: dict[str, list[Any]] | None = None) -> None:
        self.rows_by_run = rows_by_run or {}
        self.lookup_calls: list[str] = []

    def fetch_run_rows(self, po_number: str) -> list[Any]:
        self.lookup_calls.append(po_number)
        return list(self.rows_by_run.get(po_number, ()))

    def test_connection(self) -> None:
        return None


class FakePLCDataService:
    """Deterministic replacement for PLCDataService.

    The fake records payloads and returns supplied tray data; it never imports
    or invokes pycomm3.
    """

    def __init__(self, tray_data: list[TrayData] | None = None) -> None:
        self.tray_data = list(tray_data or [])
        self.write_calls: list[dict[str, Any]] = []
        self.poll_calls = 0

    def check_connection(self) -> bool:
        return True

    def write_tray_data(
        self,
        writes: dict[str, Any],
        material_no: str,
        polisher_recipe_id: int,
        engraver_recipe_id: int,
    ) -> list[TrayData]:
        self.write_calls.append(
            {
                "writes": dict(writes),
                "material_no": material_no,
                "polisher_recipe_id": polisher_recipe_id,
                "engraver_recipe_id": engraver_recipe_id,
            }
        )
        return list(self.tray_data)

    def poll_tray_data(self, *_args: Any, **_kwargs: Any) -> list[TrayData]:
        self.poll_calls += 1
        return list(self.tray_data)


class FakeRecipeService:
    """In-memory recipe lookup used by InspectionStore tests."""

    def __init__(self, mappings: dict[str, dict[str, Any]] | None = None) -> None:
        self.mappings = mappings or {}

    def by_material(self, material_no: str) -> dict[str, Any] | None:
        return self.mappings.get(material_no)


@dataclass
class FakeLotState:
    """Minimal lot state required by InspectionStore.load_snapshot."""

    run_no: str
    inspection_lot: str
    inspection_point: str
    production_run: Any


def make_trays(
    *,
    serial: str = "SER-001",
    material_no: str = "MAT-001",
    lot_code: str = "LOT-001",
    status: Any = None,
    result: Any = None,
    status_text: str = "READY",
    result_text: str = "NONE",
) -> list[TrayData]:
    """Build the current seven-part-per-tray application contract.

    Only the first part of Tray 1 is populated; all other parts are empty so a
    test can verify that one disc does not create unrelated rows.
    """

    parts = tuple(
        TrayPartData(
            result if index == 0 else None,
            serial if index == 0 else "",
            status if index == 0 else None,
            result_text if index == 0 else "NONE",
            status_text if index == 0 else "READY",
        )
        for index in range(7)
    )
    empty_parts = tuple(TrayPartData(None, "", None, "NONE", "READY") for _ in range(7))
    return [
        TrayData(0, False, "RUN-001", "", lot_code, material_no, True, parts),
        *(
            TrayData(index, False, "", "", "", "", False, empty_parts)
            for index in range(1, 8)
        ),
    ]


def isolated_inspection_store(database_path: Path) -> InspectionStore:
    """Create an initialized store in a caller-owned temporary directory."""

    return InspectionStore(database_path, FakeRecipeService())

