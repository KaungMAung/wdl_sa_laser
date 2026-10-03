from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from models.tray_data import TrayData
from services.recipe_service import RecipeService

LOGGER = logging.getLogger(__name__)
TERMINAL_STATUSES = {"PROCESSED", "COMPLETED", "COMPLETE", "DONE"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _raw_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class InspectionStore:
    """Local operational ledger for immutable load/end snapshots and live state."""

    def __init__(self, database_path: Path, recipe_service: RecipeService) -> None:
        self.database_path = database_path
        self.recipe_service = recipe_service
        self._identity_mismatches: set[str] = set()
        self.initialize()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.database_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    def initialize(self) -> None:
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS Inspection_Start (
                Disc_ID TEXT PRIMARY KEY, Run_ID TEXT NOT NULL, Lot_ID TEXT NOT NULL,
                Attempt_No INTEGER NOT NULL, PO_Run_No TEXT, Inspection_Lot TEXT,
                Inspection_Point_Name TEXT, Product_ID TEXT, Engraved_Name TEXT, Material_No TEXT,
                Diamond_Lot_Code TEXT, Serial_No TEXT NOT NULL, Tray_No INTEGER NOT NULL,
                Part_Index INTEGER NOT NULL, Status_Code INTEGER, Status_Text TEXT,
                Result_Code INTEGER, Result_Text TEXT, Run_Started_At TEXT NOT NULL,
                Loaded_At TEXT NOT NULL, UNIQUE(Run_ID, Lot_ID, Serial_No, Attempt_No))""")
            db.execute("""CREATE TABLE IF NOT EXISTS Inspection_Current (
                Disc_ID TEXT PRIMARY KEY, Run_ID TEXT NOT NULL, Lot_ID TEXT NOT NULL,
                Attempt_No INTEGER NOT NULL, PO_Run_No TEXT, Inspection_Lot TEXT,
                Inspection_Point_Name TEXT, Product_ID TEXT, Engraved_Name TEXT, Material_No TEXT,
                Diamond_Lot_Code TEXT, Serial_No TEXT NOT NULL, Tray_No INTEGER NOT NULL,
                Part_Index INTEGER NOT NULL, Status_Code INTEGER, Status_Text TEXT,
                Result_Code INTEGER, Result_Text TEXT, Run_Started_At TEXT NOT NULL,
                Loaded_At TEXT NOT NULL, Updated_At TEXT NOT NULL,
                UNIQUE(Run_ID, Lot_ID, Serial_No, Attempt_No))""")
            db.execute("""CREATE TABLE IF NOT EXISTS Inspection_End (
                Disc_ID TEXT PRIMARY KEY, Run_ID TEXT NOT NULL, Lot_ID TEXT NOT NULL,
                Attempt_No INTEGER NOT NULL, PO_Run_No TEXT, Inspection_Lot TEXT,
                Inspection_Point_Name TEXT, Product_ID TEXT, Engraved_Name TEXT, Material_No TEXT,
                Diamond_Lot_Code TEXT, Serial_No TEXT NOT NULL, Tray_No INTEGER NOT NULL,
                Part_Index INTEGER NOT NULL, Status_Code INTEGER, Status_Text TEXT,
                Result_Code INTEGER, Result_Text TEXT, Run_Started_At TEXT NOT NULL,
                Loaded_At TEXT NOT NULL, Updated_At TEXT NOT NULL, Ended_At TEXT NOT NULL,
                UNIQUE(Run_ID, Lot_ID, Serial_No, Attempt_No))""")
            for table in ("Inspection_Start", "Inspection_Current", "Inspection_End"):
                columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                if "Engraved_Name" not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN Engraved_Name TEXT")
            db.execute("""CREATE TABLE IF NOT EXISTS Inspection_Event (
                Event_ID TEXT PRIMARY KEY, Run_ID TEXT, Lot_ID TEXT, Disc_ID TEXT,
                Event_Type TEXT NOT NULL, Event_At TEXT NOT NULL, Username TEXT,
                Role TEXT, Details TEXT)""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_inspection_current_lot ON Inspection_Current(Run_ID, Lot_ID)")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_inspection_current_position ON Inspection_Current(Tray_No, Part_Index)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_inspection_event_run_time ON Inspection_Event(Run_ID, Event_At)")
            for table in ("Inspection_Start", "Inspection_End", "Inspection_Event"):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END")
                db.execute(f"CREATE TRIGGER IF NOT EXISTS protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END")

    @staticmethod
    def _event(db, event_type, actor, run_id=None, lot_id=None, disc_id=None, details=None):
        db.execute("INSERT INTO Inspection_Event (Event_ID, Run_ID, Lot_ID, Disc_ID, Event_Type, Event_At, Username, Role, Details) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), run_id, lot_id, disc_id, event_type, _now(), actor.get("username") if actor else None, actor.get("role") if actor else None, json.dumps(details or {}, ensure_ascii=False)))

    def load_snapshot(self, trays: list[TrayData], lot_states: dict[int, Any], actor: dict[str, str] | None) -> dict[str, Any]:
        now = _now()
        inserted = 0
        with self._db() as db:
            active = db.execute("SELECT Run_ID, Run_Started_At FROM Inspection_Current ORDER BY Loaded_At LIMIT 1").fetchone()
            run_id = active["Run_ID"] if active else str(uuid.uuid4())
            run_started = active["Run_Started_At"] if active else now
            active_positions = {
                (row["Tray_No"], row["Part_Index"]): dict(row)
                for row in db.execute("SELECT * FROM Inspection_Current")
            }
            active_run_ids = {row["Run_ID"] for row in active_positions.values()}
            if len(active_run_ids) > 1:
                raise RuntimeError(
                    "Multiple active Run_IDs exist; end the active runs before loading another batch."
                )
            lot_ids: dict[int, str] = {}
            for tray in trays:
                lot_no = tray.tray_index // 2 + 1
                state = lot_states.get(lot_no)
                if not state:
                    continue
                lot_id = lot_ids.get(lot_no)
                if lot_id is None:
                    current_lot = next(
                        (
                            row["Lot_ID"]
                            for (tray_no, _), row in active_positions.items()
                            if tray_no in ((lot_no - 1) * 2 + 1, (lot_no - 1) * 2 + 2)
                        ),
                        None,
                    )
                    prior = db.execute(
                        "SELECT Lot_ID FROM Inspection_Start WHERE Run_ID=? AND Tray_No IN (?,?) ORDER BY Loaded_At DESC LIMIT 1",
                        (run_id, (lot_no - 1) * 2 + 1, (lot_no - 1) * 2 + 2),
                    ).fetchone()
                    lot_id = current_lot or (prior["Lot_ID"] if prior else str(uuid.uuid4()))
                    lot_ids[lot_no] = lot_id
                for part_offset, part in enumerate(tray.parts):
                    serial = str(part.serial_no or "").strip()
                    if not serial:
                        continue
                    product_id = str(state.production_run.product_id if state.production_run else "").strip()
                    engraved_name = str(tray.engraved_name or "").strip()
                    material_no = str(tray.material_no or (state.production_run.material_number if state.production_run else "")).strip()
                    diamond_lot = str(tray.lot_code or (state.production_run.diamond_lot_code if state.production_run else "")).strip()
                    tray_no, part_index = tray.tray_index + 1, part_offset + 1
                    existing = active_positions.get((tray_no, part_index))
                    if existing:
                        same_identity = (
                            existing["Serial_No"] == serial
                            and (existing["Material_No"] or "") == material_no
                            and (existing["Diamond_Lot_Code"] or "") == diamond_lot
                        )
                        if not same_identity:
                            raise ValueError(
                                f"Cannot replace active disc at Tray {tray_no}, Part {part_index}; "
                                "clear its Lot before loading different identity data."
                            )
                        # Re-loading unchanged active PLC data is a refresh, not
                        # a new disc attempt or a second active Current row.
                        lot_ids[lot_no] = existing["Lot_ID"]
                        continue
                    previous = db.execute("SELECT COALESCE(MAX(Attempt_No),0) FROM Inspection_Start WHERE Run_ID=? AND Lot_ID=? AND Serial_No=?", (run_id, lot_id, serial)).fetchone()[0]
                    attempt = int(previous) + 1
                    disc_id = str(uuid.uuid4())
                    values = (disc_id, run_id, lot_id, attempt, str(tray.run_no or state.run_no or "").strip(), state.inspection_lot, state.inspection_point, product_id, engraved_name, material_no, diamond_lot, serial, tray_no, part_index, _raw_int(part.status), str(part.status_text), _raw_int(part.result), str(part.result_text), run_started, now)
                    columns = "Disc_ID,Run_ID,Lot_ID,Attempt_No,PO_Run_No,Inspection_Lot,Inspection_Point_Name,Product_ID,Engraved_Name,Material_No,Diamond_Lot_Code,Serial_No,Tray_No,Part_Index,Status_Code,Status_Text,Result_Code,Result_Text,Run_Started_At,Loaded_At"
                    marks = ",".join("?" for _ in values)
                    db.execute(f"INSERT INTO Inspection_Start ({columns}) VALUES ({marks})", values)
                    db.execute(f"INSERT INTO Inspection_Current ({columns},Updated_At) VALUES ({marks},?)", (*values, now))
                    self._event(db, "LOAD_DATA", actor, run_id, lot_id, disc_id, {"attempt_no":attempt,"tray_no":tray.tray_index+1,"part_index":part_offset+1})
                    active_positions[(tray_no, part_index)] = {
                        "Run_ID": run_id,
                        "Lot_ID": lot_id,
                        "Serial_No": serial,
                        "Material_No": material_no,
                        "Diamond_Lot_Code": diamond_lot,
                    }
                    inserted += 1
        LOGGER.info("Inspection load snapshot committed: Run_ID=%s new_discs=%d", run_id, inserted)
        return {"run_id":run_id,"lot_ids":lot_ids,"new_discs":inserted}

    def active_rows(self) -> list[dict[str, Any]]:
        with self._db() as db:
            return [dict(row) for row in db.execute("SELECT * FROM Inspection_Current ORDER BY Tray_No, Part_Index")]

    def rows_for_lot(self, lot_no: int) -> list[dict[str, Any]]:
        with self._db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM Inspection_Current WHERE Tray_No IN (?,?) ORDER BY Tray_No,Part_Index", ((lot_no-1)*2+1,(lot_no-1)*2+2))]

    def active_summary(self, lot_no: int | None = None) -> tuple[int, int]:
        rows = self.active_rows() if lot_no is None else self.rows_for_lot(lot_no)
        return len(rows), len(self._unfinished(rows))

    def trays_from_rows(self, rows: list[dict[str, Any]]) -> list[TrayData]:
        by_position = {(r["Tray_No"]-1, r["Part_Index"]-1): r for r in rows}
        trays = []
        from models.tray_data import TrayPartData
        for index in range(8):
            tray_rows = [r for (t, _), r in by_position.items() if t == index]
            first = tray_rows[0] if tray_rows else {}
            parts = []
            for offset in range(7):
                row = by_position.get((index, offset))
                if row:
                    parts.append(TrayPartData(row["Result_Code"],row["Serial_No"],row["Status_Code"],row["Result_Text"] or "",row["Status_Text"] or ""))
                else:
                    parts.append(TrayPartData(None,"",None,"NONE","READY"))
            material_no = first.get("Material_No", "")
            engraved_name = first.get("Engraved_Name", "")
            if not engraved_name:
                mapping = self.recipe_service.by_material(str(material_no or ""))
                engraved_name = (mapping or {}).get("engraved_name", "")
            trays.append(TrayData(index,False,first.get("PO_Run_No",""),engraved_name,first.get("Diamond_Lot_Code",""),material_no,True,tuple(parts)))
        return trays

    def sync_poll(self, trays: list[TrayData], identities: dict[tuple[int, int], dict[str, str]], actor: dict[str, str] | None) -> set[tuple[int, int]]:
        mismatches: set[tuple[int, int]] = set()
        with self._db() as db:
            active = {(r["Tray_No"], r["Part_Index"]): dict(r) for r in db.execute("SELECT * FROM Inspection_Current")}
            for tray in trays:
                for offset, part in enumerate(tray.parts, start=1):
                    current = active.get((tray.tray_index+1, offset))
                    if not current:
                        continue
                    observed = identities[(tray.tray_index, offset-1)]
                    serial = observed["serial_no"]
                    material = observed["material_no"]
                    diamond = observed["diamond_lot_code"]
                    mismatch = (serial != current["Serial_No"] or material != (current["Material_No"] or "") or diamond != (current["Diamond_Lot_Code"] or ""))
                    if mismatch:
                        mismatches.add((tray.tray_index, offset-1))
                        if current["Disc_ID"] not in self._identity_mismatches:
                            self._event(db,"IDENTITY_MISMATCH",actor,current["Run_ID"],current["Lot_ID"],current["Disc_ID"],{"expected":{"serial_no":current["Serial_No"],"material_no":current["Material_No"],"diamond_lot_code":current["Diamond_Lot_Code"],"tray_no":current["Tray_No"],"part_index":current["Part_Index"]},"actual":{"serial_no":serial,"material_no":material,"diamond_lot_code":diamond,"tray_no":tray.tray_index+1,"part_index":offset}})
                            self._identity_mismatches.add(current["Disc_ID"])
                        continue
                    self._identity_mismatches.discard(current["Disc_ID"])
                    status_code,status_text=_raw_int(part.status),str(part.status_text)
                    result_code,result_text=_raw_int(part.result),str(part.result_text)
                    # PLC raw codes define a transition. A configuration-only
                    # change to the display label must not create an event or
                    # mutate the live ledger by itself.
                    status_changed = status_code != current["Status_Code"]
                    result_changed = result_code != current["Result_Code"]
                    if not status_changed and not result_changed:continue
                    next_status_code = status_code if status_changed else current["Status_Code"]
                    next_status_text = status_text if status_changed else current["Status_Text"]
                    next_result_code = result_code if result_changed else current["Result_Code"]
                    next_result_text = result_text if result_changed else current["Result_Text"]
                    db.execute(
                        "UPDATE Inspection_Current SET Status_Code=?,Status_Text=?,Result_Code=?,Result_Text=?,Updated_At=? WHERE Disc_ID=?",
                        (next_status_code,next_status_text,next_result_code,next_result_text,_now(),current["Disc_ID"]),
                    )
                    if status_changed:self._event(db,"STATUS_CHANGED",actor,current["Run_ID"],current["Lot_ID"],current["Disc_ID"],{"from_code":current["Status_Code"],"from_text":current["Status_Text"],"to_code":status_code,"to_text":status_text})
                    if result_changed:self._event(db,"RESULT_CHANGED",actor,current["Run_ID"],current["Lot_ID"],current["Disc_ID"],{"from_code":current["Result_Code"],"from_text":current["Result_Text"],"to_code":result_code,"to_text":result_text})
        return mismatches

    @staticmethod
    def _unfinished(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [r for r in rows if str(r.get("Status_Text") or "").strip().upper() not in TERMINAL_STATUSES]

    def clear_lot(self, lot_no: int, actor: dict[str, str] | None, confirmed: bool) -> tuple[int, int]:
        now=_now()
        with self._db() as db:
            rows=[dict(r) for r in db.execute("SELECT * FROM Inspection_Current WHERE Tray_No IN (?,?)",((lot_no-1)*2+1,(lot_no-1)*2+2))]
            unfinished=self._unfinished(rows)
            if unfinished and not confirmed: return len(rows),len(unfinished)
            for row in rows:
                endrow={k:row.get(k) for k in ("Disc_ID","Run_ID","Lot_ID","Attempt_No","PO_Run_No","Inspection_Lot","Inspection_Point_Name","Product_ID","Engraved_Name","Material_No","Diamond_Lot_Code","Serial_No","Tray_No","Part_Index","Status_Code","Status_Text","Result_Code","Result_Text","Run_Started_At","Loaded_At","Updated_At")};endrow["Ended_At"]=now
                cols=tuple(endrow);db.execute(f"INSERT INTO Inspection_End ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",tuple(endrow[c] for c in cols))
            if rows:
                first=rows[0];event="LOT_CLEARED_INCOMPLETE" if unfinished else "LOT_CLEARED";self._event(db,event,actor,first["Run_ID"],first["Lot_ID"],None,{"lot_number":lot_no,"disc_count":len(rows),"unfinished_count":len(unfinished)})
            db.execute("DELETE FROM Inspection_Current WHERE Tray_No IN (?,?)",((lot_no-1)*2+1,(lot_no-1)*2+2))
        return len(rows),len(unfinished)

    def end_run(self, actor: dict[str, str] | None, confirmed: bool) -> tuple[int,int]:
        now=_now()
        with self._db() as db:
            rows=[dict(r) for r in db.execute("SELECT * FROM Inspection_Current ORDER BY Tray_No,Part_Index")]
            unfinished=self._unfinished(rows)
            if unfinished and not confirmed:return len(rows),len(unfinished)
            for row in rows:
                endrow={k:row.get(k) for k in ("Disc_ID","Run_ID","Lot_ID","Attempt_No","PO_Run_No","Inspection_Lot","Inspection_Point_Name","Product_ID","Engraved_Name","Material_No","Diamond_Lot_Code","Serial_No","Tray_No","Part_Index","Status_Code","Status_Text","Result_Code","Result_Text","Run_Started_At","Loaded_At","Updated_At")};endrow["Ended_At"]=now
                cols=tuple(endrow);db.execute(f"INSERT INTO Inspection_End ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",tuple(endrow[c] for c in cols))
            run_ids = {r["Run_ID"] for r in rows}
            db.execute("DELETE FROM Inspection_Current")
            for run_id in run_ids:
                self._event(db,"RUN_ENDED",actor,run_id,None,None,{"disc_count":len(rows),"unfinished_count":len(unfinished)})
        return len(rows),len(unfinished)
