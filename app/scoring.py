"""Deterministic job scoring flow driven by scoring.json + Ollama extraction."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.config import WorkerConfig
from app.db import utc_now_iso
from app.ollama import classify_rule_result
from time import monotonic # temp import to see how long scoring takes

@dataclass(frozen=True)
class ScoringRunSummary:
    """Aggregate counters returned after scoring finishes."""

    scoring_version: str
    llm_provider: str
    llm_model: str
    jobs_selected: int
    jobs_scored_ok: int
    jobs_failed: int


def run_job_scoring(
    connection: sqlite3.Connection,
    config: WorkerConfig,
    *,
    only_unscored: bool = False,
) -> ScoringRunSummary:
    """Score jobs with configured rules and upsert results into job_scores."""
    settings = config.scoring_config
    if not settings.llm_model:
        raise ValueError("scoring.json llm.model must be set before running scoring.")

    rows = _load_jobs_for_scoring(
        connection,
        scoring_version=settings.version,
        only_unscored=only_unscored,
    )

    jobs_scored_ok = 0
    jobs_failed = 0

    for row in rows:
        job_id = int(row["id"])
        job_text = _build_job_text(row)

        feature_results: dict[str, str] = {}
        breakdown: list[dict[str, Any]] = []
        rule_score_total = 0.0
        status = "ok"
        error_message: str | None = None

        try:
            for rule in settings.rules:
                start_time = monotonic() # temp
                result = classify_rule_result(
                    model=settings.llm_model,
                    job_text=job_text,
                    question=rule.prompt,
                    result_options=rule.result_options,
                    max_retries=settings.llm_max_retries,
                )
                print(f"job rule for job_id {job_id} scored in {monotonic() - start_time} sec") # temp

                feature_results[rule.key] = result

                applied_score = rule.score if result == rule.trigger_result_normalized else 0.0
                rule_score_total += applied_score
                breakdown.append(
                    {
                        "rule_key": rule.key,
                        "rule_name": rule.name,
                        "result": result,
                        "trigger_result": rule.trigger_result_normalized,
                        "base_score": rule.score,
                        "applied_score": applied_score,
                    }
                )
            jobs_scored_ok += 1
        except Exception as exc:
            status = "failed"
            error_message = str(exc).strip()[:4000] or "Unknown scoring error."
            jobs_failed += 1

        _upsert_job_score(
            connection=connection,
            job_id=job_id,
            rule_score=rule_score_total,
            total_score=rule_score_total,
            llm_provider=settings.llm_provider,
            llm_model=settings.llm_model,
            feature_results=feature_results,
            breakdown=breakdown,
            scoring_status=status,
            scoring_error=error_message,
            scoring_version=settings.version,
        )

    return ScoringRunSummary(
        scoring_version=settings.version,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        jobs_selected=len(rows),
        jobs_scored_ok=jobs_scored_ok,
        jobs_failed=jobs_failed,
    )


def _load_jobs_for_scoring(
    connection: sqlite3.Connection,
    *,
    scoring_version: str,
    only_unscored: bool,
) -> list[sqlite3.Row]:
    """Load job rows that should be sent to the scoring pipeline."""
    base_query = """
        SELECT
            jobs.id,
            jobs.title,
            jobs.company,
            jobs.location,
            jobs.description,
            jobs.qualifications_text,
            jobs.job_highlights_json,
            jobs.extensions_json
        FROM jobs
    """

    params: tuple[Any, ...] = ()
    where_clauses = ["jobs.is_scorable = 1"]
    if only_unscored:
        base_query += """
            LEFT JOIN job_scores
                ON job_scores.job_id = jobs.id
                AND job_scores.scoring_version = ?
        """
        params = (scoring_version,)
        where_clauses.append("job_scores.id IS NULL")

    if where_clauses:
        base_query += "\nWHERE " + " AND ".join(where_clauses)

    base_query += "\nORDER BY jobs.last_seen_at DESC, jobs.id DESC"
    rows = connection.execute(base_query, params).fetchall()
    return [row for row in rows if isinstance(row, sqlite3.Row)]


def _build_job_text(row: sqlite3.Row) -> str:
    """Build compact prompt context from the normalized jobs table fields."""
    sections = [
        f"Job Title: {_safe_text(row['title'])}",
        f"Company: {_safe_text(row['company'])}",
        f"Location: {_safe_text(row['location'])}",
        f"Description: {_safe_text(row['description'])}",
        f"Qualifications: {_safe_text(row['qualifications_text'])}",
        f"Highlights: {_extract_highlights_text(row['job_highlights_json'])}",
        f"Extensions: {_extract_extensions_text(row['extensions_json'])}",
    ]
    return "\n".join(sections)


def _extract_highlights_text(job_highlights_json: str | None) -> str:
    """Flatten job_highlights JSON into a readable text line."""
    if not job_highlights_json:
        return "N/A"
    try:
        payload = json.loads(job_highlights_json)
    except json.JSONDecodeError:
        return "N/A"

    if not isinstance(payload, list):
        return "N/A"

    chunks: list[str] = []
    for highlight in payload:
        if not isinstance(highlight, dict):
            continue
        title = _safe_text(highlight.get("title"))
        items = highlight.get("items")
        if isinstance(items, list):
            clean_items = []
            for item in items:
                normalized_item = _safe_text(item)
                if normalized_item != "N/A":
                    clean_items.append(normalized_item)
            if clean_items:
                chunks.append(f"{title}: {', '.join(clean_items)}")
            elif title != "N/A":
                chunks.append(title)
            continue
        if title != "N/A":
            chunks.append(title)

    return " | ".join(chunks) if chunks else "N/A"


def _extract_extensions_text(extensions_json: str | None) -> str:
    """Flatten extensions JSON into short comma-separated text."""
    if not extensions_json:
        return "N/A"
    try:
        payload = json.loads(extensions_json)
    except json.JSONDecodeError:
        return "N/A"

    if not isinstance(payload, list):
        return "N/A"

    values = []
    for item in payload:
        normalized_item = _safe_text(item)
        if normalized_item != "N/A":
            values.append(normalized_item)
    return ", ".join(values) if values else "N/A"


def _safe_text(value: Any) -> str:
    """Normalize optional text-like values for prompt construction."""
    if value is None:
        return "N/A"
    text = str(value).strip()
    return text if text else "N/A"


def _upsert_job_score(
    *,
    connection: sqlite3.Connection,
    job_id: int,
    rule_score: float,
    total_score: float,
    llm_provider: str,
    llm_model: str,
    feature_results: dict[str, str],
    breakdown: list[dict[str, Any]],
    scoring_status: str,
    scoring_error: str | None,
    scoring_version: str,
) -> None:
    """Insert/update one job_scores row for a job + scoring version."""
    connection.execute(
        """
        INSERT INTO job_scores (
            job_id,
            rule_score,
            resume_embedding_score,
            ideal_job_embedding_score,
            total_score,
            llm_provider,
            llm_model,
            feature_results_json,
            breakdown_json,
            scoring_status,
            scoring_error,
            scoring_version,
            scored_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id, scoring_version)
        DO UPDATE SET
            rule_score = excluded.rule_score,
            resume_embedding_score = excluded.resume_embedding_score,
            ideal_job_embedding_score = excluded.ideal_job_embedding_score,
            total_score = excluded.total_score,
            llm_provider = excluded.llm_provider,
            llm_model = excluded.llm_model,
            feature_results_json = excluded.feature_results_json,
            breakdown_json = excluded.breakdown_json,
            scoring_status = excluded.scoring_status,
            scoring_error = excluded.scoring_error,
            scored_at = excluded.scored_at
        """,
        (
            job_id,
            rule_score,
            None,
            None,
            total_score,
            llm_provider,
            llm_model,
            json.dumps(feature_results, sort_keys=True),
            json.dumps(breakdown, sort_keys=True),
            scoring_status,
            scoring_error,
            scoring_version,
            utc_now_iso(),
        ),
    )
