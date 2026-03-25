"""SQLite schema and persistence helpers for ingestion/runtime state."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


# Canonical schema applied on fresh DB creation.
SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS raw_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_name TEXT NOT NULL,
    query_params_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    response_status INTEGER NOT NULL,
    result_count INTEGER,
    requested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_job_id TEXT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    description TEXT,
    apply_url TEXT,
    share_link TEXT,
    via TEXT,
    thumbnail TEXT,
    posted_at_text TEXT,
    schedule_type TEXT,
    work_from_home INTEGER,
    qualifications_text TEXT,
    raw_job_json TEXT,
    apply_options_json TEXT,
    extensions_json TEXT,
    detected_extensions_json TEXT,
    job_highlights_json TEXT,
    date_posted TEXT,
    normalized_hash TEXT NOT NULL UNIQUE,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    rule_score REAL NOT NULL,
    resume_embedding_score REAL,
    ideal_job_embedding_score REAL,
    total_score REAL NOT NULL,
    scoring_version TEXT NOT NULL,
    scored_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    UNIQUE(job_id, scoring_version)
);

CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exported_at TEXT NOT NULL,
    export_file_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS export_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    export_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    FOREIGN KEY (export_id) REFERENCES exports(id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    UNIQUE(export_id, job_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_requests_query_name ON raw_requests(query_name);
CREATE INDEX IF NOT EXISTS idx_jobs_normalized_hash ON jobs(normalized_hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_source_job_id
ON jobs(source_job_id)
WHERE source_job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_job_scores_job_id ON job_scores(job_id);
CREATE INDEX IF NOT EXISTS idx_export_jobs_job_id ON export_jobs(job_id);
"""


def utc_now_iso() -> str:
    """Return current UTC timestamp as ISO-8601 seconds precision."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def init_db(db_path: Path) -> None:
    """Initialize DB schema and apply non-destructive schema syncs."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA)
        _sync_jobs_table_schema(connection)
        connection.commit()


def _sync_jobs_table_schema(connection: sqlite3.Connection) -> None:
    """Keep existing jobs tables aligned with the latest schema."""
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(jobs)")
    }
    required_columns: dict[str, str] = {
        "share_link": "TEXT",
        "via": "TEXT",
        "thumbnail": "TEXT",
        "posted_at_text": "TEXT",
        "schedule_type": "TEXT",
        "work_from_home": "INTEGER",
        "qualifications_text": "TEXT",
        "raw_job_json": "TEXT",
        "apply_options_json": "TEXT",
        "extensions_json": "TEXT",
        "detected_extensions_json": "TEXT",
        "job_highlights_json": "TEXT",
    }

    for column_name, column_type in required_columns.items():
        if column_name in columns:
            continue
        connection.execute(
            f"ALTER TABLE jobs ADD COLUMN {column_name} {column_type}"
        )

    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_source_job_id
        ON jobs(source_job_id)
        WHERE source_job_id IS NOT NULL
        """
    )


@contextmanager
def get_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection with commit/close lifecycle handled."""
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def log_raw_request(
    connection: sqlite3.Connection,
    *,
    query_name: str,
    query_params: dict[str, Any],
    response_payload: dict[str, Any],
    response_status: int,
    requested_at: str | None = None,
) -> int:
    """Persist one raw API request/response payload and return row id."""
    jobs_results = response_payload.get("jobs_results", [])
    result_count = len(jobs_results) if isinstance(jobs_results, list) else None
    effective_requested_at = requested_at or utc_now_iso()

    cursor = connection.execute(
        """
        INSERT INTO raw_requests (
            query_name,
            query_params_json,
            response_json,
            response_status,
            result_count,
            requested_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            query_name,
            json.dumps(query_params, sort_keys=True),
            json.dumps(response_payload, sort_keys=True),
            response_status,
            result_count,
            effective_requested_at,
        ),
    )
    return int(cursor.lastrowid)
