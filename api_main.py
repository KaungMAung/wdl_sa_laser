"""Independent LaserMaker backend process (Phase 3)."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from api.backend_context import BackendContext
from api.recipe_api import RecipeApiServer
from services.auth_service import AuthService
from services.backend_poller import BackendPoller
from services.config_service import ConfigService
from services.database_service import DatabaseService
from services.inspection_store import InspectionStore
from services.plc_data_service import PLCDataService
from services.process_lock import ProcessOwnershipError, ProcessOwnershipLock
from services.recipe_service import RecipeService
from services.run_service import RunService

ROOT = Path(__file__).resolve().parent


def configure_logging() -> None:
    directory = ROOT / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    file_handler = RotatingFileHandler(directory / "lasermaker_backend.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, logging.StreamHandler()])


def main() -> int:
    configure_logging()
    logger = logging.getLogger("api_main")
    owner = ProcessOwnershipLock(ROOT / "data" / "plc_owner.lock")
    try:
        owner.acquire()
    except ProcessOwnershipError as error:
        logger.error("Unable to start backend: %s", error)
        print(str(error))
        return 2

    server = None
    poller = None
    try:
        config = ConfigService()
        database = DatabaseService(config.load_database_config())
        recipes = RecipeService()
        auth = AuthService(recipes.database_path)
        plc = PLCDataService(config.load_plc_config(), recipes)
        inspection = InspectionStore(recipes.database_path, recipes)
        run = RunService(database, plc, recipes, inspection)
        run.recover()
        poller = BackendPoller(plc, run, plc.config.poll_interval_seconds)
        context = BackendContext(
            config,
            database,
            plc,
            run,
            poller,
            inspection_store=inspection,
            recipe_service=recipes,
            auth_service=auth,
        )
        poller.status_callback = context.poll_status_changed
        server = RecipeApiServer(recipes, auth, backend=context)
        server.start()
        poller.start()
        logger.info("LaserMaker backend started; recovery rows=%d", len(inspection.active_rows()))
        # SQL/PLC availability is reported through the API. A missing device or
        # SQL server does not prevent the backend from serving health/status.
        try:
            context.test_sql()
        except Exception:
            logger.exception("Initial SQL status check failed")
        try:
            context.test_plc()
        except Exception:
            logger.exception("Initial PLC status check failed")
        while True:
            # ThreadingHTTPServer runs request handling in daemon threads.
            # Keep this owner process alive until Ctrl+C/service shutdown.
            import threading
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        logger.info("Backend shutdown requested")
    except Exception:
        logger.exception("Backend startup/runtime failure")
        return 1
    finally:
        if poller is not None:
            poller.stop()
        if server is not None:
            server.stop()
        owner.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
