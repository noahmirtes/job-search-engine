"""Initialize/sync the local SQLite schema for the current profile."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import initialize_config
from app.db import init_db

from _default_paths import _default_paths


def main() -> None:
    """Entrypoint for creating/upgrading the local jobs database."""
    config = initialize_config(_default_paths(PROJECT_ROOT))
    init_db(config.paths.db_path)
    print(f"Initialized database at {config.paths.db_path}")


if __name__ == "__main__":
    main()
