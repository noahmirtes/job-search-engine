"""Run configured LLM scoring against jobs stored in the local DB."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import WorkerPaths, initialize_config
from app.db import get_connection, init_db
from app.scoring import run_job_scoring


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
    )


def main() -> None:
    """Entrypoint for scoring all jobs with the configured Ollama model."""
    config = initialize_config(_default_paths(PROJECT_ROOT))
    init_db(config.paths.db_path)

    with get_connection(config.paths.db_path) as connection:
        summary = run_job_scoring(connection, config, only_unscored=False)

    print(f"Scoring version: {summary.scoring_version}")
    print(f"LLM provider/model: {summary.llm_provider}/{summary.llm_model}")
    print(f"Jobs selected: {summary.jobs_selected}")
    print(f"Jobs scored (ok): {summary.jobs_scored_ok}")
    print(f"Jobs failed: {summary.jobs_failed}")


if __name__ == "__main__":
    main()
