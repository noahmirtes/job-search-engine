"""Backfill jobs table from already stored raw_requests payloads."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import initialize_config
from app.db import get_connection, init_db
from app.jobs import upsert_jobs_from_raw_response_json
from _default_paths import _default_paths


def main() -> None:
    """Replay raw requests into jobs using shared parse/hash/upsert logic."""
    config = initialize_config(_default_paths(PROJECT_ROOT))
    init_db(config.paths.db_path)

    raw_requests_processed = 0
    total_jobs_upserted = 0

    with get_connection(config.paths.db_path) as connection:
        rows = connection.execute(
            "SELECT id, query_name, response_json, requested_at FROM raw_requests "
            "ORDER BY requested_at ASC, id ASC"
        ).fetchall()

        for row in rows:
            query_name = row["query_name"]
            response_json = row["response_json"]
            requested_at = row["requested_at"]
            total_jobs_upserted += upsert_jobs_from_raw_response_json(
                connection,
                response_json,
                anchor_requested_at_utc=requested_at,
                query_name=query_name,
            )
            raw_requests_processed += 1

    print(f"Raw requests processed: {raw_requests_processed}")
    print(f"Total jobs upserted: {total_jobs_upserted}")


if __name__ == "__main__":
    main()
