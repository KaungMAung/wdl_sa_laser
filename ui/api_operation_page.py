from __future__ import annotations

from PySide6.QtCore import QDateTime, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (QFrame, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from services.api_client import ApiClient
from ui.api_workers import ApiWorker


class ApiLotPanel(QFrame):
    action_requested = Signal(int, str, str)
    clear_requested = Signal(int)

    def __init__(self, lot_number: int, parent=None) -> None:
        super().__init__(parent)
        self.lot_number = lot_number
        self._busy = False
        self.setObjectName("lotSection")
        root = QVBoxLayout(self)
        heading = QHBoxLayout()
        self.title = QLabel(f"LOT {lot_number}")
        self.title.setObjectName("lotTrayLabel")
        heading.addWidget(self.title)
        heading.addStretch(1)
        self.counter = QLabel("0 / 0")
        self.counter.setObjectName("scanCounter")
        heading.addWidget(self.counter)
        self.clear_button = QPushButton("CLEAR LOT")
        self.clear_button.clicked.connect(lambda: self.clear_requested.emit(self.lot_number))
        heading.addWidget(self.clear_button)
        root.addLayout(heading)

        form = QGridLayout()
        self.run = QLineEdit(); self.run.setPlaceholderText("Run No. / PO Number")
        self.inspection_lot = QLineEdit(); self.inspection_lot.setPlaceholderText("Inspection Lot")
        self.point = QLineEdit(); self.point.setPlaceholderText("Inspection Point / First Serial")
        self.serial = QLineEdit(); self.serial.setPlaceholderText("Scan Serial No.")
        self.product = QLabel("-"); self.material = QLabel("-"); self.diamond = QLabel("-")
        for row, (label, widget) in enumerate((("RUN NO.", self.run), ("INSPECTION LOT", self.inspection_lot), ("INSPECTION POINT", self.point), ("SERIAL NO.", self.serial))):
            form.addWidget(QLabel(label), row, 0); form.addWidget(widget, row, 1)
        form.addWidget(QLabel("PRODUCT"), 0, 2); form.addWidget(self.product, 0, 3)
        form.addWidget(QLabel("MATERIAL NO."), 1, 2); form.addWidget(self.material, 1, 3)
        form.addWidget(QLabel("DIAMOND LOT"), 2, 2); form.addWidget(self.diamond, 2, 3)
        root.addLayout(form)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["Tray", "Pos", "Product", "Material", "Run", "Diamond Lot", "Serial No.", "Result", "Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table)
        self.run.returnPressed.connect(lambda: self.action_requested.emit(self.lot_number, "run", self.run.text()))
        self.inspection_lot.returnPressed.connect(lambda: self.action_requested.emit(self.lot_number, "inspection_lot", self.inspection_lot.text()))
        self.point.returnPressed.connect(lambda: self.action_requested.emit(self.lot_number, "inspection_point", self.point.text()))
        self.serial.returnPressed.connect(lambda: self.action_requested.emit(self.lot_number, "serial", self.serial.text()))

    def apply(self, state: dict, discs: list[dict]) -> None:
        self.counter.setText(f"{state.get('scanned_count', 0)} / {state.get('expected_count', 0)}")
        for widget, key in ((self.run, "run_no"), (self.inspection_lot, "inspection_lot"), (self.point, "inspection_point")):
            if state.get(key) and not widget.hasFocus(): widget.setText(str(state[key]))
        self.product.setText(str(state.get("product_id") or "-")); self.material.setText(str(state.get("material_no") or "-")); self.diamond.setText(str(state.get("diamond_lot_code") or "-"))
        self.table.setRowCount(0)
        for disc in discs:
            row = self.table.rowCount(); self.table.insertRow(row)
            values = (disc.get("Tray_No", ""), disc.get("Part_Index", ""), disc.get("Product_ID", ""), disc.get("Material_No", ""), disc.get("PO_Run_No", ""), disc.get("Diamond_Lot_Code", ""), disc.get("Serial_No", ""), disc.get("Result_Text", ""), disc.get("Status_Text", ""))
            for col, value in enumerate(values): self.table.setItem(row, col, QTableWidgetItem(str(value or "")))
        self._set_enabled(state)

    def _set_enabled(self, state: dict) -> None:
        loaded = bool(state.get("loaded"))
        # Backend state controls the workflow; the fields are enabled only as
        # the next scan stage becomes available.
        self.run.setEnabled(not loaded and not state.get("run_no"))
        self.inspection_lot.setEnabled(not loaded and bool(state.get("run_no")) and not state.get("inspection_lot"))
        self.point.setEnabled(not loaded and bool(state.get("inspection_lot")) and not state.get("inspection_point"))
        self.serial.setEnabled(not loaded and bool(state.get("inspection_point")))


class ApiOperationPage(QWidget):
    status_changed = Signal(str, str)
    backend_changed = Signal(bool)
    sql_connection_changed = Signal(bool)
    plc_connection_changed = Signal(bool)

    def __init__(self, client: ApiClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self._threads: set[QThread] = set()
        self._refresh_in_flight = False
        self._action_in_flight = False
        self._backend_available = True
        self.lots = {number: ApiLotPanel(number) for number in range(1, 5)}
        root = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("4 LOT PRODUCTION VIEW")); toolbar.addStretch(1)
        self.load_button = QPushButton("LOAD DATA"); self.load_button.clicked.connect(self.load_data); toolbar.addWidget(self.load_button)
        self.load_status = QLabel("DATA NOT LOADED"); toolbar.addWidget(self.load_status)
        self.clear_all = QPushButton("CLEAR ALL LOTS"); self.clear_all.clicked.connect(self.clear_all_lots); toolbar.addWidget(self.clear_all)
        self.end_run = QPushButton("END RUN"); self.end_run.clicked.connect(self.end_run_clicked); toolbar.addWidget(self.end_run)
        root.addLayout(toolbar)
        summary = QHBoxLayout(); summary.addStretch(1); self.polisher = QLabel("POLISHER RECIPE: --"); self.engraver = QLabel("ENGRAVER RECIPE: --"); summary.addWidget(self.polisher); summary.addSpacing(30); summary.addWidget(self.engraver); summary.addStretch(1); root.addLayout(summary)
        tabs = QTabWidget()
        for group, label in (((1, 2), "LOTS 1–2"), ((3, 4), "LOTS 3–4")):
            scroll = QScrollArea(); scroll.setWidgetResizable(True); holder = QWidget(); layout = QVBoxLayout(holder)
            for number in group:
                layout.addWidget(self.lots[number]); self.lots[number].action_requested.connect(self.scan); self.lots[number].clear_requested.connect(self.clear_lot)
            scroll.setWidget(holder); tabs.addTab(scroll, label)
        root.addWidget(tabs, 1)
        self.timer = QTimer(self); self.timer.setInterval(1000); self.timer.timeout.connect(self.refresh_state); self.timer.start()
        QTimer.singleShot(0, self.refresh_state)

    def _request(self, operation, success, error=None) -> None:
        thread = QThread(self); worker = ApiWorker(operation); worker.moveToThread(thread); thread.started.connect(worker.run); worker.succeeded.connect(success); worker.failed.connect(error or self._request_failed); worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater); thread.finished.connect(thread.deleteLater); thread.finished.connect(lambda: self._threads.discard(thread)); self._threads.add(thread); thread.start()

    def refresh_state(self) -> None:
        if self._refresh_in_flight or self._action_in_flight or not self.client.authenticated: return
        self._refresh_in_flight = True
        self._request(self.client.operation_state, self._state_received, self._refresh_failed)

    def _state_received(self, state: dict) -> None:
        self._refresh_in_flight = False; self._set_backend(True)
        self.sql_connection_changed.emit(bool((state.get("sql") or {}).get("connected")))
        self.plc_connection_changed.emit(bool((state.get("plc") or {}).get("connected")))
        self.polisher.setText(f"POLISHER RECIPE: {state.get('polisher_recipe_id') or '--'}"); self.engraver.setText(f"ENGRAVER RECIPE: {state.get('engraver_recipe_id') or '--'}")
        active = state.get("active_discs", [])
        for number, panel in self.lots.items():
            lot_state = dict(state.get("lots", [{}] * 4)[number - 1]); lot_state["loaded"] = state.get("loaded", False)
            panel.apply(lot_state, [d for d in active if ((int(d.get("Tray_No", 1)) - 1) // 2) + 1 == number])

    def _refresh_failed(self, message: str) -> None:
        self._refresh_in_flight = False; self._set_backend(False); self.status_changed.emit("BACKEND DISCONNECTED", "error")

    def _request_failed(self, message: str) -> None:
        self.status_changed.emit(message, "error")

    def _set_backend(self, available: bool) -> None:
        if self._backend_available != available: self.backend_changed.emit(available)
        self._backend_available = available
        for widget in (self.load_button, self.clear_all, self.end_run): widget.setEnabled(available)

    def scan(self, lot: int, stage: str, value: str) -> None:
        self._action_in_flight = True; self._request(lambda: self.client.scan(lot, stage, value), self._action_received, self._action_failed)

    def load_data(self) -> None: self._action_in_flight = True; self._request(self.client.load_data, self._action_received, self._action_failed)

    def clear_lot(self, lot: int) -> None:
        if QMessageBox.question(self, "Clear Lot", f"Clear Lot {lot}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes: self._action_in_flight = True; self._request(lambda: self.client.clear_lot(lot, True), self._action_received, self._action_failed)

    def clear_all_lots(self) -> None:
        if QMessageBox.question(self, "Clear All Lots", "Clear all Lots?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes: self._action_in_flight = True; self._request(lambda: self.client.clear_all(True), self._action_received, self._action_failed)

    def end_run_clicked(self) -> None:
        if QMessageBox.question(self, "End Run", "End the active Run?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes: self._action_in_flight = True; self._request(lambda: self.client.end_run(True), self._action_received, self._action_failed)

    def _action_received(self, state: dict) -> None:
        self._action_in_flight = False; self._state_received(state.get("state", state) if isinstance(state, dict) else {})

    def _action_failed(self, message: str) -> None:
        self._action_in_flight = False; self._request_failed(message)

    def wait_for_workers(self) -> None:
        self.timer.stop()
        for thread in list(self._threads):
            if thread.isRunning(): thread.quit(); thread.wait(5000)
