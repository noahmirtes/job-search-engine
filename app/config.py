from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Settings:
    project_root: Path
    config_dir: Path
    data_dir: Path
    db_path: Path
    serpapi_key: str | None


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parent.parent
    load_env_file(project_root / ".env")

    data_dir = project_root / "data"
    config_dir = project_root / "config"
    db_path_env = os.getenv("JOB_SEARCH_DB_PATH")
    db_path = Path(db_path_env) if db_path_env else data_dir / "jobs.db"
    if not db_path.is_absolute():
        db_path = project_root / db_path

    return Settings(
        project_root=project_root,
        config_dir=config_dir,
        data_dir=data_dir,
        db_path=db_path,
        serpapi_key=os.getenv("SERPAPI_API_KEY"),
    )


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_queries(settings: Settings) -> list[dict[str, Any]]:
    queries_path = settings.config_dir / "queries.json"
    if not queries_path.exists():
        raise FileNotFoundError(
            f"Missing queries config at {queries_path}. Create it from config/queries.json."
        )

    with queries_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, list):
        raise ValueError("config/queries.json must contain a list of query objects.")

    queries: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Each query entry must be a JSON object.")

        name = item.get("name")
        request = item.get("request")
        max_pages = item.get("max_pages", 1)
        enabled = item.get("enabled", True)
        if not isinstance(name, str) or not name:
            raise ValueError("Each query entry must have a non-empty 'name' string.")
        if not isinstance(request, dict) or not request:
            raise ValueError(f"Query '{name}' must have a non-empty 'request' object.")
        if not isinstance(max_pages, int) or max_pages < 1:
            raise ValueError(f"Query '{name}' must have max_pages >= 1.")
        if not isinstance(enabled, bool):
            raise ValueError(f"Query '{name}' must have a boolean enabled flag.")

        queries.append(item)

    if not queries:
        raise ValueError("config/queries.json must contain at least one query.")

    return queries
