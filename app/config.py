from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkerPaths:
    """Filesystem inputs supplied by the orchestrator at worker startup."""

    db_path: Path
    log_path: Path
    queries_path: Path
    ideal_job_path: Path
    resume_path: Path
    env_path: Path


@dataclass(frozen=True)
class QueryConfig:
    """Validated search query entry from queries.json."""
    name: str
    request: dict[str, Any]
    max_pages: int
    enabled: bool


@dataclass(frozen=True)
class WorkerConfig:
    """Runtime config object passed across the worker flow."""

    paths: WorkerPaths
    serpapi_api_key: str
    queries: list[QueryConfig]
    resume_text: str
    ideal_job_text: str


def initialize_config(paths: WorkerPaths) -> WorkerConfig:
    """Load + validate all worker config inputs and return one runtime object."""
    resolved_paths = _resolve_paths(paths)
    _validate_paths(resolved_paths)

    _load_env_file(resolved_paths.env_path)
    serpapi_api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not serpapi_api_key:
        raise ValueError(
            "SERPAPI_API_KEY is required. Set it in the supplied env file or process env."
        )

    queries = _load_queries(resolved_paths.queries_path)
    resume_text = _read_nonempty_text(resolved_paths.resume_path, "resume")
    ideal_job_text = _read_nonempty_text(resolved_paths.ideal_job_path, "ideal job")

    return WorkerConfig(
        paths=resolved_paths,
        serpapi_api_key=serpapi_api_key,
        queries=queries,
        resume_text=resume_text,
        ideal_job_text=ideal_job_text,
    )


def _resolve_paths(paths: WorkerPaths) -> WorkerPaths:
    return WorkerPaths(
        db_path=paths.db_path.expanduser().resolve(),
        log_path=paths.log_path.expanduser().resolve(),
        queries_path=paths.queries_path.expanduser().resolve(),
        ideal_job_path=paths.ideal_job_path.expanduser().resolve(),
        resume_path=paths.resume_path.expanduser().resolve(),
        env_path=paths.env_path.expanduser().resolve(),
    )


def _validate_paths(paths: WorkerPaths) -> None:
    required_files = [
        ("queries", paths.queries_path),
        ("ideal job", paths.ideal_job_path),
        ("resume", paths.resume_path),
        ("env", paths.env_path),
    ]

    for label, path in required_files:
        if not path.exists():
            raise FileNotFoundError(f"Missing {label} file: {path}")
        if not path.is_file():
            raise ValueError(f"{label} path must be a file: {path}")

    paths.db_path.parent.mkdir(parents=True, exist_ok=True)
    paths.log_path.parent.mkdir(parents=True, exist_ok=True)


def _load_env_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


def _read_nonempty_text(path: Path, label: str) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{label} text file is empty: {path}")
    return text


def _load_queries(path: Path) -> list[QueryConfig]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, list):
        raise ValueError("queries.json must contain a list of query objects.")
    if not payload:
        raise ValueError("queries.json must contain at least one query object.")

    seen_names: set[str] = set()
    queries: list[QueryConfig] = []

    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"Query at index {index} must be a JSON object.")

        name = item.get("name")
        request = item.get("request")
        max_pages = item.get("max_pages", 1)
        enabled = item.get("enabled", True)

        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Query at index {index} must have a non-empty 'name'.")
        if name in seen_names:
            raise ValueError(f"Duplicate query name found: '{name}'.")
        seen_names.add(name)

        if not isinstance(request, dict) or not request:
            raise ValueError(f"Query '{name}' must have a non-empty 'request' object.")
        if not isinstance(max_pages, int) or max_pages < 1:
            raise ValueError(f"Query '{name}' must have max_pages >= 1.")
        if not isinstance(enabled, bool):
            raise ValueError(f"Query '{name}' must have a boolean 'enabled' field.")

        queries.append(
            QueryConfig(
                name=name,
                request=request,
                max_pages=max_pages,
                enabled=enabled,
            )
        )

    return queries
