from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget

from services.api_client import ApiError
from ui.api_workers import ApiWorker


class SettingsPage(QWidget):
    def __init__(self, config_service, database_service, plc_service, auth_service, actor, parent=None):
        super().__init__(parent)
        self.config_service = config_service; self.database_service = database_service; self.plc_service = plc_service
        self.auth_service = auth_service; self.actor = actor; self.api_mode = hasattr(config_service, "settings"); self._threads = set()
        root = QVBoxLayout(self); title = QLabel("SETTINGS"); title.setObjectName("sectionTitle"); root.addWidget(title)
        form = QFormLayout(); self.server = QLineEdit(); self.database = QLineEdit(); self.driver = QLineEdit(); self.plc_ip = QLineEdit(); self.poll = QLineEdit("2")
        for label, field in (("SQL Server", self.server), ("Database", self.database), ("ODBC Driver", self.driver), ("PLC IP", self.plc_ip), ("Poll Interval (seconds)", self.poll)): form.addRow(label, field)
        root.addLayout(form); save = QPushButton("SAVE SETTINGS"); sql = QPushButton("TEST SQL CONNECTION"); plc = QPushButton("TEST PLC CONNECTION")
        save.clicked.connect(self.save); sql.clicked.connect(self.test_sql); plc.clicked.connect(self.test_plc); root.addWidget(save); root.addWidget(sql); root.addWidget(plc); root.addStretch(1)
        if self.api_mode: QTimer.singleShot(0, self._load_api_settings)
        else: self._apply_legacy_settings()

    def _request(self, operation, success):
        thread = QThread(self); worker = ApiWorker(operation); worker.moveToThread(thread); thread.started.connect(worker.run); worker.succeeded.connect(success)
        worker.failed.connect(lambda message: QMessageBox.warning(self, "Settings", message)); worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater); thread.finished.connect(lambda: self._threads.discard(thread)); self._threads.add(thread); thread.start()

    def _load_api_settings(self): self._request(self.config_service.settings, self._apply_settings)
    def _apply_settings(self, settings):
        db = settings.get("database", {}); plc = settings.get("plc", {}); self.server.setText(str(db.get("server", ""))); self.database.setText(str(db.get("database", ""))); self.driver.setText(str(db.get("driver", ""))); self.plc_ip.setText(str(plc.get("ip", ""))); self.poll.setText(str(plc.get("poll_interval_seconds", 2)))
    def _apply_legacy_settings(self):
        db = self.database_service.config; plc = self.plc_service.config; self.server.setText(getattr(db, "server", "")); self.database.setText(getattr(db, "database", "")); self.driver.setText(getattr(db, "driver", "")); self.plc_ip.setText(getattr(plc, "ip_address", "")); self.poll.setText(str(getattr(plc, "poll_interval_seconds", 2)))

    def save(self):
        try:
            database = {"server": self.server.text().strip(), "database": self.database.text().strip(), "driver": self.driver.text().strip()}; plc = {"ip": self.plc_ip.text().strip(), "poll_interval_seconds": float(self.poll.text())}
            if self.api_mode: self._request(lambda: self.config_service.update_settings(database, plc), lambda _: QMessageBox.information(self, "Settings", "Settings saved.")); return
            self.config_service.save_runtime_settings(database, plc); self.auth_service.audit(self.actor["username"], "settings_changed", "SQL and PLC configuration"); QMessageBox.information(self, "Settings", "Settings saved.")
        except (ValueError, OSError, ApiError) as error: QMessageBox.warning(self, "Settings", str(error))

    def test_sql(self):
        if self.api_mode: self._request(self.config_service.test_sql, lambda result: QMessageBox.information(self, "SQL Connection", "SQL Connection Successful" if result.get("connected", False) else "SQL Connection Failed")); return
        try: result = self.database_service.test_connection() or {"connected": True}; ok = result.get("connected", False) if isinstance(result, dict) else True
        except Exception: ok = False
        QMessageBox.information(self, "SQL Connection", "SQL Connection Successful" if ok else "SQL Connection Failed")

    def test_plc(self):
        if self.api_mode: self._request(self.config_service.test_plc, lambda result: QMessageBox.information(self, "PLC Connection", "PLC Connection Successful" if result.get("connected", False) else "PLC Connection Failed")); return
        try: ok = bool(self.plc_service.check_connection())
        except Exception: ok = False
        QMessageBox.information(self, "PLC Connection", "PLC Connection Successful" if ok else "PLC Connection Failed")
