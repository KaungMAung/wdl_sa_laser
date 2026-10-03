"""Characterization of BackendPoller connection-check cadence."""

from __future__ import annotations

import unittest

from services.backend_poller import BackendPoller


class _PLC:
    def __init__(self) -> None:
        self.connection_checks = 0
        self.polls = 0

    def check_connection(self) -> bool:
        self.connection_checks += 1
        return True

    def poll_result_status(self, trays):
        self.polls += 1
        return trays, {}


class _Run:
    def __init__(self, loaded=None) -> None:
        self.loaded_tray_data = loaded or []
        self.polls = 0

    def apply_plc_poll(self, trays, identities) -> None:
        self.polls += 1


class PollerIntervalCharacterizationTests(unittest.TestCase):
    def test_connection_check_runs_on_each_poll_interval_when_no_data_loaded(self) -> None:
        plc = _PLC()
        run = _Run()
        poller = BackendPoller(plc, run, interval_seconds=2)

        self.assertTrue(poller.poll_once())
        self.assertTrue(poller.poll_once())
        self.assertEqual(plc.connection_checks, 2)
        self.assertEqual(plc.polls, 0)
        self.assertEqual(poller.interval_seconds, 2)
        self.assertFalse(hasattr(poller, "connection_check_interval_seconds"))

    def test_loaded_data_poll_does_not_perform_separate_connection_check(self) -> None:
        plc = _PLC()
        run = _Run(loaded=[object()])
        poller = BackendPoller(plc, run, interval_seconds=2)

        self.assertTrue(poller.poll_once())
        self.assertEqual(plc.connection_checks, 0)
        self.assertEqual(plc.polls, 1)
        self.assertEqual(run.polls, 1)


if __name__ == "__main__":
    unittest.main()

