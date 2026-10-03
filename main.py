"""Compatibility launcher for the separated LaserMaker architecture.

Use ``api_main.py`` for the backend and ``gui_main.py`` for the desktop
client.  This shim intentionally imports no PLC, database, run, recipe, or
authentication service and can never become a PLC owner.
"""
from __future__ import annotations

from gui_main import main as gui_main


def main() -> int:
    print("main.py is a compatibility shim; start api_main.py and gui_main.py separately.")
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
