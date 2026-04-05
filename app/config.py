"""Worker bootstrap: path resolution, config loading, and validation."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# Public config contracts used by scripts/orchestrator code.
@dataclass(frozen=True)
class WorkerPaths:
    """Filesystem inputs supplied by the orchestrator at worker startup."""

    db_path: Path
    log_path: Path
    queries_path: Path
    scoring_path: Path
    ideal_job_path: Path
    resume_path: Path
    env_path: Path
    report_export_dir: Path


@dataclass(frozen=True)
class QueryConfig:
    """Validated search query entry from queries.json."""
    name: str
    request: dict[str, Any]
    max_pages: int
    enabled: bool


@dataclass(frozen=True)
class ScoringRuleConfig:
    """Validated and normalized scoring rule."""

    key: str
    name: str
    prompt: str
    score: float
    result_options: list[str]
    trigger_result: str
    trigger_result_normalized: str
    terminate_options: list


@dataclass(frozen=True)
class ScoringConfig:
    """Validated scoring settings loaded from scoring.json."""

    version: str
    llm_provider: str
    llm_model: str
    llm_max_retries: int
    report: "ScoringReportConfig"
    rules: list[ScoringRuleConfig]


@dataclass(frozen=True)
class ScoringReportConfig:
    """Validated report settings loaded from scoring.json."""

    threshold: float
    include_all_jobs_list: bool


@dataclass(frozen=True)
class WorkerConfig:
    """Runtime config object passed across the worker flow."""

    paths: WorkerPaths
    serpapi_api_key: str
    queries: list[QueryConfig]
    scoring_config: ScoringConfig
    resume_text: str
    ideal_job_text: str


# Bootstrap entrypoint used by all worker scripts.
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
    scoring_config = _load_scoring_config(resolved_paths.scoring_path)
    resume_text = _read_nonempty_text(resolved_paths.resume_path, "resume")
    ideal_job_text = _read_nonempty_text(resolved_paths.ideal_job_path, "ideal job")

    return WorkerConfig(
        paths=resolved_paths,
        serpapi_api_key=serpapi_api_key,
        queries=queries,
        scoring_config=scoring_config,
        resume_text=resume_text,
        ideal_job_text=ideal_job_text,
    )


# Internal helpers for path/env/file parsing.
def _resolve_paths(paths: WorkerPaths) -> WorkerPaths:
    """Normalize configured paths to absolute paths."""
    return WorkerPaths(
        db_path=paths.db_path.expanduser().resolve(),
        log_path=paths.log_path.expanduser().resolve(),
        queries_path=paths.queries_path.expanduser().resolve(),
        scoring_path=paths.scoring_path.expanduser().resolve(),
        ideal_job_path=paths.ideal_job_path.expanduser().resolve(),
        resume_path=paths.resume_path.expanduser().resolve(),
        env_path=paths.env_path.expanduser().resolve(),
        report_export_dir=paths.report_export_dir.expanduser().resolve(),
    )


def _validate_paths(paths: WorkerPaths) -> None:
    """Validate required input files and ensure output directories exist."""
    required_files = [
        ("queries", paths.queries_path),
        ("scoring", paths.scoring_path),
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
    paths.report_export_dir.mkdir(parents=True, exist_ok=True)


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines into process env without overriding existing vars."""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


def _read_nonempty_text(path: Path, label: str) -> str:
    """Read a text file and enforce non-empty content."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{label} text file is empty: {path}")
    return text


def _load_queries(path: Path) -> list[QueryConfig]:
    """Parse and validate query configuration entries."""
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


def _load_scoring_config(path: Path) -> ScoringConfig:
    """Parse, validate, and normalize scoring configuration JSON."""
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError("scoring.json must contain a JSON object.")

    version = str(payload.get("version", "v1")).strip()
    if not version:
        raise ValueError("scoring.json version must be a non-empty string.")

    llm = payload.get("llm", {})
    if not isinstance(llm, dict):
        raise ValueError("scoring.json 'llm' must be an object.")

    provider = str(llm.get("provider", "ollama")).strip().lower()
    if provider != "ollama":
        raise ValueError(f"Unsupported llm.provider '{provider}'. Only 'ollama' is supported.")

    model = llm.get("model", "")
    if not isinstance(model, str):
        raise ValueError("scoring.json llm.model must be a string.")
    model = model.strip()

    max_retries = llm.get("max_retries", 3)
    if not isinstance(max_retries, int) or max_retries < 1:
        raise ValueError("scoring.json llm.max_retries must be an integer >= 1.")

    report = payload.get("report")
    if not isinstance(report, dict):
        raise ValueError("scoring.json report must be an object.")
    if "include_all_jobs_tab" in report:
        raise ValueError(
            "scoring.json report.include_all_jobs_tab is not supported. "
            "Use report.include_all_jobs_list."
        )

    if "threshold" not in report:
        raise ValueError("scoring.json report.threshold is required.")
    threshold = report["threshold"]
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("scoring.json report.threshold must be numeric.")
    threshold = float(threshold)
    if not math.isfinite(threshold):
        raise ValueError("scoring.json report.threshold must be a finite number.")

    if "include_all_jobs_list" not in report:
        raise ValueError("scoring.json report.include_all_jobs_list is required.")
    include_all_jobs_list = report["include_all_jobs_list"]
    if not isinstance(include_all_jobs_list, bool):
        raise ValueError("scoring.json report.include_all_jobs_list must be a boolean.")

    rules = payload.get("rules", [])
    if not isinstance(rules, list) or not rules:
        raise ValueError("scoring.json rules must contain at least one rule.")

    parsed_rules: list[ScoringRuleConfig] = []
    used_keys: set[str] = set()

    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"scoring.json rule at index {index} must be an object.")

        default_name = f"rule_{index + 1}"
        raw_name = rule.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else default_name
        key = _build_unique_rule_key(name, used_keys)

        prompt = rule.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"scoring.json rule '{name}' must have a non-empty prompt.")
        prompt = prompt.strip()

        score = rule.get("score")
        if not isinstance(score, (int, float)):
            raise ValueError(f"scoring.json rule '{name}' must have a numeric score.")

        result_options = rule.get("result_options")
        if not isinstance(result_options, list) or not result_options:
            raise ValueError(
                f"scoring.json rule '{name}' must define non-empty result_options."
            )
        if any(not isinstance(item, str) for item in result_options):
            raise ValueError(
                f"scoring.json rule '{name}' result_options must contain only strings."
            )
        normalized_options = [item.strip() for item in result_options if item.strip()]
        if not normalized_options:
            raise ValueError(
                f"scoring.json rule '{name}' must define non-empty string result_options."
            )

        trigger_result = rule.get("trigger_result")
        if not isinstance(trigger_result, str) or not trigger_result.strip():
            raise ValueError(
                f"scoring.json rule '{name}' must define a non-empty trigger_result."
            )
        trigger_result = trigger_result.strip()
        trigger_result_normalized = trigger_result.lower()

        if trigger_result_normalized not in {item.lower() for item in normalized_options}:
            raise ValueError(
                f"scoring.json rule '{name}' trigger_result must exist in result_options."
            )

        terminate_options = rule.get("terminate_options")
        if terminate_options and not isinstance(rule.get("terminate_options"), list):
            raise ValueError(
                f"scoring.json role {name} terminate_options must be a list"
            )

        parsed_rules.append(
            ScoringRuleConfig(
                key=key,
                name=name,
                prompt=prompt,
                score=float(score),
                result_options=normalized_options,
                trigger_result=trigger_result,
                trigger_result_normalized=trigger_result_normalized,
                terminate_options=terminate_options
            )
        )

    return ScoringConfig(
        version=version,
        llm_provider=provider,
        llm_model=model,
        llm_max_retries=max_retries,
        report=ScoringReportConfig(
            threshold=threshold,
            include_all_jobs_list=include_all_jobs_list,
        ),
        rules=parsed_rules,
    )


def _build_unique_rule_key(name: str, used_keys: set[str]) -> str:
    """Create a stable unique key for rule result/breakdown maps."""
    key = name
    suffix = 2
    while key in used_keys:
        key = f"{name}_{suffix}"
        suffix += 1
    used_keys.add(key)
    return key
