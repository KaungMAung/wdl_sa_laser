# Verification

## Evidence Classes

- **[CODE]** Observable from current source.
- **[AUTO]** Verified by repeatable automated test or build check.
- **[API]** Verified through API-level integration testing.
- **[DB]** Verified against the relevant real database.
- **[PLC]** Verified against the actual PLC/hardware.
- **[HUMAN]** Verified manually by engineer/operator.

## Current Evidence

### [CODE]

Source inspection establishes the current backend/API boundary, RunService
ownership, BackendPoller ownership, SQL query, PLC tag construction, SQLite
tables/triggers, authentication roles, and legacy direct-service modules.

### [AUTO]

An offline `unittest` harness exists under `tests/`. Running
`python -m unittest discover -s tests -v` executes deterministic tests using
temporary SQLite databases and fake PLC/SQL/recipe services. This does not
verify live SQL Server, PLC, API, authentication, or operator behavior.

The suite now includes HTTP-boundary health, authentication/session,
authorization, operation scan, Recipe, Settings/User tests plus SQLite
inspection lifecycle, recovery, and defect-characterization tests.

Recorded batch result: 31 tests passed; `python -m compileall -q api api_main.py
services tests` completed with exit code 0.

### [API]

Checked-in HTTP-boundary tests in `tests/test_api_health.py` verify `/health`
when required service objects are initialized and when a required service is
missing. They also verify that unavailable PLC/SQL connectivity does not make
an initialized backend unhealthy. `tests/test_auth_api.py` verifies bearer and
cookie login, current-user lookup, invalid/inactive users, logout invalidation,
secret-safe responses/logs, and deterministic expiry. Broader API behavior
remains unverified. `tests/test_authorization_api.py` verifies the documented
Admin/Engineer/Operator route authorization matrix for production, Recipe,
Settings, and User Management endpoints.

`tests/test_operation_api.py`, `tests/test_recipe_api.py`, and
`tests/test_settings_users_api.py` verify operation state/scan, Recipe CRUD,
and Settings/User API behavior with isolated fakes. Live deployment and GUI
acceptance remain unverified.

### [DB]

The local SQLite file `data/lasermaker.db` was readable during the audit and
contained the expected inspection, recipe, and user tables. This does not
verify the live SQL Server or production database contents.

Historical `logs/lasermaker.log` contains `services.database_service` entries
reporting `SQL connection status: CONNECTED`; no formal SQL lookup or schema
acceptance record was found.

Offline SQLite lifecycle tests exercise temporary databases only; they are not
production database verification.

### [PLC]

Historical `logs/lasermaker.log` contains pycomm3 session initialization,
successful PLC connection activity, a logged `PLC LOAD DATA completed` event,
inspection snapshot creation, and repeated Result/Status polls.

This is runtime log evidence, not complete PLC acceptance testing. It does not
prove all recipe IDs, all trays, identity mismatch handling, recovery, or
operator workflows.

### [HUMAN]

No operator or engineer acceptance record was found in the repository.

## Required Future Verification

The following remain unverified and must not be treated as passed:

- Live backend startup/readiness deployment
- Backend restart/session behavior in the deployed environment
- GUI/API integration and operator workflow
- SQL Server connectivity and PO lookup against the real database
- SQLite Start/Current/End/Event lifecycle
- Backend restart recovery from Inspection_Current
- Live PLC recipe selection and LaserProgramNo read-back
- Live PLC TRAYDATA writes and reads
- Seven-versus-ten-part contract confirmation
- PLC Result/Status polling and changed-disc persistence
- PLC identity mismatch behavior
- Clear Lot behavior and history/end records (confirmed semantics, runtime
  behavior still unverified)
- Clear All behavior and absence of `RUN_ENDED` (confirmed semantics, runtime
  behavior still unverified)
- End Run behavior and exactly one `RUN_ENDED` event (confirmed semantics,
  runtime behavior still unverified)
- Scanner focus and operator workflow
- Multiple backend/process-lock behavior
- GUI close/reopen while backend polling continues
- SQL/PLC connection-loss and reconnection behavior
