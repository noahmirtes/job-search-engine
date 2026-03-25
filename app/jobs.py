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
    normalized_hash: str


def upsert_jobs_from_payload(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    anchor_requested_at_utc: str,
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
        )
        _upsert_job(connection, record)
        processed_count += 1

    return processed_count


def upsert_jobs_from_raw_response_json(
    connection: sqlite3.Connection,
    response_json: str,
    *,
    anchor_requested_at_utc: str,
) -> int:
    """Decode raw response JSON and upsert contained jobs."""
    payload = json.loads(response_json)
    if not isinstance(payload, dict):
        return 0
    return upsert_jobs_from_payload(
        connection,
        payload,
        anchor_requested_at_utc=anchor_requested_at_utc,
    )


def _to_job_record(
    raw_job: dict[str, Any],
    *,
    anchor_requested_at_utc: str,
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
        normalized_hash=normalized_hash,
    )


def _upsert_job(connection: sqlite3.Connection, record: JobRecord) -> None:
    """Insert or update a job record using source id/hash identity."""
    existing_job_id = _find_existing_job_id(
        connection=connection,
        source_job_id=record.source_job_id,
        normalized_hash=record.normalized_hash,
    )

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
                normalized_hash,
                first_seen_at,
                last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                record.normalized_hash,
                now,
                now,
            ),
        )
        return

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
            record.normalized_hash,
            now,
            existing_job_id,
        ),
    )


def _find_existing_job_id(
    connection: sqlite3.Connection,
    *,
    source_job_id: str | None,
    normalized_hash: str,
) -> int | None:
    """Find existing job by source id first, then fallback normalized hash."""
    if source_job_id:
        row = connection.execute(
            "SELECT id FROM jobs WHERE source_job_id = ? LIMIT 1",
            (source_job_id,),
        ).fetchone()
        if row is not None:
            return int(row["id"] if isinstance(row, sqlite3.Row) else row[0])

    row = connection.execute(
        "SELECT id FROM jobs WHERE normalized_hash = ? LIMIT 1",
        (normalized_hash,),
    ).fetchone()
    if row is None:
        return None
    return int(row["id"] if isinstance(row, sqlite3.Row) else row[0])


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
