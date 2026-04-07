"""Search execution flow: archive raw attempts first, then derive jobs."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.config import QueryConfig, WorkerConfig
from app.db import get_connection, init_db, log_raw_request, utc_now_iso
from app.jobs import upsert_jobs_from_payload
from app.serpapi import SearchAttempt, SerpApiService
from app.worker_logging import get_logger

# ---------------------------------------------------- LOGGER ----
LOGGER = get_logger("search")


# ---------------------------------------------------- DATACLASSES ----
@dataclass(frozen=True)
class QueryRunSummary:
    attempts_received: int
    query_name: str
    raw_attempts_archived: int
    pages_fetched: int
    stored_request_ids: list[int]
    jobs_upserted: int
    error_count: int
    last_error_message: str | None = None


@dataclass(frozen=True)
class SearchRunSummary:
    queries_run: int
    total_attempts_received: int
    total_pages_fetched: int
    total_raw_requests_stored: int
    total_jobs_upserted: int
    total_error_count: int
    query_summaries: list[QueryRunSummary]


@dataclass(frozen=True)
class ArchivedAttempt:
    request_id: int
    requested_at: str


# ---------------------------------------------------- EXCEPTIONS ----
class RawAttemptArchiveError(RuntimeError):
    """Raised when a returned API attempt could not be durably archived."""

    def __init__(self, message: str, *, backup_path: Path | None = None) -> None:
        super().__init__(message)
        self.backup_path = backup_path


# ---------------------------------------------------- ENTRYPOINTS ----
def run_enabled_queries(config: WorkerConfig) -> SearchRunSummary:
    """Run all enabled queries and persist raw attempts before derived jobs."""
    enabled_queries = [query for query in config.queries if query.enabled]
    if not enabled_queries:
        raise ValueError("No enabled queries were found in config/queries.json.")

    init_db(config.paths.db_path)
    service = SerpApiService(api_key=config.serpapi_api_key)
    raw_backup_dir = _derive_raw_backup_dir(config)
    LOGGER.info("Search run start: enabled_queries=%s", len(enabled_queries))

    query_summaries: list[QueryRunSummary] = []
    total_attempts_received = 0
    total_pages_fetched = 0
    total_raw_requests_stored = 0
    total_jobs_upserted = 0
    total_error_count = 0

    with get_connection(config.paths.db_path) as connection:
        for query in enabled_queries:
            summary = _run_single_query(
                service,
                connection,
                query,
                raw_backup_dir=raw_backup_dir,
            )
            query_summaries.append(summary)
            total_attempts_received += summary.attempts_received
            total_pages_fetched += summary.pages_fetched
            total_raw_requests_stored += summary.raw_attempts_archived
            total_jobs_upserted += summary.jobs_upserted
            total_error_count += summary.error_count

    summary = SearchRunSummary(
        queries_run=len(query_summaries),
        total_attempts_received=total_attempts_received,
        total_pages_fetched=total_pages_fetched,
        total_raw_requests_stored=total_raw_requests_stored,
        total_jobs_upserted=total_jobs_upserted,
        total_error_count=total_error_count,
        query_summaries=query_summaries,
    )
    LOGGER.info(
        "Search run complete: queries_run=%s attempts_received=%s successful_pages=%s raw_requests=%s jobs_upserted=%s errors=%s",
        summary.queries_run,
        summary.total_attempts_received,
        summary.total_pages_fetched,
        summary.total_raw_requests_stored,
        summary.total_jobs_upserted,
        summary.total_error_count,
    )
    return summary


# ---------------------------------------------------- HELPERS ----
def _run_single_query(
    service: SerpApiService,
    connection: sqlite3.Connection,
    query: QueryConfig,
    *,
    raw_backup_dir: Path,
) -> QueryRunSummary:
    """Execute one query attempt-by-attempt with archive-first durability."""
    LOGGER.info("Query start: query=%s max_pages=%s", query.name, query.max_pages)
    attempts_received = 0
    raw_attempts_archived = 0
    stored_request_ids: list[int] = []
    jobs_upserted = 0
    successful_pages = 0
    error_count = 0
    last_error_message: str | None = None

    attempts = service.search(
        query.request,
        max_pages=query.max_pages,
        query_name=query.name,
    )
    try:
        for attempt in attempts:
            attempts_received += 1
            archived_attempt = _archive_attempt(
                connection,
                attempt,
                raw_backup_dir=raw_backup_dir,
            )
            raw_attempts_archived += 1
            stored_request_ids.append(archived_attempt.request_id)

            if attempt.is_error:
                error_count += 1
                last_error_message = attempt.error_message
                LOGGER.warning(
                    "Error attempt archived: query=%s page=%s status=%s request_id=%s error=%s",
                    attempt.query_name,
                    attempt.page_number,
                    attempt.response_status,
                    archived_attempt.request_id,
                    attempt.error_message or "",
                )
                break

            successful_pages += 1
            try:
                page_jobs_upserted = _upsert_jobs_from_attempt(
                    connection,
                    attempt,
                    requested_at=archived_attempt.requested_at,
                )
            except Exception as exc:
                # Raw attempt is already committed; rollback only derived writes for this page.
                connection.rollback()
                error_count += 1
                last_error_message = f"Job normalization failed: {exc}"
                LOGGER.error(
                    "Post-archive normalization failed: query=%s page=%s request_id=%s error=%s",
                    attempt.query_name,
                    attempt.page_number,
                    archived_attempt.request_id,
                    last_error_message,
                )
                continue

            jobs_upserted += page_jobs_upserted
            LOGGER.info(
                "Jobs upserted from archived attempt: query=%s page=%s request_id=%s jobs_upserted=%s",
                attempt.query_name,
                attempt.page_number,
                archived_attempt.request_id,
                page_jobs_upserted,
            )
    except RawAttemptArchiveError:
        raise
    except Exception as exc:
        # Last-resort durability: persist unexpected iterator failures as synthetic raw rows.
        last_error_message = f"Search iteration failed: {exc}"
        request_id = _archive_iteration_failure(
            connection,
            query=query,
            error_message=last_error_message,
        )
        raw_attempts_archived += 1
        stored_request_ids.append(request_id)
        error_count += 1
        LOGGER.error(
            "Query iteration failed before attempt archival completed: query=%s request_id=%s error=%s",
            query.name,
            request_id,
            last_error_message,
        )

    summary = QueryRunSummary(
        attempts_received=attempts_received,
        query_name=query.name,
        raw_attempts_archived=raw_attempts_archived,
        pages_fetched=successful_pages,
        stored_request_ids=stored_request_ids,
        jobs_upserted=jobs_upserted,
        error_count=error_count,
        last_error_message=last_error_message,
    )
    LOGGER.info(
        "Query complete: query=%s attempts_received=%s raw_requests=%s successful_pages=%s jobs_upserted=%s errors=%s",
        summary.query_name,
        summary.attempts_received,
        summary.raw_attempts_archived,
        summary.pages_fetched,
        summary.jobs_upserted,
        summary.error_count,
    )
    return summary


def _archive_attempt(
    connection: sqlite3.Connection,
    attempt: SearchAttempt,
    *,
    raw_backup_dir: Path,
) -> ArchivedAttempt:
    """Persist one returned API attempt immediately and commit it durably."""
    requested_at = utc_now_iso()
    try:
        request_id = log_raw_request(
            connection,
            query_name=attempt.query_name,
            query_params=attempt.request,
            response_payload=attempt.payload,
            response_status=attempt.response_status,
            requested_at=requested_at,
        )
        connection.commit()
    except Exception as exc:
        connection.rollback()
        backup_path = None
        backup_error: Exception | None = None
        try:
            backup_path = _write_raw_attempt_backup(
                raw_backup_dir,
                attempt=attempt,
                failure_message=str(exc),
                failure_stage="raw_request_archive",
            )
        except Exception as backup_exc:  # pragma: no cover - defensive logging path
            backup_error = backup_exc

        if backup_error is None:
            LOGGER.error(
                "Raw attempt archive failed: query=%s page=%s status=%s backup_path=%s error=%s",
                attempt.query_name,
                attempt.page_number,
                attempt.response_status,
                backup_path,
                exc,
            )
        else:
            LOGGER.error(
                "Raw attempt archive failed and backup write failed: query=%s page=%s status=%s backup_dir=%s archive_error=%s backup_error=%s",
                attempt.query_name,
                attempt.page_number,
                attempt.response_status,
                raw_backup_dir,
                exc,
                backup_error,
            )

        raise RawAttemptArchiveError(
            f"Failed to archive raw attempt for query '{attempt.query_name}' page {attempt.page_number}.",
            backup_path=backup_path,
        ) from exc

    LOGGER.info(
        "Raw attempt archived: query=%s page=%s status=%s request_id=%s",
        attempt.query_name,
        attempt.page_number,
        attempt.response_status,
        request_id,
    )
    return ArchivedAttempt(request_id=request_id, requested_at=requested_at)


def _upsert_jobs_from_attempt(
    connection: sqlite3.Connection,
    attempt: SearchAttempt,
    *,
    requested_at: str,
) -> int:
    """Derive normalized jobs from one already archived successful attempt."""
    return upsert_jobs_from_payload(
        connection,
        attempt.payload,
        anchor_requested_at_utc=requested_at,
        query_name=attempt.query_name,
    )


def _archive_iteration_failure(
    connection: sqlite3.Connection,
    *,
    query: QueryConfig,
    error_message: str,
) -> int:
    """Persist a synthetic raw row for iterator/runtime failures before an attempt exists."""
    requested_at = utc_now_iso()
    request_id = log_raw_request(
        connection,
        query_name=query.name,
        query_params=query.request,
        response_payload={
            "error": error_message,
            "synthetic_error": True,
            "error_stage": "search_iteration",
        },
        response_status=500,
        requested_at=requested_at,
    )
    connection.commit()
    return request_id


def _derive_raw_backup_dir(config: WorkerConfig) -> Path:
    """Derive the fallback raw backup directory from the resolved config paths."""
    return config.paths.log_path.parent / "raw_response_backup"


def _write_raw_attempt_backup(
    raw_backup_dir: Path,
    *,
    attempt: SearchAttempt,
    failure_message: str,
    failure_stage: str,
) -> Path:
    """Write a JSON backup when a returned raw attempt cannot be archived to SQLite."""
    raw_backup_dir.mkdir(parents=True, exist_ok=True)
    failed_at = utc_now_iso()
    timestamp = failed_at.replace(":", "-")
    query_slug = _slugify_query_name(attempt.query_name)
    suffix = uuid4().hex[:8]
    file_path = raw_backup_dir / f"{timestamp}_{query_slug}_page_{attempt.page_number}_{suffix}.json"
    payload = {
        "query_name": attempt.query_name,
        "page_number": attempt.page_number,
        "request": attempt.request,
        "response_status": attempt.response_status,
        "payload": attempt.payload,
        "failed_at": failed_at,
        "failure_stage": failure_stage,
        "failure_message": failure_message,
    }
    file_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return file_path


def _slugify_query_name(query_name: str) -> str:
    """Convert query names into safe, readable backup filename fragments."""
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", query_name.strip())
    sanitized = sanitized.strip("._")
    return sanitized or "query"
