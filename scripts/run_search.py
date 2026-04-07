"""Run enabled query ingestion: fetch pages, archive raw, upsert jobs."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import initialize_config
from app.search import run_enabled_queries
from app.worker_logging import get_logger, log_worker_startup, setup_worker_logging

from _default_paths import _default_paths

LOGGER = get_logger("scripts.run_search")


def main() -> None:
    """Entrypoint for running the full enabled-query ingest flow."""
    setup_worker_logging()
    try:
        config = initialize_config(_default_paths(PROJECT_ROOT))
        setup_worker_logging(config.paths.log_path)
        log_worker_startup(config, context="run_search")
        LOGGER.info("Script start: run_search")
        summary = run_enabled_queries(config)
        LOGGER.info(
            "Script complete: run_search queries=%s pages=%s raw_requests=%s jobs_upserted=%s errors=%s",
            summary.queries_run,
            summary.total_pages_fetched,
            summary.total_raw_requests_stored,
            summary.total_jobs_upserted,
            summary.total_error_count,
        )
        for query_summary in summary.query_summaries:
            LOGGER.info(
                "Script query summary: query=%s pages=%s stored_requests=%s jobs_upserted=%s errors=%s last_error=%s",
                query_summary.query_name,
                query_summary.pages_fetched,
                len(query_summary.stored_request_ids),
                query_summary.jobs_upserted,
                query_summary.error_count,
                query_summary.last_error_message or "",
            )
    except Exception:
        LOGGER.exception("Script failed: run_search")
        raise


if __name__ == "__main__":
    main()
