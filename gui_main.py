"""Standalone LaserMaker GUI client.

The GUI deliberately starts no PLC, SQL, SQLite, or business service.  Those
services are owned by ``api_main.py``; this process only presents the API state.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from services.api_client import ApiClient
from ui.api_main_window import ApiMainWindow
from ui.login_dialog import LoginDialog


def main() -> int:
    log_dir = Path(__file__).resolve().parent / "logs"; log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "lasermaker_gui.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()])
    logging.getLogger("gui_main").info("LaserMaker API GUI start")
    app = QApplication(sys.argv)
    client = ApiClient(os.getenv("LASERMAKER_API_URL", "http://127.0.0.1:8765"))

    while True:
        login = LoginDialog(client)
        if login.exec() != login.DialogCode.Accepted:
            return 0
        user = login.user
        if not user:
            QMessageBox.critical(None, "Backend", "Authenticated user information was not returned by the backend.")
            client.logout()
            continue

        window = ApiMainWindow(client, user)
        logged_out = {"value": False}

        def reopen_login() -> None:
            logged_out["value"] = True
            app.quit()

        window.logout_requested.connect(reopen_login)
        window.show()
        result = app.exec()
        if not logged_out["value"]:
            return result
        # Logout ends only the GUI session.  The backend and its PLC poller
        # remain running; the next loop iteration displays the login screen.


if __name__ == "__main__":
    raise SystemExit(main())
