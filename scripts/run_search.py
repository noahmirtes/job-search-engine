"""Run enabled query ingestion: fetch pages, archive raw, upsert jobs."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import WorkerPaths, initialize_config
from app.search import run_enabled_queries


def _default_paths(project_root: Path) -> WorkerPaths:
    """Build default single-profile path mapping for local runs."""
    config_dir = project_root / "config"
    return WorkerPaths(
        db_path=config_dir / "jobs.db",
        log_path=config_dir / "worker.log",
        queries_path=config_dir / "queries.json",
        scoring_path=config_dir / "scoring.json",
        ideal_job_path=config_dir / "ideal_job.txt",
        resume_path=config_dir / "resume.txt",
        env_path=config_dir / ".env",
        report_export_dir=config_dir / "reports",
    )


def main() -> None:
    """Entrypoint for running the full enabled-query ingest flow."""
    config = initialize_config(_default_paths(PROJECT_ROOT))
    summary = run_enabled_queries(config)

    print(f"Queries run: {summary.queries_run}")
    print(f"Total pages fetched: {summary.total_pages_fetched}")
    print(f"Total raw requests stored: {summary.total_raw_requests_stored}")
    print(f"Total jobs upserted: {summary.total_jobs_upserted}")
    print(f"Total query errors: {summary.total_error_count}")
    for query_summary in summary.query_summaries:
        line = (
            f"- {query_summary.query_name}: "
            f"{query_summary.pages_fetched} pages, "
            f"{len(query_summary.stored_request_ids)} stored requests, "
            f"{query_summary.jobs_upserted} jobs upserted, "
            f"{query_summary.error_count} errors"
        )
        if query_summary.last_error_message:
            line += f" (last error: {query_summary.last_error_message})"
        print(line)


if __name__ == "__main__":
    main()
