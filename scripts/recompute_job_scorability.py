"""Recompute scoring eligibility flags for all normalized jobs rows."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import initialize_config
from app.db import get_connection, init_db
from app.jobs import recompute_jobs_scorability

from _default_paths import _default_paths


def main() -> None:
    """Entrypoint for backfilling jobs.is_scorable fields."""
    config = initialize_config(_default_paths(PROJECT_ROOT))
    init_db(config.paths.db_path)

    with get_connection(config.paths.db_path) as connection:
        updated_count = recompute_jobs_scorability(connection)

    print(f"Jobs eligibility recomputed: {updated_count}")


if __name__ == "__main__":
    main()
