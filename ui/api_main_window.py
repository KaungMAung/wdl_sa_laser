from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDateTime, Qt, Signal, QTimer
from PySide6.QtGui import QCloseEvent, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QTabWidget, QVBoxLayout, QWidget

from services.api_client import ApiClient
from ui.api_operation_page import ApiOperationPage
from ui.recipe_page import RecipePage
from ui.settings_page import SettingsPage
from ui.users_page import UsersPage


class ApiMainWindow(QMainWindow):
    logout_requested = Signal()

    def __init__(self, client: ApiClient, user: dict, parent=None) -> None:
        super().__init__(parent)
        self.client = client; self.user = user
        self.setWindowTitle("LaserMaker"); self.resize(1080, 1920); self.setMinimumSize(900, 900)
        self._build_ui(); self._load_stylesheet()

    def _build_ui(self) -> None:
        root = QWidget(); layout = QVBoxLayout(root); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        layout.addWidget(self._header())
        self.operation_page = ApiOperationPage(self.client)
        self.operation_page.status_changed.connect(self.show_status)
        self.operation_page.backend_changed.connect(self._backend_status)
        self.operation_page.sql_connection_changed.connect(self._sql_status)
        self.operation_page.plc_connection_changed.connect(self._plc_status)
        self.navigation = QTabWidget(); self._populate_navigation(); layout.addWidget(self.navigation, 1); layout.addWidget(self._status_bar()); self.setCentralWidget(root)

    def _header(self) -> QFrame:
        header = QFrame(); header.setObjectName("header"); header.setFixedHeight(88); row = QHBoxLayout(header); row.setContentsMargins(26, 12, 26, 12)
        logo = QLabel(); logo.setFixedSize(102, 62); logo.setObjectName("brandLogo"); path = Path(__file__).resolve().parents[1] / "3M.png"; logo.setPixmap(QPixmap(str(path)).scaled(96, 58, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)); row.addWidget(logo)
        title = QLabel("LASER ENGRAVER/POLISHER"); title.setObjectName("appTitle"); row.addWidget(title); row.addStretch(1)
        self.sql_label = QLabel("● SQL DISCONNECTED"); self.sql_label.setObjectName("connectionStatus"); row.addWidget(self.sql_label)
        self.plc_label = QLabel("● PLC DISCONNECTED"); self.plc_label.setObjectName("connectionStatus"); row.addWidget(self.plc_label)
        self.clock = QLabel(); self.clock.setObjectName("clockLabel"); self.clock.setMinimumWidth(190); row.addWidget(self.clock)
        self.user_label = QLabel(f"USER: {self.user['username']}"); self.user_label.setObjectName("loggedInUser"); row.addWidget(self.user_label)
        logout = QPushButton("LOGOUT"); logout.setObjectName("logoutButton"); logout.clicked.connect(self.logout); row.addWidget(logout)
        self.clock_timer = QTimer(self); self.clock_timer.timeout.connect(self._clock); self.clock_timer.start(1000); self._clock()
        return header

    def _populate_navigation(self) -> None:
        self.navigation.clear(); self.navigation.addTab(self.operation_page, "Operation")
        role = self.user.get("role")
        if role in ("Admin", "Engineer"):
            self.navigation.addTab(RecipePage(self.client, self.user, self.client), "Recipe")
            self.navigation.addTab(SettingsPage(self.client, None, None, None, self.user), "Settings")
        if role == "Admin": self.navigation.addTab(UsersPage(self.client, self.user), "Users")

    def _status_bar(self) -> QFrame:
        frame = QFrame(); frame.setObjectName("statusArea"); frame.setFixedHeight(56); row = QHBoxLayout(frame); row.setContentsMargins(26, 8, 26, 8); row.addWidget(QLabel("OPERATOR STATUS")); self.status = QLabel("CONNECTED TO BACKEND"); self.status.setObjectName("statusMessage"); row.addWidget(self.status, 1); return frame

    def _clock(self) -> None: self.clock.setText(QDateTime.currentDateTime().toString("ddd, dd MMM yyyy\nhh:mm:ss AP"))
    def _load_stylesheet(self) -> None: self.setStyleSheet((Path(__file__).with_name("styles.qss")).read_text(encoding="utf-8"))
    def _backend_status(self, available: bool) -> None: self.status.setText("BACKEND CONNECTED" if available else "BACKEND DISCONNECTED")
    def _sql_status(self, connected: bool) -> None: self.sql_label.setText("● SQL CONNECTED" if connected else "● SQL DISCONNECTED")
    def _plc_status(self, connected: bool) -> None: self.plc_label.setText("● PLC CONNECTED" if connected else "● PLC DISCONNECTED")
    def show_status(self, message: str, tone: str = "neutral") -> None: self.status.setText(message)
    def logout(self) -> None:
        self.client.logout(); self.hide(); self.logout_requested.emit()
    def closeEvent(self, event: QCloseEvent) -> None:
        self.operation_page.wait_for_workers(); super().closeEvent(event)
