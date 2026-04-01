"""Thin SerpApi client wrapper with predictable paging behavior."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

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


@dataclass(frozen=True)
class SearchAttempt:
    """One API attempt, including explicit error metadata on failures."""

    query_name: str
    page_number: int
    request: dict[str, Any]
    payload: dict[str, Any]
    response_status: int
    is_error: bool
    error_message: str | None = None


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
    ) -> Iterator[SearchAttempt]:
        """Yield one attempt at a time so callers can persist each result immediately."""
        base_request = dict(request)
        base_request.setdefault("engine", "google_jobs")

        next_page_token: str | None = None

        for page_number in range(1, max_pages + 1):
            page_request = dict(base_request)
            if next_page_token:
                page_request["next_page_token"] = next_page_token

            attempt = self._search_once(
                query_name=query_name,
                page_number=page_number,
                request=page_request,
            )
            yield attempt

            if attempt.is_error:
                break

            next_page_token = extract_next_page_token(attempt.payload)
            if not next_page_token:
                break

    def _search_once(
        self,
        *,
        query_name: str,
        page_number: int,
        request: dict[str, Any],
    ) -> SearchAttempt:
        """Execute one API call and always return a normalized success/error attempt."""
        try:
            results = self.client.search(request)
        except Exception as exc:
            return _build_error_attempt(
                query_name=query_name,
                page_number=page_number,
                request=request,
                response_status=502,
                error_message=f"SerpApi request failed: {exc}",
                error_stage="request",
            )

        if not isinstance(results, serpapi.SerpResults):
            return _build_error_attempt(
                query_name=query_name,
                page_number=page_number,
                request=request,
                response_status=502,
                error_message="SerpApi returned a non-JSON response.",
                error_stage="response_type",
            )

        try:
            payload = results.as_dict()
        except Exception as exc:
            return _build_error_attempt(
                query_name=query_name,
                page_number=page_number,
                request=request,
                response_status=502,
                error_message=f"SerpApi payload parsing failed: {exc}",
                error_stage="payload_parse",
            )

        if not isinstance(payload, dict):
            return _build_error_attempt(
                query_name=query_name,
                page_number=page_number,
                request=request,
                response_status=502,
                error_message="SerpApi returned payload in unexpected shape.",
                error_stage="payload_shape",
            )

        if payload.get("error"):
            error_message = str(payload.get("error"))
            return SearchAttempt(
                query_name=query_name,
                page_number=page_number,
                request=request,
                payload=payload,
                response_status=422,
                is_error=True,
                error_message=error_message,
            )

        return SearchAttempt(
            query_name=query_name,
            page_number=page_number,
            request=request,
            payload=payload,
            response_status=200,
            is_error=False,
            error_message=None,
        )


def extract_next_page_token(payload: dict[str, Any]) -> str | None:
    """Extract pagination token from a SerpApi response payload."""
    pagination = payload.get("serpapi_pagination")
    if not isinstance(pagination, dict):
        return None

    next_page_token = pagination.get("next_page_token")
    if isinstance(next_page_token, str) and next_page_token:
        return next_page_token

    return None


def _build_error_attempt(
    *,
    query_name: str,
    page_number: int,
    request: dict[str, Any],
    response_status: int,
    error_message: str,
    error_stage: str,
) -> SearchAttempt:
    """Build a normalized error attempt with synthetic payload metadata."""
    return SearchAttempt(
        query_name=query_name,
        page_number=page_number,
        request=request,
        payload=_synthetic_error_payload(error_message, error_stage=error_stage),
        response_status=response_status,
        is_error=True,
        error_message=error_message,
    )


def _synthetic_error_payload(error_message: str, *, error_stage: str) -> dict[str, Any]:
    """Create a stable payload shape for failures with no upstream JSON payload."""
    return {
        "error": error_message,
        "synthetic_error": True,
        "error_stage": error_stage,
    }
