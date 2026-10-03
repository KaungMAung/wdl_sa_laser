from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

LOGGER = logging.getLogger(__name__)


class ApiWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self.operation = operation

    @Slot()
    def run(self) -> None:
        try:
            self.succeeded.emit(self.operation())
        except Exception as error:
            LOGGER.debug("API request failed", exc_info=True)
            self.failed.emit(str(error))
        finally:
            self.finished.emit()
