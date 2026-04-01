"""Report export flow: query scored jobs, write workbook tabs, track exports."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import WorkerConfig
from app.db import utc_now_iso


@dataclass(frozen=True)
class ReportRunSummary:
    """Run summary returned after one report export."""

    export_id: int
    export_path: Path
    new_count: int
    all_count: int
    all_jobs_list_count: int


def generate_report(
    connection: sqlite3.Connection,
    config: WorkerConfig,
) -> ReportRunSummary:
    """Generate one Excel report and record export metadata in the DB."""
    scoring_version = config.scoring_config.version
    threshold = config.scoring_config.report.threshold
    include_all_jobs_list = config.scoring_config.report.include_all_jobs_list

    all_rows = _fetch_scored_rows(
        connection=connection,
        scoring_version=scoring_version,
        threshold=threshold,
    )

    last_exported_at = _get_latest_exported_at(connection)
    if last_exported_at is None:
        new_rows = all_rows
    else:
        new_rows = [
            row for row in all_rows
            if _as_text(row["first_seen_at"]) and _as_text(row["first_seen_at"]) > last_exported_at
        ]

    all_jobs_list_rows: list[sqlite3.Row] = []
    if include_all_jobs_list:
        all_jobs_list_rows = _fetch_all_jobs_rows(
            connection=connection,
            scoring_version=scoring_version,
        )

    report_file_name = _build_report_file_name()
    report_path = config.paths.report_export_dir / report_file_name
    _write_report_workbook(
        report_path=report_path,
        new_rows=new_rows,
        all_rows=all_rows,
        all_jobs_list_rows=all_jobs_list_rows,
        include_all_jobs_list=include_all_jobs_list,
    )

    export_id = _insert_export(connection, report_file_name)
    _insert_export_jobs(
        connection=connection,
        export_id=export_id,
        job_ids=[int(row["job_id"]) for row in new_rows],
    )

    return ReportRunSummary(
        export_id=export_id,
        export_path=report_path,
        new_count=len(new_rows),
        all_count=len(all_rows),
        all_jobs_list_count=len(all_jobs_list_rows),
    )


def _fetch_scored_rows(
    *,
    connection: sqlite3.Connection,
    scoring_version: str,
    threshold: float,
) -> list[sqlite3.Row]:
    """Load threshold-qualified scored jobs for the configured scoring version."""
    rows = connection.execute(
        """
        SELECT
            jobs.id AS job_id,
            jobs.title,
            jobs.company,
            jobs.location,
            jobs.description,
            jobs.date_posted,
            jobs.schedule_type,
            jobs.qualifications_text,
            jobs.extensions_json,
            jobs.detected_extensions_json,
            jobs.apply_options_json,
            jobs.first_seen_at,
            jobs.last_seen_at,
            job_scores.total_score,
            job_scores.scored_at
        FROM jobs
        JOIN job_scores
            ON job_scores.job_id = jobs.id
        WHERE job_scores.scoring_version = ?
          AND job_scores.scoring_status = 'ok'
          AND job_scores.total_score >= ?
          AND jobs.is_scorable = 1
        ORDER BY job_scores.total_score DESC, jobs.last_seen_at DESC, jobs.id DESC
        """,
        (scoring_version, threshold),
    ).fetchall()
    return [row for row in rows if isinstance(row, sqlite3.Row)]


def _fetch_all_jobs_rows(
    *,
    connection: sqlite3.Connection,
    scoring_version: str,
) -> list[sqlite3.Row]:
    """Load all jobs, attaching score when available for the configured version."""
    rows = connection.execute(
        """
        SELECT
            jobs.id AS job_id,
            jobs.title,
            jobs.company,
            jobs.location,
            jobs.description,
            jobs.date_posted,
            jobs.schedule_type,
            jobs.qualifications_text,
            jobs.extensions_json,
            jobs.detected_extensions_json,
            jobs.apply_options_json,
            jobs.first_seen_at,
            jobs.last_seen_at,
            job_scores.total_score,
            job_scores.scored_at
        FROM jobs
        LEFT JOIN job_scores
            ON job_scores.job_id = jobs.id
           AND job_scores.scoring_version = ?
           AND job_scores.scoring_status = 'ok'
        WHERE jobs.is_scorable = 1
        ORDER BY
            CASE WHEN job_scores.total_score IS NULL THEN 1 ELSE 0 END ASC,
            job_scores.total_score DESC,
            jobs.last_seen_at DESC,
            jobs.id DESC
        """,
        (scoring_version,),
    ).fetchall()
    return [row for row in rows if isinstance(row, sqlite3.Row)]


def _get_latest_exported_at(connection: sqlite3.Connection) -> str | None:
    """Return the timestamp of the most recent export, if any."""
    row = connection.execute(
        "SELECT exported_at FROM exports ORDER BY exported_at DESC, id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return _as_text(row["exported_at"] if isinstance(row, sqlite3.Row) else row[0])


def _write_report_workbook(
    *,
    report_path: Path,
    new_rows: list[sqlite3.Row],
    all_rows: list[sqlite3.Row],
    all_jobs_list_rows: list[sqlite3.Row],
    include_all_jobs_list: bool,
) -> None:
    """Write Excel workbook with required tabs and dynamic apply columns."""
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
        _to_dataframe(new_rows).to_excel(writer, sheet_name="new", index=False)
        _to_dataframe(all_rows).to_excel(writer, sheet_name="all", index=False)
        if include_all_jobs_list:
            _to_dataframe(all_jobs_list_rows).to_excel(
                writer,
                sheet_name="all_jobs_list",
                index=False,
            )


def _to_dataframe(rows: list[sqlite3.Row]) -> pd.DataFrame:
    """Convert DB rows into report-ready rows with trailing apply-option columns."""
    max_apply_options = 0
    parsed_options_by_job: dict[int, list[tuple[str, str]]] = {}

    for row in rows:
        job_id = int(row["job_id"])
        options = _parse_apply_options(row["apply_options_json"])
        parsed_options_by_job[job_id] = options
        max_apply_options = max(max_apply_options, len(options))

    columns = [
        "Job ID",
        "Score",
        "Title",
        "Company",
        "Location",
        "Description",
        "Date Posted",
        "Schedule Type",
        "Qualifications",
        "Extensions",
        "Detected Extensions",
    ]
    for index in range(1, max_apply_options + 1):
        columns.append(f"Apply Location {index}")
        columns.append(f"Apply Link {index}")

    records: list[dict[str, Any]] = []
    for row in rows:
        job_id = int(row["job_id"])
        options = parsed_options_by_job[job_id]

        record: dict[str, Any] = {
            "Job ID": job_id,
            "Score": row["total_score"],
            "Title": _as_text(row["title"]) or "",
            "Company": _as_text(row["company"]) or "",
            "Location": _as_text(row["location"]) or "",
            "Description": _as_text(row["description"]) or "",
            "Date Posted": _as_text(row["date_posted"]) or "",
            "Schedule Type": _as_text(row["schedule_type"]) or "",
            "Qualifications": _as_text(row["qualifications_text"]) or "",
            "Extensions": _as_text(row["extensions_json"]) or "",
            "Detected Extensions": _as_text(row["detected_extensions_json"]) or "",
        }

        for index in range(max_apply_options):
            column_index = index + 1
            if index < len(options):
                apply_location, apply_link = options[index]
            else:
                apply_location, apply_link = "", ""
            record[f"Apply Location {column_index}"] = apply_location
            record[f"Apply Link {column_index}"] = apply_link

        records.append(record)

    return pd.DataFrame(records, columns=columns)


def _parse_apply_options(raw_apply_options_json: str | None) -> list[tuple[str, str]]:
    """Extract ordered (location, link) tuples from apply_options_json."""
    if not raw_apply_options_json:
        return []
    try:
        payload = json.loads(raw_apply_options_json)
    except json.JSONDecodeError:
        return []

    if not isinstance(payload, list):
        return []

    items: list[tuple[str, str]] = []
    for option in payload:
        if not isinstance(option, dict):
            continue

        location = (
            _as_text(option.get("title"))
            or _as_text(option.get("via"))
            or _as_text(option.get("source"))
            or ""
        )
        link = (
            _as_text(option.get("link"))
            or _as_text(option.get("apply_link"))
            or _as_text(option.get("url"))
            or ""
        )

        if location or link:
            items.append((location, link))

    return items


def _build_report_file_name() -> str:
    """Build stable timestamped report filename."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"job_report_{stamp}.xlsx"


def _insert_export(connection: sqlite3.Connection, report_file_name: str) -> int:
    """Insert an exports row and return new export id."""
    cursor = connection.execute(
        "INSERT INTO exports (exported_at, export_file_name) VALUES (?, ?)",
        (utc_now_iso(), report_file_name),
    )
    return int(cursor.lastrowid)


def _insert_export_jobs(
    *,
    connection: sqlite3.Connection,
    export_id: int,
    job_ids: list[int],
) -> None:
    """Link jobs surfaced in the new tab to the export run."""
    if not job_ids:
        return
    connection.executemany(
        "INSERT OR IGNORE INTO export_jobs (export_id, job_id) VALUES (?, ?)",
        [(export_id, job_id) for job_id in job_ids],
    )


def _as_text(value: Any) -> str | None:
    """Normalize optional values to trimmed text."""
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None
