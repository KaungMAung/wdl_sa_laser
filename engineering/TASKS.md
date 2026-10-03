# SA PLC Inspection Engineering Task Backlog

This backlog converts the current engineering gaps and unverified behavior into focused tasks. It does not authorize implementation by itself. Hardware- and operator-dependent work remains explicitly gated.

| ID | Title | Status | Type | Depends On |
|---|---|---|---|---|
| SA-001 | Establish an automated verification harness | DONE | TEST | — |
| SA-002 | Verify backend health and readiness endpoints | DONE | API | SA-001 |
| SA-003 | Verify authentication and session lifecycle | DONE | API | SA-001 |
| SA-004 | Verify role authorization across API routes | DONE | API | SA-003 |
| SA-005 | Verify operation state and scan workflow API | DONE | API | SA-001, SA-003 |
| SA-006 | Verify LOAD DATA Start and Current persistence | DONE | DB | SA-001 |
| SA-007 | Verify changed PLC status/result persistence | DONE | DB | SA-001, SA-006 |
| SA-008 | Verify Clear Lot lifecycle | DONE | DB | SA-006, SA-007 |
| SA-009 | Verify Clear All semantics | IN_REVIEW | DB | SA-008 |
| SA-010 | Verify explicit End Run semantics | DONE | DB | SA-006, SA-007 |
| SA-011 | Verify Inspection_Current restart recovery | DONE | DB | SA-006 |
| SA-012 | Verify SQL Server PO lookup in a controlled environment | ALIGNING | DB | SA-001 |
| SA-013 | Verify PLC connection and single-poller ownership | ALIGNING | PLC | SA-001 |
| SA-014 | Verify PLC recipe selection and LaserProgramNo contract | ALIGNING | PLC | SA-013, SA-019 |
| SA-015 | Verify TRAYDATA write and read-back mapping | ALIGNING | PLC | SA-014, SA-019 |
| SA-016 | Verify live PLC status/result polling persistence | ALIGNING | PLC | SA-007, SA-015 |
| SA-017 | Verify PLC identity mismatch protection | ALIGNING | PLC | SA-016 |
| SA-018 | Verify PLC communication-loss and reconnection behavior | ALIGNING | PLC | SA-013, SA-016 |
| SA-019 | Align unresolved PLC contract questions | ALIGNING | PLC | — |
| SA-020 | Characterize recipe workbook upsert reporting defect | DONE | BUG | SA-001 |
| SA-021 | Characterize configured connection-check interval behavior | DONE | BUG | SA-001 |
| SA-022 | Characterize SQL lookup database-name configuration defect | DONE | BUG | SA-001 |
| SA-023 | Characterize Clear All in-memory reset gap | DONE | BUG | SA-009 |
| SA-024 | Characterize Clear All transaction scope | DONE | BUG | SA-009 |
| SA-025 | Human/operator acceptance of production workflow | ALIGNING | HUMAN | SA-004, SA-005, SA-009, SA-010, SA-016 |
| SA-026 | Review legacy GUI retirement readiness | BLOCKED | CLEANUP | SA-002, SA-003, SA-004, SA-005, SA-009, SA-010, SA-025 |
| SA-027 | Retire obsolete direct-service GUI modules | BLOCKED | CLEANUP | SA-026 |
| SA-028 | Verify Recipe API CRUD contract | DONE | API | SA-001, SA-004 |
| SA-029 | Verify Settings and user-administration API contracts | DONE | API | SA-003, SA-004 |
| SA-030 | Correct expected scan rejection logging severity | READY | BUG | SA-005 |
| SA-031 | Correct recipe importer existing-row upsert behavior | READY | BUG | SA-020 |
| SA-032 | Close Recipe.xlsx workbook handles after import | READY | BUG | SA-020 |
| SA-033 | Honor configured connection-check interval | READY | BUG | SA-021 |
| SA-034 | Use configured database name in PO lookup | READY | BUG | SA-022 |
| SA-035 | Implement Clear All transaction atomicity | READY | BUG | SA-024 |
| SA-036 | Reset all Clear All working state | READY | BUG | SA-009, SA-023, SA-035 |

## Ordering Guidance

SA-001 and SA-002 are complete. The current executable correction backlog is
SA-030 through SA-036 in dependency order; SA-036 follows SA-035. SA-034 can
be implemented and verified offline after SA-022, while controlled/live SQL
verification remains SA-012. SA-026 and SA-027 are blocked by their human
acceptance/readiness dependencies. Hardware alignment (SA-019) should precede
PLC contract verification, and legacy cleanup must wait for the relevant API
and human acceptance evidence.

## Status Summary

- READY: 7
- ALIGNING: 9
- IN_PROGRESS: 0
- IN_REVIEW: 1
- BLOCKED: 2
- DONE: 17
- TRIAGE: 0
- CANCELLED: 0
