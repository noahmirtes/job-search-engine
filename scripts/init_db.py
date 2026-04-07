"""Initialize/sync the local SQLite schema for the current profile."""

from _script_runtime import load_local_worker_config
from app.db import init_db
from app.worker_logging import get_logger

LOGGER = get_logger("scripts.init_db")


def main() -> None:
    """Entrypoint for creating/upgrading the local jobs database."""
    try:
        config = load_local_worker_config(context="init_db")
        LOGGER.info("Script start: init_db")
        init_db(config.paths.db_path)
        LOGGER.info("Script complete: init_db db=%s", config.paths.db_path)
    except Exception:
        LOGGER.exception("Script failed: init_db")
        raise


if __name__ == "__main__":
    main()
