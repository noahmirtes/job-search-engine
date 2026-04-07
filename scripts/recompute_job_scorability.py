"""Recompute scoring eligibility flags for all normalized jobs rows."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import initialize_config
from app.db import get_connection, init_db
from app.jobs import recompute_jobs_scorability
from app.worker_logging import get_logger, log_worker_startup, setup_worker_logging

from _default_paths import _default_paths

LOGGER = get_logger("scripts.recompute_job_scorability")


def main() -> None:
    """Entrypoint for backfilling jobs.is_scorable fields."""
    setup_worker_logging()
    try:
        config = initialize_config(_default_paths(PROJECT_ROOT))
        setup_worker_logging(config.paths.log_path)
        log_worker_startup(config, context="recompute_job_scorability")
        LOGGER.info("Script start: recompute_job_scorability")
        init_db(config.paths.db_path)

        with get_connection(config.paths.db_path) as connection:
            updated_count = recompute_jobs_scorability(connection)

        LOGGER.info(
            "Script complete: recompute_job_scorability updated_jobs=%s",
            updated_count,
        )
    except Exception:
        LOGGER.exception("Script failed: recompute_job_scorability")
        raise


if __name__ == "__main__":
    main()
