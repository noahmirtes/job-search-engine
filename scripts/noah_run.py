"""Run the local end-to-end pipeline from Noah's hard-coded config setup."""

import sys
from pathlib import Path

PROJECT_ROOT = Path("/Users/noah/REPOS/job-search-engine")
CONFIG_DIR = Path("/Users/noah/REPOS/job-search-engine/config")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import WorkerConfig, WorkerPaths, initialize_config
from app.db import get_connection, init_db

# ------------------------------------------------------------------- #

def default_paths() -> WorkerPaths:
    """Build the hard-coded local path mapping for Noah's runs."""
    return WorkerPaths(
        db_path=CONFIG_DIR / "jobs.db",
        log_path=CONFIG_DIR / "worker.log",
        queries_path=CONFIG_DIR / "queries.json",
        scoring_path=CONFIG_DIR / "scoring.json",
        ideal_job_path=CONFIG_DIR / "ideal_job.txt",
        resume_path=CONFIG_DIR / "resume.txt",
        env_path=CONFIG_DIR / ".env",
        report_export_dir=CONFIG_DIR / "reports",
    )

def run_search(config: WorkerConfig) -> None:
    """Run search and print a compact stage summary."""
    from app.search import run_enabled_queries

    summary = run_enabled_queries(config)

    print("[search]")
    print(f"Queries run: {summary.queries_run}")
    print(f"Pages fetched: {summary.total_pages_fetched}")
    print(f"Raw requests stored: {summary.total_raw_requests_stored}")
    print(f"Jobs upserted: {summary.total_jobs_upserted}")
    print(f"Query errors: {summary.total_error_count}")

def run_scoring(config: WorkerConfig, *, rescore_all: bool) -> None:
    """Run scoring and print a compact stage summary."""
    from app.scoring import run_job_scoring

    with get_connection(config.paths.db_path) as connection:
        summary = run_job_scoring(
            connection,
            config,
            only_unscored=not rescore_all,
        )

    print("[scoring]")
    print(f"Scoring version: {summary.scoring_version}")
    print(f"LLM provider/model: {summary.llm_provider}/{summary.llm_model}")
    print(f"Jobs selected: {summary.jobs_selected}")
    print(f"Jobs scored (ok): {summary.jobs_scored_ok}")
    print(f"Jobs failed: {summary.jobs_failed}")

def run_report(config: WorkerConfig) -> None:
    """Run report generation and print a compact stage summary."""
    from app.reporting import generate_report

    with get_connection(config.paths.db_path) as connection:
        summary = generate_report(connection, config)

    print("[report]")
    print(f"Export id: {summary.export_id}")
    print(f"Report path: {summary.export_path}")
    print(f"Rows in 'new' tab: {summary.new_count}")
    print(f"Rows in 'all' tab: {summary.all_count}")
    if config.scoring_config.report.include_all_jobs_list:
        print(f"Rows in 'all_jobs_list' tab: {summary.all_jobs_list_count}")

# ------------------------------------------------------------------- #
# Local run toggles.
RUN_SEARCH = True
RUN_SCORING = True
RUN_REPORT = True
RESCORE_ALL = False

def main() -> None:
    """Run the local pipeline from the hard-coded config directory."""
    config = initialize_config(default_paths())
    init_db(config.paths.db_path)

    if RUN_SEARCH:
        run_search(config)

    if RUN_SCORING:
        run_scoring(config, rescore_all=RESCORE_ALL)

    if RUN_REPORT:
        run_report(config)


if __name__ == "__main__":
    main()
