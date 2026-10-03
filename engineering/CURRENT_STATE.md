# Current State

## Current Production Architecture

The normal runtime is two processes:

```text
python api_main.py   # backend/API, database, PLC and polling owner
python gui_main.py   # PySide6 API client
```

`api_main.py::main` creates the backend services and starts the
`ThreadingHTTPServer` implementation in `api/recipe_api.py::RecipeApiServer`.
This is not FastAPI.

`gui_main.py::main` creates `services/api_client.py::ApiClient` and the API GUI.
`main.py` is a compatibility shim that delegates to `gui_main.py`; it does not
create PLC/database services or a poller.

## Current Ownership

- Run state and business validation: `services/run_service.py::RunService`
- PLC connection, reads and writes: `services/plc_data_service.py::PLCDataService`
- PLC polling: `services/backend_poller.py::BackendPoller`
- SQL Server lookup: `services/database_service.py::DatabaseService`
- Inspection persistence: `services/inspection_store.py::InspectionStore`
- Recipe SQLite data: `services/recipe_service.py::RecipeService`
- Users and sessions: `services/auth_service.py::AuthService`
- GUI rendering and operator input: `ui/api_*` modules through `ApiClient`

## Implemented

[CODE] Four-lot scan state, SQL PO lookup, serial whitelist validation, recipe
resolution, PLC recipe/tray load, PLC status/result polling, SQLite inspection
ledger, startup recovery, authentication roles, and API-backed GUI pages are
implemented in the current production path.

[CODE] The backend uses `data/plc_owner.lock` through
`services/process_lock.py::ProcessOwnershipLock`.

[CODE] `GET /health` reports HTTP/backend readiness and required service-object
availability separately from live PLC and SQL connectivity.

[CODE] Authentication uses PBKDF2 password hashes and in-memory eight-hour
sessions. API requests support Bearer tokens and the HttpOnly session cookie;
logout invalidates the server-side session, and backend restart invalidates
active sessions.

## Legacy Still Present

[CODE] `legacy/ui/main_window.py`, `legacy/ui/operation_page.py`, and
`legacy/ui/workers.py` contain the retained direct PLC/database/RunService
ownership and Qt PLC timers. They are physically isolated from, and not
launched by, the normal `main.py` shim.

## Verification Status

- [CODE] Architecture and behavior are observable from source.
- [AUTO] An offline `unittest` harness now exists under `tests/`; it uses
  temporary SQLite databases and fake PLC/SQL/recipe services. It does not
  verify live API, SQL Server, PLC, or operator behavior.
- [API] HTTP-boundary tests now cover `/health` readiness, missing-service
  handling, authentication/session behavior, bearer and cookie auth, logout,
  invalid/inactive users, and deterministic expiry. Broader API behavior
  remains unverified.
- [DB] Local `data/lasermaker.db` was inspectable; this does not verify SQL Server.
- [PLC] Historical logs show pycomm3 connection, Load Data, and polling events;
  this is not complete PLC acceptance testing.
- [HUMAN] No operator acceptance record was found.

## Known Gaps

- Legacy direct-service GUI modules remain.
- PLC export metadata conflicts with current seven-part/1–16 recipe assumptions.
- Configured connection-check intervals are not used by the backend polling loop.
- Recipe workbook import counts existing rows as updates but does not visibly
  execute an update for them in `RecipeService::import_workbook`.
- Clear Lot/Clear All versus End Run semantics are confirmed. Clear All must
  reset all working state atomically; implementation gaps remain and are
  tracked by SA-035 and SA-036.

## Decisions / Unresolved Questions

- Provisional application contract: retain seven parts per tray; treat the
  exported ten-element PLC structure as capacity/unknown until hardware
  verification.
- Retain Polisher Recipe IDs 1–16; do not expand to 20 until RECIPE17–20 are
  proven production-valid.
- Retain `HMI_RECIPE_SELECT_BIT` as the current implementation, pending PLC
  verification; leave `CURRENT_RECIPE` unused.
- `Done` and `NewTray` semantics remain unresolved.
- API/SQL Server/PLC/operator acceptance remains unverified.

## Current Engineering Objective

Stabilize and verify the API-based production architecture.

Immediate priorities:
- establish automated verification
- verify API path with live SQL Server and PLC
- resolve PLC contract uncertainties
- retire legacy direct-service GUI after equivalence is confirmed
