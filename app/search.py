"""Search execution flow: fetch pages, archive raw payloads, upsert jobs."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.config import QueryConfig, WorkerConfig
from app.db import get_connection, init_db, log_raw_request, utc_now_iso
from app.jobs import upsert_jobs_from_payload
from app.serpapi import SerpApiService
from app.worker_logging import get_logger
"""

LOGGER = get_logger("search")
Notes:
I'm looking at this script and it seems kinda weird to me how the call is happening with the connection integrated inside it
I think a better way to do this would be to run each request and if it succeeds, add it to a list, if it fails mark it
and then loop over all the request summaries or whatever and just add those to the database that way. That would simplify
the logic quite a bit and would make it a bit easier to follow what's going on and why. That also gets rid of that awkward
except logic that adds a fake row to the db if the request fails
"""

# Lightweight run summaries returned to scripts/callers.
@dataclass(frozen=True)
class QueryRunSummary:
    query_name: str
    pages_fetched: int
    stored_request_ids: list[int]
    jobs_upserted: int
    error_count: int
    last_error_message: str | None = None


@dataclass(frozen=True)
class SearchRunSummary:
    queries_run: int
    total_pages_fetched: int
    total_raw_requests_stored: int
    total_jobs_upserted: int
    total_error_count: int
    query_summaries: list[QueryRunSummary]


def run_enabled_queries(config: WorkerConfig) -> SearchRunSummary:
    """Run all enabled queries and persist both raw + normalized job data."""
    enabled_queries = [query for query in config.queries if query.enabled]
    if not enabled_queries:
        raise ValueError("No enabled queries were found in config/queries.json.")

    init_db(config.paths.db_path)
    service = SerpApiService(api_key=config.serpapi_api_key)
    LOGGER.info("Search run start: enabled_queries=%s", len(enabled_queries))

    query_summaries: list[QueryRunSummary] = []
    total_pages_fetched = 0
    total_raw_requests_stored = 0
    total_jobs_upserted = 0
    total_error_count = 0

    with get_connection(config.paths.db_path) as connection:
        for query in enabled_queries:
            summary = _run_single_query(service, connection, query)
            query_summaries.append(summary)
            total_pages_fetched += summary.pages_fetched
            total_raw_requests_stored += len(summary.stored_request_ids)
            total_jobs_upserted += summary.jobs_upserted
            total_error_count += summary.error_count

    summary = SearchRunSummary(
        queries_run=len(query_summaries),
        total_pages_fetched=total_pages_fetched,
        total_raw_requests_stored=total_raw_requests_stored,
        total_jobs_upserted=total_jobs_upserted,
        total_error_count=total_error_count,
        query_summaries=query_summaries,
    )
    LOGGER.info(
        "Search run complete: queries_run=%s pages_fetched=%s raw_requests=%s jobs_upserted=%s errors=%s",
        summary.queries_run,
        summary.total_pages_fetched,
        summary.total_raw_requests_stored,
        summary.total_jobs_upserted,
        summary.total_error_count,
    )
    return summary


def _run_single_query(
    service: SerpApiService,
    connection: sqlite3.Connection,
    query: QueryConfig,
) -> QueryRunSummary:
    """Execute one query attempt-by-attempt and persist each attempt immediately."""
    LOGGER.info("Query start: query=%s max_pages=%s", query.name, query.max_pages)
    stored_request_ids: list[int] = []
    jobs_upserted = 0
    pages_fetched = 0
    error_count = 0
    last_error_message: str | None = None

    attempts = service.search(
        query.request,
        max_pages=query.max_pages,
        query_name=query.name,
    )
    try:
        for attempt in attempts:
            page_jobs_upserted = 0
            requested_at = utc_now_iso()
            request_id = log_raw_request(
                connection,
                query_name=attempt.query_name,
                query_params=attempt.request,
                response_payload=attempt.payload,
                response_status=attempt.response_status,
                requested_at=requested_at,
            )
            # Durability guardrail: commit each attempt so later failures do not lose prior rows.
            connection.commit()

            stored_request_ids.append(request_id)
            pages_fetched += 1

            if attempt.is_error:
                error_count += 1
                last_error_message = attempt.error_message
                LOGGER.warning(
                    "Query page result: query=%s page=%s status=%s request_id=%s jobs_upserted=%s error=%s",
                    attempt.query_name,
                    attempt.page_number,
                    attempt.response_status,
                    request_id,
                    page_jobs_upserted,
                    attempt.error_message or "",
                )
                break

            page_jobs_upserted = upsert_jobs_from_payload(
                connection,
                attempt.payload,
                anchor_requested_at_utc=requested_at,
                query_name=attempt.query_name,
            )
            jobs_upserted += page_jobs_upserted
            LOGGER.info(
                "Query page result: query=%s page=%s status=%s request_id=%s jobs_upserted=%s",
                attempt.query_name,
                attempt.page_number,
                attempt.response_status,
                request_id,
                page_jobs_upserted,
            )
    except Exception as exc:
        # Last-resort durability: persist unexpected iterator failures as synthetic raw rows.
        last_error_message = f"Search iteration failed: {exc}"
        requested_at = utc_now_iso()
        request_id = log_raw_request(
            connection,
            query_name=query.name,
            query_params=query.request,
            response_payload={
                "error": last_error_message,
                "synthetic_error": True,
                "error_stage": "search_iteration",
            },
            response_status=500,
            requested_at=requested_at,
        )
        connection.commit()
        stored_request_ids.append(request_id)
        pages_fetched += 1
        error_count += 1
        LOGGER.error(
            "Query iteration failed: query=%s status=%s request_id=%s error=%s",
            query.name,
            500,
            request_id,
            last_error_message,
        )


    summary = QueryRunSummary(
        query_name=query.name,
        pages_fetched=pages_fetched,
        stored_request_ids=stored_request_ids,
        jobs_upserted=jobs_upserted,
        error_count=error_count,
        last_error_message=last_error_message,
    )
    LOGGER.info(
        "Query complete: query=%s pages_fetched=%s stored_requests=%s jobs_upserted=%s errors=%s",
        summary.query_name,
        summary.pages_fetched,
        len(summary.stored_request_ids),
        summary.jobs_upserted,
        summary.error_count,
    )
    return summary
