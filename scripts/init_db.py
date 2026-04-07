"""Initialize/sync the local SQLite schema for the current profile."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import initialize_config
from app.db import init_db
from app.worker_logging import get_logger, log_worker_startup, setup_worker_logging

from _default_paths import _default_paths

LOGGER = get_logger("scripts.init_db")


def main() -> None:
    """Entrypoint for creating/upgrading the local jobs database."""
    setup_worker_logging()
    try:
        config = initialize_config(_default_paths(PROJECT_ROOT))
        setup_worker_logging(config.paths.log_path)
        log_worker_startup(config, context="init_db")
        LOGGER.info("Script start: init_db")
        init_db(config.paths.db_path)
        LOGGER.info("Script complete: init_db db=%s", config.paths.db_path)
    except Exception:
        LOGGER.exception("Script failed: init_db")
        raise


if __name__ == "__main__":
    main()
