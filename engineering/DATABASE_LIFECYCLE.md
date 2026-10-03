# Database Lifecycle

## SQL Server

[CODE] `services/database_service.py::DatabaseService` uses SQL Server for
Run/PO lookup against `SA_MICRecord`.

The parameterized query selects `TOP (15)`:

- `ProdName` as Product ID
- `MaterialNbr` as Material No.
- `PO_Nbr` as Run No.
- `DIAMOND_LOT_NUM` as Diamond Lot Code
- `BatchNbr` as Serial No.

[CODE] `ProductionRun::from_rows` interprets zero rows, 1–14 rows, and 15
rows as separate validation outcomes.

[CODE] The query text hard-codes database name
`[workflow-u-woodlands-sg-new]`, even though a database name is also loaded
from configuration.

No production SQL Server verification is established by source alone.

## SQLite Ownership

The shared `data/lasermaker.db` is used by:

- `RecipeService` for `recipe_mapping`
- `AuthService` for `users`
- `InspectionStore` for inspection tables

## Inspection Lifecycle

```text
LOAD DATA
  -> Inspection_Start immutable snapshot
  -> Inspection_Current active row

PLC Status/Result change
  -> update affected Inspection_Current row
  -> append Inspection_Event

CLEAR LOT
  -> copy only that lot's Current rows to Inspection_End
  -> append LOT_CLEARED or LOT_CLEARED_INCOMPLETE
  -> delete only that lot's Current rows
  -> keep other lots active

CLEAR ALL
  -> perform the Clear Lot operation for every active lot
  -> append lot-level clear events
  -> delete all corresponding Current rows
  -> do not append RUN_ENDED
  -> perform the complete persistence operation atomically across all lots
  -> reset all lot/batch working state only after commit

END RUN
  -> copy all remaining Current rows to Inspection_End
  -> append one RUN_ENDED event
  -> delete all remaining Current rows
  -> explicitly terminate the run/batch
```

## Table Semantics

### Inspection_Start

[CODE] Created by `InspectionStore::load_snapshot` for each loaded disc. It
contains immutable identity, PLC raw/display values, run/lot/disc IDs, attempt,
and timestamps.

SQLite triggers prevent updates and deletes.

### Inspection_Current

[CODE] Contains active discs. `InspectionStore::sync_poll` updates only changed
Status/Result codes/text and `Updated_At`.

Current rows are deleted by clear/end operations.

### Inspection_End

[CODE] Receives the latest Current snapshot during Clear Lot or End Run.
SQLite triggers prevent updates and deletes.

### Inspection_Event

[CODE] Append-only events include `LOAD_DATA`, `STATUS_CHANGED`,
`RESULT_CHANGED`, `IDENTITY_MISMATCH`, lot-cleared events, and `RUN_ENDED`.
Username, role, timestamps, and JSON details are stored.

## IDs and Timestamps

[CODE] `InspectionStore::load_snapshot` generates UUID values for new Run_ID,
Lot_ID, and Disc_ID records. Attempt_No is incremented for a repeated serial in
the same Run/Lot.

Rows contain Run_Started_At, Loaded_At, Updated_At, and Ended_At where
applicable.

## Recovery

[CODE] `api_main.py` calls `RunService::recover` before starting the backend
poller. Recovery reads `Inspection_Current` and reconstructs active lot/tray
state without recreating Start records.

## Observed Local Database Evidence

[DB] At audit time, the repository-local SQLite file contained:

- `Inspection_Start`: 37 rows
- `Inspection_Current`: 0 rows
- `Inspection_End`: 37 rows
- `Inspection_Event`: 111 rows
- `recipe_mapping`: 80 rows
- `users`: 3 rows

This is evidence for the local SQLite file only, not the live SQL Server.

## Confirmed Clear/End Decision and Implementation Alignment

[DECISION] Clear Lot and Clear All are working-screen reset operations. They do
not explicitly end the production run. Only an explicit End Run action produces
`RUN_ENDED`.

[DECISION] Clear All must archive/finalize all affected lots, write all
lot-level clear events, and delete their Current rows in one logical
transaction. A failure rolls back all of those persistence changes and must
not reset in-memory state as though the operation succeeded. Clear All never
emits `RUN_ENDED`.

[CODE] `InspectionStore::end_run` already follows the End Run event behavior.
`RunService::clear_all_lots` clears active lots individually and calls
`finish_batch`; it does not call `InspectionStore::end_run` or emit
`RUN_ENDED`, which aligns with the confirmed event distinction.

[GAP] Current `RunService::clear_all_lots` resets each lot only when that lot
has active Current rows and performs separate Clear Lot transactions through
the loop. This does not yet satisfy the confirmed all-state reset and
all-lots-atomicity rules. Corrections are tracked by SA-035 and SA-036.
