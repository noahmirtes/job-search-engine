from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import WorkerPaths, initialize_config
from app.db import init_db


def _default_paths(project_root: Path) -> WorkerPaths:
    config_dir = project_root / "config"
    return WorkerPaths(
        db_path=config_dir / "jobs.db",
        log_path=config_dir / "worker.log",
        queries_path=config_dir / "queries.json",
        ideal_job_path=config_dir / "ideal_job.txt",
        resume_path=config_dir / "resume.txt",
        env_path=config_dir / ".env",
    )


def main() -> None:
    config = initialize_config(_default_paths(PROJECT_ROOT))
    init_db(config.paths.db_path)
    print(f"Initialized database at {config.paths.db_path}")


if __name__ == "__main__":
    main()
