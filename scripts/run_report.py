"""Generate the export workbook from scored jobs in the local database."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import initialize_config
from app.db import get_connection, init_db
from app.reporting import generate_report
from app.worker_logging import get_logger, log_worker_startup, setup_worker_logging
from _default_paths import _default_paths

LOGGER = get_logger("scripts.run_report")

def main() -> None:
    """Entrypoint for building one report workbook and storing export metadata."""
    setup_worker_logging()
    try:
        config = initialize_config(_default_paths(PROJECT_ROOT))
        setup_worker_logging(config.paths.log_path)
        log_worker_startup(config, context="run_report")
        LOGGER.info("Script start: run_report")
        init_db(config.paths.db_path)

        with get_connection(config.paths.db_path) as connection:
            summary = generate_report(connection, config)

        LOGGER.info(
            "Script complete: run_report export_id=%s path=%s new_rows=%s all_rows=%s all_jobs_list_rows=%s",
            summary.export_id,
            summary.export_path,
            summary.new_count,
            summary.all_count,
            summary.all_jobs_list_count,
        )
    except Exception:
        LOGGER.exception("Script failed: run_report")
        raise


if __name__ == "__main__":
    main()
