"""Run configured LLM scoring against jobs stored in the local DB."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import initialize_config
from app.db import get_connection, init_db
from app.scoring import run_job_scoring
from app.worker_logging import get_logger, log_worker_startup, setup_worker_logging
from _default_paths import _default_paths

LOGGER = get_logger("scripts.run_scoring")


def main() -> None:
    """Entrypoint for scoring all jobs with the configured Ollama model."""
    setup_worker_logging()
    try:
        config = initialize_config(_default_paths(PROJECT_ROOT))
        setup_worker_logging(config.paths.log_path)
        log_worker_startup(config, context="run_scoring")
        LOGGER.info("Script start: run_scoring")
        init_db(config.paths.db_path)

        with get_connection(config.paths.db_path) as connection:
            summary = run_job_scoring(connection, config, only_unscored=False)

        LOGGER.info(
            "Script complete: run_scoring version=%s provider=%s jobs_selected=%s rule_model=%s rule_ok=%s rule_failed=%s fit_model=%s fit_attempted=%s fit_ok=%s fit_failed=%s",
            summary.scoring_version,
            summary.llm_provider,
            summary.jobs_selected,
            summary.rule_model,
            summary.jobs_scored_ok,
            summary.jobs_failed,
            summary.fit_model,
            summary.fit_jobs_attempted,
            summary.fit_jobs_scored_ok,
            summary.fit_jobs_failed,
        )
    except Exception:
        LOGGER.exception("Script failed: run_scoring")
        raise


if __name__ == "__main__":
    main()
