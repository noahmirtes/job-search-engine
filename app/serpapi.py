"""Thin SerpApi client wrapper with predictable paging behavior."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import serpapi


class SerpApiError(RuntimeError):
    """Raised for request/response issues from SerpApi."""
    pass


@dataclass(frozen=True)
class SearchPage:
    """One fetched page plus request metadata used by downstream storage."""
    query_name: str
    page_number: int
    request: dict[str, Any]
    payload: dict[str, Any]
    response_status: int = 200


class SerpApiService:
    """Service wrapper that handles Google Jobs paging tokens."""
    def __init__(self, api_key: str, *, timeout: int = 30) -> None:
        self.client = serpapi.Client(api_key=api_key, timeout=timeout)

    def search(
        self,
        request: dict[str, Any],
        *,
        max_pages: int = 1,
        query_name: str = "query",
    ) -> list[SearchPage]:
        """Fetch up to max_pages pages for a query request."""
        base_request = dict(request)
        base_request.setdefault("engine", "google_jobs")

        pages: list[SearchPage] = []
        next_page_token: str | None = None

        for page_number in range(1, max_pages + 1):
            page_request = dict(base_request)
            if next_page_token:
                page_request["next_page_token"] = next_page_token

            payload = self._search_once(page_request)
            pages.append(
                SearchPage(
                    query_name=query_name,
                    page_number=page_number,
                    request=page_request,
                    payload=payload,
                )
            )

            next_page_token = extract_next_page_token(payload)
            if not next_page_token:
                break

        return pages

    def _search_once(self, request: dict[str, Any]) -> dict[str, Any]:
        """Execute one API call and validate payload shape."""
        try:
            results = self.client.search(request)
        except Exception as exc:
            raise SerpApiError(f"SerpApi request failed: {exc}") from exc

        if not isinstance(results, serpapi.SerpResults):
            raise SerpApiError("SerpApi returned a non-JSON response.")

        payload = results.as_dict()
        if payload.get("error"):
            raise SerpApiError(str(payload["error"]))

        return payload


def extract_next_page_token(payload: dict[str, Any]) -> str | None:
    """Extract pagination token from a SerpApi response payload."""
    pagination = payload.get("serpapi_pagination")
    if not isinstance(pagination, dict):
        return None

    next_page_token = pagination.get("next_page_token")
    if isinstance(next_page_token, str) and next_page_token:
        return next_page_token

    return None
