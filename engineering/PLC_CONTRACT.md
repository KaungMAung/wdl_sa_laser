# PLC Contract

## Connection

[CODE] `services/plc_data_service.py::PLCDataService` uses
`pycomm3.LogixDriver` against the configured IP `192.168.1.10` from
`config/config.yaml`.

[CODE] Configured polling interval is two seconds. Configured connection-check
interval is 60 seconds, but `BackendPoller` currently polls/checks using its
poll interval; the separate connection-check interval is not applied there.

## Application-Written Data

[CODE] `PLCDataService::write_tray_data` validates Polisher Recipe ID 1–16,
builds `RECIPE<n>`, verifies `RECIPE<n>.ID`, writes and reads back
`RECIPE<n>.LaserProgramNo`, and writes/reads back `HMI_RECIPE_SELECT_BIT`.

[CODE] It writes the following current tray fields for eight trays:

- `TRAYDATA[x].Done`
- `TRAYDATA[x].RunNo`
- `TRAYDATA[x].ProductID`
- `TRAYDATA[x].LotCode`
- `TRAYDATA[x].MaterialNo`
- `TRAYDATA[x].NewTray`
- `TRAYDATA[x].Part[1..7].SerialNo`

[CODE] It does not write PLC-owned `Result` or `Status` fields.

## PLC-Owned / Read Data

[CODE] Load reads back the full generated tray tag list after writing.

[CODE] Polling reads each part's `Result`, `Status`, and `SerialNo`, plus tray
`MaterialNo` and `LotCode`. Serial/material/lot values are read to verify
identity protection.

## Polling

[CODE] `services/backend_poller.py::BackendPoller` is the only poller in the
production backend. It has a non-blocking lock to prevent overlapping calls,
records connection/error/last-poll state, and routes refreshed values through
`RunService::apply_plc_poll`.

[CODE] When a disc identity differs from the persisted Current identity,
`InspectionStore::sync_poll` logs `IDENTITY_MISMATCH`, does not overwrite the
identity, and skips Status/Result updates for that disc until identity matches.

## Status Mapping

[CODE] `ConfigService::load_plc_config` loads mappings from YAML.
`PLCDataService::map_plc_value` preserves raw values and maps display text;
unknown values become `UNKNOWN (<value>)`.

Current configured mappings include:

```text
Status: 0 READY, 1 RUNNING, 2 PROCESSED, 3 PART FAILED, 5 NO PART
Result: 0 NONE, 1 PASS
```

## Identity Protection

[CODE] Current identity fields are Serial No., Material No., Diamond/Lot Code,
tray, and part position. Status and Result are not applied when an identity
mismatch is observed.

## Confirmed Provisional Decisions / Unresolved PLC Contract Questions

1. **Application contract:** retain seven application parts per tray. Treat the
   exported ten-element structure as PLC capacity/unknown until hardware
   verification; do not change the application to ten based only on the export.
2. **Recipe range:** retain Polisher Recipe IDs 1–16. Do not expand to 20 until
   `RECIPE17`–`RECIPE20` are proven production-valid.
3. **Recipe selection:** retain `HMI_RECIPE_SELECT_BIT` as current
   implementation. Verify against the PLC before calling it the final contract;
   do not switch to `RECIPE_SELECTED_BIT` based only on the export.
4. **CURRENT_RECIPE:** leave it unused. The current
   `write_tray_data` does not write it.
5. Exact production semantics of `Done` and `NewTray` remain unresolved and
   require an actual PLC sequence test.
6. Exported metadata shows `Result` as BOOL in one tag export while application
   configuration treats Result mappings as numeric values; this remains to be
   confirmed against the deployed controller.
