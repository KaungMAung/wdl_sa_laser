from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TrayPartData:
    result: Any
    serial_no: Any
    status: Any
    result_text: str
    status_text: str
    identity_mismatch: bool = False


@dataclass(frozen=True, slots=True)
class TrayData:
    tray_index: int
    done: Any
    run_no: Any
    engraved_name: Any
    lot_code: Any
    material_no: Any
    new_tray: Any
    parts: tuple[TrayPartData, ...]
