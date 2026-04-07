"""Run search, scoring, and report generation for a single profile."""

from __future__ import annotations

from pathlib import Path

from app.config import WorkerPaths, initialize_config
from app.db import get_connection, init_db
from app.reporting import generate_report
from app.scoring import run_job_scoring
from app.search import run_enabled_queries
from app.worker_logging import get_logger, log_worker_startup, setup_worker_logging
from orchestrator.models import PipelineResult, ProfileConfig

LOGGER = get_logger("pipeline")


def run_profile_pipeline(profile: ProfileConfig) -> PipelineResult:
    """Run one full worker pipeline and return a compact summary."""
    setup_worker_logging()
    try:
        worker_paths = _build_worker_paths(profile)
        worker_config = initialize_config(worker_paths)
        setup_worker_logging(worker_config.paths.log_path)
        log_worker_startup(worker_config, context=f"profile:{profile.id}")
        LOGGER.info("Worker pipeline start: profile=%s", profile.id)

        init_db(worker_config.paths.db_path)
        search_summary = run_enabled_queries(worker_config)

        with get_connection(worker_config.paths.db_path) as connection:
            scoring_summary = run_job_scoring(connection, worker_config, only_unscored=False)

        with get_connection(worker_config.paths.db_path) as connection:
            report_summary = generate_report(connection, worker_config)

        result = PipelineResult(
            profile_id=profile.id,
            report_path=Path(report_summary.export_path),
            new_count=report_summary.new_count,
            all_count=report_summary.all_count,
            pages_fetched=search_summary.total_pages_fetched,
            jobs_upserted=search_summary.total_jobs_upserted,
            jobs_scored_ok=scoring_summary.jobs_scored_ok,
        )
        LOGGER.info(
            "Worker pipeline complete: profile=%s pages_fetched=%s jobs_upserted=%s jobs_scored_ok=%s report_new=%s",
            profile.id,
            result.pages_fetched,
            result.jobs_upserted,
            result.jobs_scored_ok,
            result.new_count,
        )
        return result
    except Exception:
        LOGGER.exception("Worker pipeline failed: profile=%s", profile.id)
        raise

def _build_worker_paths(profile: ProfileConfig) -> WorkerPaths:
    """Map profile paths into the existing worker path contract."""
    log_path = profile.paths.log_path or (profile.paths.db_path.parent / "worker.log")
    return WorkerPaths(
        db_path=profile.paths.db_path,
        log_path=log_path,
        queries_path=profile.paths.queries_path,
        scoring_path=profile.paths.scoring_path,
        ideal_job_path=profile.paths.ideal_job_path,
        resume_path=profile.paths.resume_path,
        env_path=profile.paths.env_path,
        report_export_dir=profile.paths.report_export_dir,
    )
