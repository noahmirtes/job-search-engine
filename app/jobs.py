"""Job normalization and upsert logic shared by live ingest and backfill."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.db import utc_now_iso
from app.posting_date import derive_posted_date


# Normalized in-memory job shape before DB write.
@dataclass(frozen=True)
class JobRecord:
    source_job_id: str | None
    title: str
    company: str
    location: str | None
    description: str | None
    apply_url: str | None
    share_link: str | None
    via: str | None
    thumbnail: str | None
    posted_at_text: str | None
    schedule_type: str | None
    work_from_home: int | None
    qualifications_text: str | None
    raw_job_json: str
    apply_options_json: str
    extensions_json: str
    detected_extensions_json: str
    job_highlights_json: str
    date_posted: str | None
    is_scorable: int
    scorable_missing_fields_json: str
    query_names_json: str
    normalized_hash: str


def upsert_jobs_from_payload(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    anchor_requested_at_utc: str,
    query_name: str | None = None,
) -> int:
    """Parse payload jobs_results and upsert each job into the jobs table."""
    jobs_results = payload.get("jobs_results")
    if not isinstance(jobs_results, list):
        return 0

    processed_count = 0
    for raw_job in jobs_results:
        if not isinstance(raw_job, dict):
            continue
        record = _to_job_record(
            raw_job,
            anchor_requested_at_utc=anchor_requested_at_utc,
            query_name=query_name,
        )
        _upsert_job(connection, record)
        processed_count += 1

    return processed_count


def upsert_jobs_from_raw_response_json(
    connection: sqlite3.Connection,
    response_json: str,
    *,
    anchor_requested_at_utc: str,
    query_name: str | None = None,
) -> int:
    """Decode raw response JSON and upsert contained jobs."""
    payload = json.loads(response_json)
    if not isinstance(payload, dict):
        return 0
    return upsert_jobs_from_payload(
        connection,
        payload,
        anchor_requested_at_utc=anchor_requested_at_utc,
        query_name=query_name,
    )


def _to_job_record(
    raw_job: dict[str, Any],
    *,
    anchor_requested_at_utc: str,
    query_name: str | None = None,
) -> JobRecord:
    """Map a raw SerpApi job object into the normalized JobRecord shape."""
    source_job_id = _as_text(raw_job.get("job_id"))
    title = _as_text(raw_job.get("title")) or "Unknown title"
    company = _as_text(raw_job.get("company_name")) or "Unknown company"
    location = _as_text(raw_job.get("location"))
    description = _as_text(raw_job.get("description"))
    share_link = _as_text(raw_job.get("share_link"))
    via = _as_text(raw_job.get("via"))
    thumbnail = _as_text(raw_job.get("thumbnail"))

    apply_options = raw_job.get("apply_options")
    if not isinstance(apply_options, list):
        apply_options = []
    apply_url = _first_apply_url(apply_options)

    extensions = raw_job.get("extensions")
    if not isinstance(extensions, list):
        extensions = []

    detected_extensions = raw_job.get("detected_extensions")
    if not isinstance(detected_extensions, dict):
        detected_extensions = {}

    job_highlights = raw_job.get("job_highlights")
    if not isinstance(job_highlights, list):
        job_highlights = []

    posted_at_text = _as_text(detected_extensions.get("posted_at"))
    schedule_type = _as_text(detected_extensions.get("schedule_type"))
    qualifications_text = _as_text(detected_extensions.get("qualifications"))
    work_from_home = _as_int_bool(detected_extensions.get("work_from_home"))

    normalized_hash = _build_normalized_hash(
        source_job_id=source_job_id,
        title=title,
        company=company,
        location=location,
        apply_url=apply_url,
        share_link=share_link,
    )

    date_posted = derive_posted_date(posted_at_text, anchor_requested_at_utc)
    missing_fields = _compute_scorable_missing_fields(
        title=title,
        company=company,
        description=description,
        apply_url=apply_url,
    )
    is_scorable = 1 if not missing_fields else 0

    return JobRecord(
        source_job_id=source_job_id,
        title=title,
        company=company,
        location=location,
        description=description,
        apply_url=apply_url,
        share_link=share_link,
        via=via,
        thumbnail=thumbnail,
        posted_at_text=posted_at_text,
        schedule_type=schedule_type,
        work_from_home=work_from_home,
        qualifications_text=qualifications_text,
        raw_job_json=json.dumps(raw_job, sort_keys=True),
        apply_options_json=json.dumps(apply_options, sort_keys=True),
        extensions_json=json.dumps(extensions, sort_keys=True),
        detected_extensions_json=json.dumps(detected_extensions, sort_keys=True),
        job_highlights_json=json.dumps(job_highlights, sort_keys=True),
        date_posted=date_posted,
        is_scorable=is_scorable,
        scorable_missing_fields_json=json.dumps(missing_fields, sort_keys=True),
        query_names_json=json.dumps(_normalize_query_names([query_name])),
        normalized_hash=normalized_hash,
    )


def _upsert_job(connection: sqlite3.Connection, record: JobRecord) -> None:
    """Insert or update a job record using source id/hash identity."""
    existing_job_row = _find_existing_job_row(
        connection=connection,
        source_job_id=record.source_job_id,
        normalized_hash=record.normalized_hash,
    )
    existing_job_id = None if existing_job_row is None else int(existing_job_row["id"])

    now = utc_now_iso()
    if existing_job_id is None:
        connection.execute(
            """
            INSERT INTO jobs (
                source_job_id,
                title,
                company,
                location,
                description,
                apply_url,
                share_link,
                via,
                thumbnail,
                posted_at_text,
                schedule_type,
                work_from_home,
                qualifications_text,
                raw_job_json,
                apply_options_json,
                extensions_json,
                detected_extensions_json,
                job_highlights_json,
                date_posted,
                is_scorable,
                scorable_missing_fields_json,
                query_names_json,
                normalized_hash,
                first_seen_at,
                last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.source_job_id,
                record.title,
                record.company,
                record.location,
                record.description,
                record.apply_url,
                record.share_link,
                record.via,
                record.thumbnail,
                record.posted_at_text,
                record.schedule_type,
                record.work_from_home,
                record.qualifications_text,
                record.raw_job_json,
                record.apply_options_json,
                record.extensions_json,
                record.detected_extensions_json,
                record.job_highlights_json,
                record.date_posted,
                record.is_scorable,
                record.scorable_missing_fields_json,
                record.query_names_json,
                record.normalized_hash,
                now,
                now,
            ),
        )
        return

    merged_query_names_json = _merge_query_names_json(
        existing_job_row["query_names_json"],
        record.query_names_json,
    )

    connection.execute(
        """
        UPDATE jobs
        SET
            source_job_id = ?,
            title = ?,
            company = ?,
            location = ?,
            description = ?,
            apply_url = ?,
            share_link = ?,
            via = ?,
            thumbnail = ?,
            posted_at_text = ?,
            schedule_type = ?,
            work_from_home = ?,
            qualifications_text = ?,
            raw_job_json = ?,
            apply_options_json = ?,
            extensions_json = ?,
            detected_extensions_json = ?,
            job_highlights_json = ?,
            date_posted = ?,
            is_scorable = ?,
            scorable_missing_fields_json = ?,
            query_names_json = ?,
            normalized_hash = ?,
            last_seen_at = ?
        WHERE id = ?
        """,
        (
            record.source_job_id,
            record.title,
            record.company,
            record.location,
            record.description,
            record.apply_url,
            record.share_link,
            record.via,
            record.thumbnail,
            record.posted_at_text,
            record.schedule_type,
            record.work_from_home,
            record.qualifications_text,
            record.raw_job_json,
            record.apply_options_json,
            record.extensions_json,
            record.detected_extensions_json,
            record.job_highlights_json,
            record.date_posted,
            record.is_scorable,
            record.scorable_missing_fields_json,
            merged_query_names_json,
            record.normalized_hash,
            now,
            existing_job_id,
        ),
    )


def _find_existing_job_row(
    connection: sqlite3.Connection,
    *,
    source_job_id: str | None,
    normalized_hash: str,
) -> sqlite3.Row | None:
    """Find existing job row by source id first, then fallback normalized hash."""
    if source_job_id:
        row = connection.execute(
            "SELECT id, query_names_json FROM jobs WHERE source_job_id = ? LIMIT 1",
            (source_job_id,),
        ).fetchone()
        if row is not None:
            return row if isinstance(row, sqlite3.Row) else None

    row = connection.execute(
        "SELECT id, query_names_json FROM jobs WHERE normalized_hash = ? LIMIT 1",
        (normalized_hash,),
    ).fetchone()
    return row if isinstance(row, sqlite3.Row) else None


def _build_normalized_hash(
    *,
    source_job_id: str | None,
    title: str,
    company: str,
    location: str | None,
    apply_url: str | None,
    share_link: str | None,
) -> str:
    """Build stable dedupe hash from source id or normalized fallback fields."""
    if source_job_id:
        identity = f"id:{source_job_id.strip().lower()}"
    else:
        pieces = [
            title.strip().lower(),
            company.strip().lower(),
            (location or "").strip().lower(),
            (apply_url or "").strip().lower(),
            (share_link or "").strip().lower(),
        ]
        identity = "hash:" + "|".join(pieces)

    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _first_apply_url(apply_options: list[Any]) -> str | None:
    """Pick the first valid apply option URL."""
    for option in apply_options:
        if not isinstance(option, dict):
            continue
        link = _as_text(option.get("link"))
        if link:
            return link
    return None


def _merge_query_names_json(
    existing_query_names_json: str | None,
    incoming_query_names_json: str | None,
) -> str:
    """Merge ordered query source lists without duplicates."""
    merged = _normalize_query_names(
        _load_query_names_json(existing_query_names_json)
        + _load_query_names_json(incoming_query_names_json)
    )
    return json.dumps(merged, sort_keys=False)


def _load_query_names_json(raw_query_names_json: str | None) -> list[str]:
    """Parse query_names_json into a normalized list."""
    if not raw_query_names_json:
        return []
    try:
        payload = json.loads(raw_query_names_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return _normalize_query_names(payload)


def _normalize_query_names(values: list[Any]) -> list[str]:
    """Trim, dedupe, and preserve first-seen query name order."""
    normalized: list[str] = []
    seen: set[str] = set()

    for value in values:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)

    return normalized


def _as_text(value: Any) -> str | None:
    """Normalize optional text values."""
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _as_int_bool(value: Any) -> int | None:
    """Map bool to SQLite-friendly 1/0 while preserving missing values."""
    if isinstance(value, bool):
        return 1 if value else 0
    return None


def recompute_jobs_scorability(connection: sqlite3.Connection) -> int:
    """Recompute is_scorable fields for all existing jobs rows."""
    rows = connection.execute(
        """
        SELECT id, title, company, description, apply_url
        FROM jobs
        ORDER BY id ASC
        """
    ).fetchall()

    updates: list[tuple[int, str, int]] = []
    for row in rows:
        row_id = int(row["id"] if isinstance(row, sqlite3.Row) else row[0])
        title = row["title"] if isinstance(row, sqlite3.Row) else row[1]
        company = row["company"] if isinstance(row, sqlite3.Row) else row[2]
        description = row["description"] if isinstance(row, sqlite3.Row) else row[3]
        apply_url = row["apply_url"] if isinstance(row, sqlite3.Row) else row[4]

        missing_fields = _compute_scorable_missing_fields(
            title=_as_text(title) or "",
            company=_as_text(company) or "",
            description=_as_text(description),
            apply_url=_as_text(apply_url),
        )
        is_scorable = 1 if not missing_fields else 0
        updates.append((is_scorable, json.dumps(missing_fields, sort_keys=True), row_id))

    connection.executemany(
        """
        UPDATE jobs
        SET is_scorable = ?, scorable_missing_fields_json = ?
        WHERE id = ?
        """,
        updates,
    )
    return len(updates)


def _compute_scorable_missing_fields(
    *,
    title: str,
    company: str,
    description: str | None,
    apply_url: str | None,
) -> list[str]:
    """Return deterministic missing-field codes for scoring eligibility."""
    missing_fields: list[str] = []
    if not title.strip():
        missing_fields.append("missing_title")
    if not company.strip():
        missing_fields.append("missing_company")
    if not description or not description.strip():
        missing_fields.append("missing_description")
    if not apply_url or not apply_url.strip():
        missing_fields.append("missing_apply_link")
    return missing_fields
