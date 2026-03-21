from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_queries, load_settings
from app.db import get_connection, init_db, log_raw_request
from app.serpapi import SerpApiService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a configured SerpApi Google Jobs query and archive the raw response."
    )
    parser.add_argument(
        "--query",
        help="Query name from config/queries.json. Defaults to the first configured query.",
    )
    return parser.parse_args()


def pick_query(
    queries: list[dict[str, object]],
    query_name: str | None,
) -> dict[str, object]:
    enabled_queries = [query for query in queries if query.get("enabled", True)]
    if not enabled_queries:
        raise ValueError("No enabled queries were found in config/queries.json.")

    if query_name is None:
        return enabled_queries[0]

    for query in queries:
        if query.get("name") == query_name:
            return query

    raise ValueError(f"Query '{query_name}' was not found in config/queries.json.")


def main() -> None:
    args = parse_args()
    settings = load_settings()
    queries = load_queries(settings)
    selected_query = pick_query(queries, args.query)

    if not settings.serpapi_key:
        raise RuntimeError(
            "SERPAPI_API_KEY is not set. Add it to .env before running the search script."
        )

    init_db(settings.db_path)
    service = SerpApiService(api_key=settings.serpapi_key)
    pages = service.search(
        selected_query["request"],
        max_pages=int(selected_query.get("max_pages", 1)),
        query_name=str(selected_query["name"]),
    )

    stored_request_ids: list[int] = []
    with get_connection(settings.db_path) as connection:
        for page in pages:
            request_id = log_raw_request(
                connection,
                query_name=page.query_name,
                query_params=page.request,
                response_payload=page.payload,
                response_status=page.response_status,
            )
            stored_request_ids.append(request_id)

    print(f"Query: {selected_query['name']}")
    print(f"Pages fetched: {len(pages)}")
    if stored_request_ids:
        print(f"Stored raw request ids: {stored_request_ids}")

    if not pages:
        return

    first_page = pages[0]
    jobs_results = first_page.payload.get("jobs_results", [])
    job_count = len(jobs_results) if isinstance(jobs_results, list) else 0

    print(f"First page HTTP status: {first_page.response_status}")
    print(f"First page jobs_results count: {job_count}")
    if job_count:
        print("First job preview:")
        print(json.dumps(jobs_results[0], indent=2)[:2000])


if __name__ == "__main__":
    main()
