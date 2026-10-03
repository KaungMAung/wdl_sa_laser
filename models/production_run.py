from dataclasses import dataclass, field
from typing import Any, Iterable


class ProductionRunValidationError(ValueError):
    """Raised when database rows cannot form a safe production run."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ProductionRecord:
    product_id: str
    material_number: str
    run_number: str
    diamond_lot_code: str
    serial_number: str

    @classmethod
    def from_database_row(cls, row: Any) -> "ProductionRecord":
        return cls(
            product_id=_clean(row[0]),
            material_number=_clean(row[1]),
            run_number=_clean(row[2]),
            diamond_lot_code=_clean(row[3]),
            serial_number=_clean(row[4]),
        )


@dataclass(frozen=True, slots=True)
class ProductionRun:
    product_id: str
    material_number: str
    run_number: str
    diamond_lot_code: str
    records: tuple[ProductionRecord, ...]
    expected_serial_numbers: tuple[str, ...]

    @property
    def expected_count(self) -> int:
        return len(self.expected_serial_numbers)

    @classmethod
    def from_rows(cls, rows: Iterable[Any]) -> "ProductionRun":
        records = tuple(ProductionRecord.from_database_row(row) for row in rows)

        if not records:
            raise ProductionRunValidationError("not_found", "RUN NO. NOT FOUND")
        if len(records) > 14:
            raise ProductionRunValidationError(
                "too_many",
                "MORE THAN 14 SERIAL NUMBERS FOUND",
            )

        first = records[0]
        identity = (
            first.product_id,
            first.material_number,
            first.run_number,
            first.diamond_lot_code,
        )
        if not all(
            (
                record.product_id,
                record.material_number,
                record.run_number,
                record.diamond_lot_code,
            )
            == identity
            for record in records
        ):
            raise ProductionRunValidationError(
                "inconsistent",
                "INCONSISTENT DATABASE DATA FOR RUN",
            )

        serials = tuple(record.serial_number for record in records)
        if any(not serial for serial in serials):
            raise ProductionRunValidationError(
                "inconsistent",
                "INCONSISTENT DATABASE DATA FOR RUN",
            )
        if len(set(serials)) != len(serials):
            raise ProductionRunValidationError(
                "duplicate_database_serial",
                "DUPLICATE SERIAL NUMBER IN DATABASE",
            )

        return cls(
            product_id=first.product_id,
            material_number=first.material_number,
            run_number=first.run_number,
            diamond_lot_code=first.diamond_lot_code,
            records=records,
            expected_serial_numbers=serials,
        )


@dataclass(slots=True)
class LotState:
    lot_number: int
    run_no: str = ""
    inspection_lot: str = ""
    inspection_point: str = ""
    production_run: ProductionRun | None = None
    sql_returned_records: list[ProductionRecord] = field(default_factory=list)
    records_by_serial: dict[str, ProductionRecord] = field(default_factory=dict)
    expected_serials: set[str] = field(default_factory=set)
    scanned_serials: set[str] = field(default_factory=set)
    scanned_serial_order: list[str] = field(default_factory=list)
    expected_count: int = 0
    scanned_count: int = 0
    status: str = "SCAN RUN NO. / PO NUMBER"
    status_tone: str = "neutral"

    @property
    def first_tray(self) -> int:
        return ((self.lot_number - 1) * 2) + 1

    @property
    def second_tray(self) -> int:
        return self.first_tray + 1

    def tray_and_position(self, scan_position: int) -> tuple[int, int]:
        if not 1 <= scan_position <= 14:
            raise ValueError("Scan position must be between 1 and 14")
        if scan_position <= 7:
            return self.first_tray, scan_position
        return self.second_tray, scan_position - 7

    def reset(self) -> None:
        self.run_no = ""
        self.inspection_lot = ""
        self.inspection_point = ""
        self.production_run = None
        self.sql_returned_records.clear()
        self.records_by_serial.clear()
        self.expected_serials.clear()
        self.scanned_serials.clear()
        self.scanned_serial_order.clear()
        self.expected_count = 0
        self.scanned_count = 0
        self.status = "SCAN RUN NO. / PO NUMBER"
        self.status_tone = "neutral"


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()
