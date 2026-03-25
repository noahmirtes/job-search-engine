from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.config import QueryConfig, WorkerConfig
from app.db import get_connection, init_db, log_raw_request
from app.jobs import upsert_jobs_from_payload
from app.serpapi import SerpApiService


@dataclass(frozen=True)
class QueryRunSummary:
    query_name: str
    pages_fetched: int
    stored_request_ids: list[int]
    jobs_upserted: int


@dataclass(frozen=True)
class SearchRunSummary:
    queries_run: int
    total_pages_fetched: int
    total_raw_requests_stored: int
    total_jobs_upserted: int
    query_summaries: list[QueryRunSummary]


def run_enabled_queries(config: WorkerConfig) -> SearchRunSummary:
    enabled_queries = [query for query in config.queries if query.enabled]
    if not enabled_queries:
        raise ValueError("No enabled queries were found in config/queries.json.")

    init_db(config.paths.db_path)
    service = SerpApiService(api_key=config.serpapi_api_key)

    query_summaries: list[QueryRunSummary] = []
    total_pages_fetched = 0
    total_raw_requests_stored = 0
    total_jobs_upserted = 0

    with get_connection(config.paths.db_path) as connection:
        for query in enabled_queries:
            summary = _run_single_query(service, connection, query)
            query_summaries.append(summary)
            total_pages_fetched += summary.pages_fetched
            total_raw_requests_stored += len(summary.stored_request_ids)
            total_jobs_upserted += summary.jobs_upserted

    return SearchRunSummary(
        queries_run=len(query_summaries),
        total_pages_fetched=total_pages_fetched,
        total_raw_requests_stored=total_raw_requests_stored,
        total_jobs_upserted=total_jobs_upserted,
        query_summaries=query_summaries,
    )


def _run_single_query(
    service: SerpApiService,
    connection: sqlite3.Connection,
    query: QueryConfig,
) -> QueryRunSummary:
    pages = service.search(
        query.request,
        max_pages=query.max_pages,
        query_name=query.name,
    )

    stored_request_ids: list[int] = []
    jobs_upserted = 0
    for page in pages:
        request_id = log_raw_request(
            connection,
            query_name=page.query_name,
            query_params=page.request,
            response_payload=page.payload,
            response_status=page.response_status,
        )
        stored_request_ids.append(request_id)
        jobs_upserted += upsert_jobs_from_payload(connection, page.payload)

    return QueryRunSummary(
        query_name=query.name,
        pages_fetched=len(pages),
        stored_request_ids=stored_request_ids,
        jobs_upserted=jobs_upserted,
    )
