"""Generate the export workbook from scored jobs in the local database."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import initialize_config
from app.db import get_connection, init_db
from app.reporting import generate_report
from app.scoring import run_job_scoring
from app.worker_logging import get_logger, log_worker_startup, setup_worker_logging
from _default_paths import _default_paths

LOGGER = get_logger("scripts.score_and_report")


def main() -> None:
    """Entrypoint for building one report workbook and storing export metadata."""
    setup_worker_logging()
    try:
        config = initialize_config(_default_paths(PROJECT_ROOT))
        setup_worker_logging(config.paths.log_path)
        log_worker_startup(config, context="score_and_report")
        LOGGER.info("Script start: score_and_report")
        init_db(config.paths.db_path)

        LOGGER.info("Script phase start: scoring")
        with get_connection(config.paths.db_path) as connection:
            scoring_summary = run_job_scoring(connection, config, only_unscored=False)

        LOGGER.info("Script phase start: reporting")
        with get_connection(config.paths.db_path) as connection:
            summary = generate_report(connection, config)

        LOGGER.info(
            "Script complete: score_and_report version=%s provider=%s jobs_selected=%s rule_ok=%s rule_failed=%s fit_attempted=%s fit_ok=%s fit_failed=%s export_id=%s path=%s new_rows=%s all_rows=%s all_jobs_list_rows=%s",
            scoring_summary.scoring_version,
            scoring_summary.llm_provider,
            scoring_summary.jobs_selected,
            scoring_summary.jobs_scored_ok,
            scoring_summary.jobs_failed,
            scoring_summary.fit_jobs_attempted,
            scoring_summary.fit_jobs_scored_ok,
            scoring_summary.fit_jobs_failed,
            summary.export_id,
            summary.export_path,
            summary.new_count,
            summary.all_count,
            summary.all_jobs_list_count,
        )
    except Exception:
        LOGGER.exception("Script failed: score_and_report")
        raise


if __name__ == "__main__":
    main()
