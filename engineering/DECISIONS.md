# Engineering Decisions

This is an index of decisions observable in the current architecture. It does
not claim historical rationale that is not recorded.

## ADR-001 — Production GUI communicates through backend API

**Status:** Implemented

**Evidence:** `gui_main.py`, `services/api_client.py`,
`ui/api_main_window.py`, and `ui/api_operation_page.py`.

The normal GUI path sends operation, recipe, settings, user, and connection
requests to `api/recipe_api.py::RecipeApiServer`. The GUI does not construct
backend services in this path.

**Consequence:** Backend state is authoritative for the API GUI. The legacy
direct-service UI remains in the repository but is not the normal launcher.

## ADR-002 — Backend owns PLC polling

**Status:** Implemented

**Evidence:** `api_main.py::main` constructs one
`services/backend_poller.py::BackendPoller`; `services/process_lock.py` protects
`data/plc_owner.lock`.

**Consequence:** GUI refresh is HTTP state refresh, not PLC polling. A second
backend is rejected by the ownership lock.

## ADR-003 — RunService owns business/run state

**Status:** Implemented

**Evidence:** `services/run_service.py::RunService` owns LotState objects,
scanning decisions, recipe resolution, PLC payload construction, recovery,
and clear/end coordination.

**Consequence:** API handlers delegate operation actions to RunService rather
than implementing a second run-state model.

## ADR-004 — Inspection Start/Current/End/Event persistence model

**Status:** Implemented

**Evidence:** `services/inspection_store.py::InspectionStore::initialize`,
`load_snapshot`, `sync_poll`, `clear_lot`, and `end_run`.

Start and End are protected by SQLite immutability triggers; Current is the
active mutable ledger; Event is append-only history.

## ADR-005 — Clear All and End Run have different semantics

**Status:** Confirmed

**Evidence:** Confirmed business/engineering decision recorded on 2026-10-03;
current implementation references are `services/run_service.py::clear_lot`,
`clear_all_lots`, `end_run`, and `services/inspection_store.py::clear_lot`,
`end_run`.

Clear Lot finalizes only one lot, records its lot-level clear event, removes
only that lot's Current rows, and leaves other active lots running. It does not
emit `RUN_ENDED`.

Clear All repeats the Clear Lot behavior for every active lot and resets the
working batch state. It does not emit `RUN_ENDED`; it means “clear all active
lots,” not “explicitly end the production run.”

End Run finalizes all remaining Current rows, removes them, records one
run-level `RUN_ENDED` event, and explicitly terminates the run/batch.

**Consequence:** `RUN_ENDED` is reserved for an explicit End Run action. Clear
Lot and Clear All must not be interpreted as production-run termination.

**Implementation note:** Current Clear All behavior aligns with the event
distinction but should be checked for complete in-memory reset of inactive lots
and for the desired transaction scope; see `DATABASE_LIFECYCLE.md`.

## Decisions Requiring Human Confirmation

**Status:** NEEDS HUMAN CONFIRMATION

- **Application contract:** retain seven application parts per tray. Treat the
  exported ten-element PLC structure as capacity/unknown until hardware
  verification; do not change application code to ten based only on the export.
- **Recipe range:** retain Polisher Recipe IDs 1–16. Do not expand to 20 until
  RECIPE17–RECIPE20 are proven production-valid.
- **Recipe selection:** retain `HMI_RECIPE_SELECT_BIT` as the current
  implementation. Verify against the PLC before declaring the final contract;
  do not switch to `RECIPE_SELECTED_BIT` based only on the export.
- **CURRENT_RECIPE:** leave it unused. Do not write another PLC recipe tag
  without a confirmed machine requirement.
- Intended Done/NewTray PLC semantics.

The following are verification/operational items rather than architecture
decisions:

- In-memory authentication sessions are acceptable for now if re-login after
  backend restart is operationally acceptable.
- API GUI acceptance against live SQL Server, PLC hardware, and operators.

## ADR-006 — Clear All resets all working state atomically

**Status:** Confirmed

Clear All means clear all active lots and reset the complete working batch
state. It must not emit `RUN_ENDED`. All affected Current-to-End copies,
lot-level clear events, and Current deletions form one logical transaction;
failure rolls back the complete persistence operation and leaves in-memory
state unchanged as a successful clear.

**Consequence:** Clear All is distinct from End Run, which alone records
`RUN_ENDED`. The current implementation gaps are tracked by SA-035 (atomic
persistence) and SA-036 (complete in-memory reset).

## ADR-007 — Expected input rejection is not a system error

**Status:** Confirmed

Duplicate serials, invalid serials, and invalid scan-stage input are expected
business validation outcomes. They must not produce ERROR-level tracebacks;
unexpected exceptions remain ERROR-level with traceback.

## ADR-008 — Separate PLC idle checks from active polling

**Status:** Confirmed

When no run/tray data is active, PLC connectivity checks use their configured
connection-check cadence. Active Result/Status polling continues on its
configured polling cadence.

## ADR-009 — Configured SQL database is authoritative

**Status:** Confirmed

PO/run lookup must target the configured SQL database while retaining a bound
PO parameter and safe identifier handling.
