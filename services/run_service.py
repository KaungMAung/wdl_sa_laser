"""Application-facing production run business service.

Phase 2 keeps the existing Qt screens and workers, but puts run state and the
decisions around scanning, recipe selection, load, polling, and completion in
one object.  The next API phase can expose this object without moving rules a
second time.
"""

from __future__ import annotations

import logging
from threading import RLock
from typing import Any

from models.production_run import LotState, ProductionRecord, ProductionRun
from models.tray_data import TrayData
from services.database_service import DatabaseService
from services.inspection_store import InspectionStore
from services.plc_data_service import PLCDataService
from services.recipe_service import RecipeService

LOGGER = logging.getLogger(__name__)


class RunService:
    def __init__(self, database_service: DatabaseService,
                 plc_data_service: PLCDataService,
                 recipe_service: RecipeService,
                 inspection_store: InspectionStore,
                 actor: dict[str, str] | None = None) -> None:
        self.database_service = database_service
        self.plc_data_service = plc_data_service
        self.recipe_service = recipe_service
        self.inspection_store = inspection_store
        self.actor = actor or {}
        self.lot_states = {lot: LotState(lot_number=lot) for lot in range(1, 5)}
        self.loaded_tray_data: list[TrayData] = []
        self.loaded_data_source = "NOT_LOADED"
        self.batch_active = False
        self.pending_batch_lots: set[int] = set()
        self.batch_lots: set[int] = set()
        self.lots_cleared_after_load: set[int] = set()
        self.resolved_material_no = ""
        self.resolved_polisher_recipe_id: int | None = None
        self.resolved_engraver_recipe_id: int | None = None
        self.resolved_engraved_name = ""
        self._lock = RLock()

    def set_actor(self, actor: dict[str, str]) -> None:
        self.actor = actor or {}

    def lookup_result(self, production_run: ProductionRun, lot_number: int) -> None:
        state = self.lot_states[lot_number]
        state.production_run = production_run
        state.sql_returned_records = list(production_run.records)
        state.records_by_serial = {r.serial_number: r for r in production_run.records}
        state.expected_serials = set(state.records_by_serial)
        state.scanned_serials.clear()
        state.scanned_serial_order.clear()
        state.expected_count = len(state.expected_serials)
        state.scanned_count = 0

    def clear_loaded_run_data(self, lot_number: int) -> None:
        state = self.lot_states[lot_number]
        state.inspection_lot = ""
        state.inspection_point = ""
        state.production_run = None
        state.sql_returned_records.clear()
        state.records_by_serial.clear()
        state.expected_serials.clear()
        state.scanned_serials.clear()
        state.scanned_serial_order.clear()
        state.expected_count = 0
        state.scanned_count = 0

    def lookup_run(self, run_no: str) -> ProductionRun:
        """Execute and validate the existing parameterized SQL lookup."""
        return ProductionRun.from_rows(self.database_service.fetch_run_rows(run_no.strip()))

    def scan(self, lot_number: int, stage: str, value: str) -> dict[str, Any]:
        """Apply one scanner action and return the authoritative state."""
        with self._lock:
            state = self.lot_states[lot_number]
            value = value.strip()
            if stage in {"run", "po", "run_no"}:
                if not value:
                    raise ValueError("RUN NO. REQUIRED")
                production = self.lookup_run(value)
                state.run_no = value
                self.lookup_result(production, lot_number)
                state.status, state.status_tone = "RUN FOUND — SCAN INSPECTION LOT", "active"
            elif stage in {"inspection_lot", "lot"}:
                self.accept_inspection_lot(lot_number, value)
                state.status, state.status_tone = "SCAN INSPECTION POINT / FIRST SERIAL NO.", "active"
            elif stage in {"inspection_point", "point"}:
                self.accept_inspection_point(lot_number, value)
                state.status, state.status_tone = self._scan_status(state)
            elif stage in {"serial", "serial_no"}:
                self.accept_serial(lot_number, value)
                state.status, state.status_tone = self._scan_status(state)
            else:
                raise ValueError(f"Unknown scan stage: {stage}")
            return self.state_snapshot()

    @staticmethod
    def _scan_status(state: LotState) -> tuple[str, str]:
        if state.scanned_count == state.expected_count:
            return "ALL SERIAL NUMBERS SCANNED", "success"
        return f"{state.scanned_count} OF {state.expected_count} SERIAL NUMBERS SCANNED", "warning"

    def load_data(self) -> dict[str, Any]:
        with self._lock:
            self.resolve_recipe()
            trays = self.plc_data_service.write_tray_data(
                self.build_plc_write_payload(),
                self.resolved_material_no,
                int(self.resolved_polisher_recipe_id),
                int(self.resolved_engraver_recipe_id),
            )
            self.record_loaded_trays(trays, "PLC")
            return self.state_snapshot()

    def recipe_for_material(self, material_no: str) -> dict[str, Any] | None:
        return self.recipe_service.by_material(material_no.strip())

    def recipe_summary(self) -> tuple[str, str]:
        materials = {
            str(state.production_run.material_number).strip()
            for state in self.lot_states.values()
            if state.production_run and str(state.production_run.material_number).strip()
        }
        if len(materials) != 1:
            return "--", "--"
        mapping = self.recipe_for_material(next(iter(materials)))
        if not mapping:
            return "--", "--"
        return (
            str(mapping["polisher_recipe_id"]) if mapping.get("polisher_recipe_id") is not None else "--",
            str(mapping["engraver_recipe_id"]) if mapping.get("engraver_recipe_id") is not None else "--",
        )

    def accept_inspection_lot(self, lot_number: int, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("INSPECTION LOT REQUIRED")
        self.lot_states[lot_number].inspection_lot = value
        return value

    def accept_inspection_point(self, lot_number: int, value: str) -> str:
        value = value.strip()
        state = self.lot_states[lot_number]
        if not value or value not in state.records_by_serial:
            raise ValueError("INVALID INSPECTION POINT / SERIAL NO. FOR THIS RUN")
        state.inspection_point = value
        self.accept_serial(lot_number, value)
        return value

    def inspection_point_is_valid(self, lot_number: int, value: str) -> bool:
        value = value.strip()
        return bool(value) and value in self.lot_states[lot_number].records_by_serial

    def validate_serial(self, lot_number: int, value: str) -> str:
        value = value.strip()
        state = self.lot_states[lot_number]
        if not value or value not in state.records_by_serial:
            raise ValueError("INVALID SERIAL NO. FOR THIS RUN")
        if value in state.scanned_serials:
            raise ValueError("SERIAL NO. ALREADY SCANNED")
        return value

    def accept_serial(self, lot_number: int, value: str) -> ProductionRecord:
        value = self.validate_serial(lot_number, value)
        state = self.lot_states[lot_number]
        state.scanned_serials.add(value)
        state.scanned_serial_order.append(value)
        state.scanned_count = len(state.scanned_serials)
        return state.records_by_serial[value]

    def resolve_recipe(self) -> tuple[str, int, int, str]:
        materials = {
            str(s.production_run.material_number).strip()
            for s in self.lot_states.values()
            if s.production_run and str(s.production_run.material_number).strip()
        }
        if len(materials) != 1:
            raise ValueError(
                "NO MSSQL RUN DATA LOADED" if not materials
                else "MATERIAL NUMBER MISMATCH: ALL LOTS MUST USE THE SAME MATERIAL NO."
            )
        material = next(iter(materials))
        mapping = self.recipe_service.by_material(material)
        if not mapping:
            raise ValueError(f"No recipe mapping configured for Material No. {material}")
        polisher, engraver = mapping.get("polisher_recipe_id"), mapping.get("engraver_recipe_id")
        if polisher is None or engraver is None:
            raise ValueError(f"INCOMPLETE RECIPE MAPPING FOR MATERIAL NO. {material}")
        self.resolved_material_no = material
        self.resolved_polisher_recipe_id = int(polisher)
        self.resolved_engraver_recipe_id = int(engraver)
        self.resolved_engraved_name = str(mapping.get("engraved_name") or "")
        return material, int(polisher), int(engraver), self.resolved_engraved_name

    def build_plc_write_payload(self) -> dict[str, object]:
        writes: dict[str, object] = {}
        for lot_number, state in self.lot_states.items():
            production = state.production_run
            active = bool(state.run_no or state.scanned_serial_order or production)
            material = production.material_number if production else ""
            diamond = production.diamond_lot_code if production else ""
            serials = list(state.scanned_serial_order[:14])
            for local_tray in range(2):
                tray_index = (lot_number - 1) * 2 + local_tray
                prefix = f"TRAYDATA[{tray_index}]"
                writes[f"{prefix}.Done"] = False
                writes[f"{prefix}.RunNo"] = state.run_no.strip()
                writes[f"{prefix}.ProductID"] = self.resolved_engraved_name if production else ""
                writes[f"{prefix}.LotCode"] = diamond
                writes[f"{prefix}.MaterialNo"] = material
                writes[f"{prefix}.NewTray"] = active
                for part_index in range(7):
                    position = local_tray * 7 + part_index
                    writes[f"{prefix}.Part[{part_index + 1}].SerialNo"] = serials[position] if position < len(serials) else ""
        LOGGER.info("Prepared writable TRAYDATA payload for 8 trays (%d values)", len(writes))
        return writes

    def record_loaded_trays(self, trays: list[TrayData], source: str) -> dict[str, Any]:
        snapshot = self.inspection_store.load_snapshot(trays, self.lot_states, self.actor)
        self.loaded_tray_data = list(trays)
        self.loaded_data_source = source
        self.batch_active = True
        self.batch_lots = self.pending_batch_lots | {
            lot for lot in range(1, 5)
            if any(self.tray_has_loaded_data(trays[i]) for i in ((lot - 1) * 2, (lot - 1) * 2 + 1) if i < len(trays))
        } or {1, 2, 3, 4}
        self.lots_cleared_after_load.clear()
        return snapshot

    def set_pending_batch_lots(self, lots: set[int]) -> None:
        self.pending_batch_lots = set(lots)

    def apply_plc_poll(self, trays: list[TrayData], identities: dict[tuple[int, int], dict[str, str]]) -> set[tuple[int, int]]:
        with self._lock:
            self.loaded_tray_data = list(trays)
            return self.inspection_store.sync_poll(trays, identities, self.actor)

    def recover(self) -> list[dict[str, Any]]:
        rows = self.inspection_store.active_rows()
        if not rows:
            return []
        self.loaded_tray_data = self.inspection_store.trays_from_rows(rows)
        self.loaded_data_source = "PLC"
        self.batch_active = True
        self.batch_lots = {((r["Tray_No"] - 1) // 2) + 1 for r in rows}
        for lot_no in self.batch_lots:
            lot_rows = [r for r in rows if ((r["Tray_No"] - 1) // 2) + 1 == lot_no]
            first = lot_rows[0]
            records = tuple(ProductionRecord(r["Product_ID"] or "", r["Material_No"] or "", r["PO_Run_No"] or "", r["Diamond_Lot_Code"] or "", r["Serial_No"]) for r in lot_rows)
            state = self.lot_states[lot_no]
            state.run_no = str(first["PO_Run_No"] or "")
            state.inspection_lot = str(first["Inspection_Lot"] or "")
            state.inspection_point = str(first["Inspection_Point_Name"] or "")
            state.production_run = ProductionRun(str(first["Product_ID"] or ""), str(first["Material_No"] or ""), str(first["PO_Run_No"] or ""), str(first["Diamond_Lot_Code"] or ""), records, tuple(r.serial_number for r in records))
            state.sql_returned_records = list(records)
            state.records_by_serial = {r.serial_number: r for r in records}
            state.expected_serials = set(state.records_by_serial)
            state.scanned_serial_order = [r.serial_number for r in records]
            state.scanned_serials = set(state.scanned_serial_order)
            state.expected_count = state.scanned_count = len(records)
        return rows

    def active_summary(self, lot_number: int | None = None) -> tuple[int, int]:
        return self.inspection_store.active_summary(lot_number)

    def has_active_lot(self, lot_number: int) -> bool:
        return bool(self.inspection_store.rows_for_lot(lot_number))

    def reset_lot(self, lot_number: int) -> None:
        self.lot_states[lot_number].reset()

    def finish_batch(self) -> None:
        self.loaded_tray_data.clear()
        self.loaded_data_source = "NOT_LOADED"
        self.batch_active = False
        self.pending_batch_lots.clear()
        self.batch_lots.clear()
        self.lots_cleared_after_load.clear()
        self.resolved_material_no = ""
        self.resolved_polisher_recipe_id = None
        self.resolved_engraver_recipe_id = None
        self.resolved_engraved_name = ""

    def clear_lot(self, lot_number: int, confirmed: bool = True) -> tuple[int, int]:
        with self._lock:
            result = self.inspection_store.clear_lot(lot_number, self.actor, confirmed)
            if confirmed:
                self.reset_lot(lot_number)
                wanted = {(lot_number - 1) * 2, (lot_number - 1) * 2 + 1}
                self.loaded_tray_data = [t for t in self.loaded_tray_data if t.tray_index not in wanted]
            self.lots_cleared_after_load.add(lot_number)
            return result

    def clear_all_lots(self) -> None:
        for lot_number in range(1, 5):
            if self.has_active_lot(lot_number):
                self.clear_lot(lot_number, confirmed=True)
        self.finish_batch()

    def all_batch_lots_cleared(self) -> bool:
        return self.batch_lots.issubset(self.lots_cleared_after_load)

    def end_run(self, confirmed: bool = True) -> tuple[int, int]:
        with self._lock:
            result = self.inspection_store.end_run(self.actor, confirmed)
            if confirmed:
                for lot_number in range(1, 5):
                    self.reset_lot(lot_number)
                self.finish_batch()
            return result

    def state_snapshot(self) -> dict[str, Any]:
        with self._lock:
            lots = []
            for number, state in self.lot_states.items():
                lots.append({
                    "lot_number": number,
                    "run_no": state.run_no,
                    "inspection_lot": state.inspection_lot,
                    "inspection_point": state.inspection_point,
                    "expected_count": state.expected_count,
                    "scanned_count": state.scanned_count,
                    "status": state.status,
                    "status_tone": state.status_tone,
                    "product_id": state.production_run.product_id if state.production_run else "",
                    "material_no": state.production_run.material_number if state.production_run else "",
                    "diamond_lot_code": state.production_run.diamond_lot_code if state.production_run else "",
                    "scanned_serials": list(state.scanned_serial_order),
                    "records": [
                        {"serial_no": r.serial_number, "product_id": r.product_id,
                         "material_no": r.material_number, "run_no": r.run_number,
                         "diamond_lot_code": r.diamond_lot_code}
                        for r in state.sql_returned_records
                    ],
                })
            return {
                "loaded": bool(self.loaded_tray_data),
                "source": self.loaded_data_source,
                "batch_active": self.batch_active,
                "polisher_recipe_id": self.resolved_polisher_recipe_id,
                "engraver_recipe_id": self.resolved_engraver_recipe_id,
                "lots": lots,
                "active_discs": self.inspection_store.active_rows(),
            }

    @staticmethod
    def tray_has_loaded_data(tray: TrayData) -> bool:
        return any(str(v or "").strip() for v in (tray.run_no, tray.engraved_name, tray.lot_code, tray.material_no)) or any(str(p.serial_no or "").strip() for p in tray.parts)
