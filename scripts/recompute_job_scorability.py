"""Recompute scoring eligibility flags for all normalized jobs rows."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import WorkerPaths, initialize_config
from app.db import get_connection, init_db
from app.jobs import recompute_jobs_scorability


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
    """Entrypoint for backfilling jobs.is_scorable fields."""
    config = initialize_config(_default_paths(PROJECT_ROOT))
    init_db(config.paths.db_path)

    with get_connection(config.paths.db_path) as connection:
        updated_count = recompute_jobs_scorability(connection)

    print(f"Jobs eligibility recomputed: {updated_count}")


if __name__ == "__main__":
    main()
