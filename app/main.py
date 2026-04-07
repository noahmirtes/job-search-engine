"""Small local entrypoint for config/bootstrap sanity checks."""

from __future__ import annotations

from pathlib import Path

from config import WorkerPaths, initialize_config
from db import init_db


# ---------------------------------------------------- HELPERS ----
def _default_paths(project_root: Path) -> WorkerPaths:
    """Build default local profile paths."""
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


# ---------------------------------------------------- ENTRYPOINTS ----
def main() -> None:
    """Initialize config + DB for manual local smoke runs."""
    #project_root = Path(__file__).resolve().parent.parent

    project_root = Path("/Users/noah/REPOS/job-search-engine")
    config = initialize_config(_default_paths(project_root))
    init_db(config.paths.db_path)

    print(config.queries)
    



if __name__ == "__main__":
    main()
