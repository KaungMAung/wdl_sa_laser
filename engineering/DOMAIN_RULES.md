# Domain Rules

This document records current executable behavior. It does not establish
business rules beyond what the code currently enforces.

## Run

[CODE] `models/production_run.py::ProductionRun` is created from SQL rows. A
run must contain 1–14 rows, consistent Product ID, Material No., Run No., and
Diamond Lot Code, non-empty serials, and unique serials.

## Lot

[CODE] `RunService` creates four `LotState` instances. Each lot stores its own
Run No., inspection values, SQL records, serial whitelist, scanned serials,
counts, and status.

## Tray

[CODE] Current mapping in `LotState::first_tray`, `second_tray`, and
`tray_and_position` is:

- Lot 1 → Tray 1–2
- Lot 2 → Tray 3–4
- Lot 3 → Tray 5–6
- Lot 4 → Tray 7–8

## Disc / Part

[CODE] Current application models seven parts per tray. PLC tag generation and
polling use `Part[1]` through `Part[7]`. The current application contract is to
retain seven while treating the exported ten-element structure as capacity or
unknown until hardware verification.

## Serial Number

[CODE] SQL `BatchNbr` becomes `ProductionRecord.serial_number`.

[CODE] `RunService::validate_serial` trims input, requires membership in the
current SQL result set, and rejects previously scanned values.

## Inspection Point

[CODE] `RunService::accept_inspection_point` validates the entered value against
the current lot's serial map and immediately accepts it as the first serial.

This is CURRENT IMPLEMENTATION. The repository does not prove whether it is a
permanent business rule.

## Material / PO

[CODE] `DatabaseService::RUN_LOOKUP_SQL` maps:

- `ProdName` → Product ID
- `MaterialNbr` → Material No.
- `PO_Nbr` → Run No.
- `DIAMOND_LOT_NUM` → Diamond Lot Code
- `BatchNbr` → Serial No.

[CODE] `ProductionRun::from_rows` rejects zero rows, more than 14 rows,
inconsistent identity fields, blank serials, and duplicate database serials.

[CODE] `RunService::resolve_recipe` requires exactly one unique Material No.
across loaded lots, then queries `RecipeService::by_material` once for
Polisher and Engraver recipe IDs.

## Scan and Load

[CODE] Scan stages handled by `RunService::scan` are Run/PO, Inspection Lot,
Inspection Point, and Serial. `RunService::load_data` resolves the recipe,
prepares/writes PLC data, records the loaded snapshot, and returns a state
snapshot.

## Clear / End / Recovery

[CODE] `InspectionStore::clear_lot` copies Current rows to End, records a lot
cleared event, and deletes the lot's Current rows.

[CODE] `InspectionStore::end_run` copies all Current rows to End, records
`RUN_ENDED`, and deletes Current rows.

[CODE] `RunService::recover` rebuilds active lot state from Current rows during
backend startup.

## Confirmed Clear/End Semantics

[DECISION] Clear Lot clears only one lot: its Current rows move to End, a
`LOT_CLEARED` or `LOT_CLEARED_INCOMPLETE` event is recorded, those Current rows
are deleted, and that lot's in-memory state is cleared. It does not emit
`RUN_ENDED` or terminate other active lots.

[DECISION] Clear All performs the equivalent lot-level clear for every active
lot, records lot-level clear events, deletes the corresponding Current rows,
and clears ALL lot/batch working state, including inactive or partially entered
lot state, counters/displays, and staged/transient tray state. Its persistence
operation is atomic across all affected lots: either all required archives,
events, and Current deletions commit, or none do. It does not emit
`RUN_ENDED` and does not mean that the production run was explicitly
terminated.

[DECISION] End Run explicitly terminates the active run/batch: all remaining
Current rows are finalized to End, removed from Current, one run-level
`RUN_ENDED` event is recorded, and active lot/batch state is cleared.
`RUN_ENDED` represents only an explicit End Run action.

## Unresolved

- The intended meaning of Done/NewTray is not established by source comments or
  test records.
- Operator acceptance of the scanner sequence is not recorded.

## Confirmed Operational Rules

[DECISION] Expected business/input rejection (for example duplicate serial,
invalid serial, or invalid scan-stage input) is not a system ERROR. It should
be logged at an appropriate validation severity without a traceback; genuine
unexpected failures remain ERROR-level with traceback.

[DECISION] Recipe import reporting an existing Material No. as updated means
the imported recipe values must be persisted to that existing row.

[DECISION] Idle PLC connectivity checks and active Result/Status polling are
separate configured cadences.

[DECISION] SQL database configuration is authoritative for PO lookup; PO
values remain parameterized.

The confirmed semantics above are intended behavior. Current implementation
alignment is documented in `DATABASE_LIFECYCLE.md`.
