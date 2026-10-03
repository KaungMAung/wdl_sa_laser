"""Backend-owned PLC result/status polling loop."""

from __future__ import annotations

import logging
from threading import Event, Lock, Thread
from typing import Callable

from services.plc_data_service import PLCDataService
from services.run_service import RunService

LOGGER = logging.getLogger(__name__)


class BackendPoller:
    def __init__(self, plc_service: PLCDataService, run_service: RunService,
                 interval_seconds: float,
                 status_callback: Callable[[bool], None] | None = None) -> None:
        self.plc_service = plc_service
        self.run_service = run_service
        self.interval_seconds = max(0.25, float(interval_seconds))
        self.status_callback = status_callback
        self._stop = Event()
        self._wake = Event()
        self._thread: Thread | None = None
        self._poll_lock = Lock()
        self.last_error: str | None = None
        self.connected: bool | None = None
        self.last_poll_at: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="backend-plc-poller", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout)
        self._thread = None

    def status(self) -> dict[str, object]:
        return {
            "connected": self.connected,
            "last_error": self.last_error,
            "last_poll_at": self.last_poll_at,
            "running": bool(self._thread and self._thread.is_alive()),
        }

    def poll_once(self) -> bool:
        if not self._poll_lock.acquire(blocking=False):
            return False
        try:
            if self.run_service.loaded_tray_data:
                refreshed, identities = self.plc_service.poll_result_status(
                    self.run_service.loaded_tray_data
                )
                self.run_service.apply_plc_poll(refreshed, identities)
            else:
                self.plc_service.check_connection()
            self.connected = True
            self.last_error = None
            from datetime import datetime, timezone
            self.last_poll_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            if self.status_callback:
                self.status_callback(True)
            return True
        except Exception as error:
            self.connected = False
            self.last_error = str(error)
            LOGGER.exception("Backend PLC poll failed")
            if self.status_callback:
                self.status_callback(False)
            return False
        finally:
            self._poll_lock.release()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._wake.wait(self.interval_seconds)
            self._wake.clear()
