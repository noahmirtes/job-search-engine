"""Recompute scoring eligibility flags for all normalized jobs rows."""

from __future__ import annotations

from _script_runtime import load_local_worker_config
from app.db import get_connection, init_db
from app.jobs import recompute_jobs_scorability
from app.worker_logging import get_logger

LOGGER = get_logger("scripts.recompute_job_scorability")


def main() -> None:
    """Entrypoint for backfilling jobs.is_scorable fields."""
    try:
        config = load_local_worker_config(context="recompute_job_scorability")
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
