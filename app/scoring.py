"""Deterministic job scoring flow driven by scoring.json + Ollama extraction."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.config import WorkerConfig
from app.db import utc_now_iso
from app.ollama import classify_fit_recommendation, classify_rule_result, unload_model
from time import monotonic # temp import to see how long scoring takes

# ------------------------------ MODELS ------------------------------ #

@dataclass(frozen=True)
class ScoringRunSummary:
    """Aggregate counters returned after scoring finishes."""

    scoring_version: str
    llm_provider: str
    llm_model: str
    rule_model: str
    fit_model: str
    jobs_selected: int
    jobs_scored_ok: int
    jobs_failed: int
    fit_jobs_attempted: int
    fit_jobs_scored_ok: int
    fit_jobs_failed: int

@dataclass(frozen=True)
class RulePassResult:
    jobs_scored_ok: int
    jobs_failed: int
    successful_rows: list[sqlite3.Row]


@dataclass(frozen=True)
class FitPassResult:
    jobs_attempted: int
    jobs_scored_ok: int
    jobs_failed: int


# ------------------------- SCORING ENTRYPOINT ------------------------ #

def run_job_scoring(
    connection: sqlite3.Connection,
    config: WorkerConfig,
    *,
    only_unscored: bool = False,
) -> ScoringRunSummary:
    """Score jobs in two passes: rules first, then fit recommendation."""
    settings = config.scoring_config

    rows = _load_jobs_for_scoring(
        connection,
        scoring_version=settings.version,
        only_unscored=only_unscored,
    )

    rule_pass = _run_rule_scoring_pass(connection, config, rows)
    try:
        fit_pass = _run_fit_scoring_pass(connection, config, rule_pass.successful_rows)
    finally:
        unload_model(settings.llm_fit_model)

    return ScoringRunSummary(
        scoring_version=settings.version,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_rule_model,
        rule_model=settings.llm_rule_model,
        fit_model=settings.llm_fit_model,
        jobs_selected=len(rows),
        jobs_scored_ok=rule_pass.jobs_scored_ok,
        jobs_failed=rule_pass.jobs_failed,
        fit_jobs_attempted=fit_pass.jobs_attempted,
        fit_jobs_scored_ok=fit_pass.jobs_scored_ok,
        fit_jobs_failed=fit_pass.jobs_failed,
    )



# --------------------------- SCORING PASSES -------------------------- #

def _run_rule_scoring_pass(
    connection: sqlite3.Connection,
    config: WorkerConfig,
    rows: list[sqlite3.Row],
) -> RulePassResult:
    """Run the rule model across the selected batch and persist numeric results."""
    settings = config.scoring_config
    jobs_scored_ok = 0
    jobs_failed = 0
    successful_rows: list[sqlite3.Row] = []

    try:
        for row in rows:
            job_id = int(row["id"])
            job_text = _build_job_text(row)

            feature_results: dict[str, str] = {}
            breakdown: list[dict[str, Any]] = []
            rule_score_total = 0.0
            status = "ok"
            error_message: str | None = None
            print(f"scoring rules for job_id {job_id}")

            try:
                for rule in settings.rules:
                    start_time = monotonic() # temp
                    result = classify_rule_result(
                        model=settings.llm_rule_model,
                        job_text=job_text,
                        question=rule.prompt,
                        result_options=rule.result_options,
                        think=settings.llm_rule_think,
                        max_retries=settings.llm_max_retries,
                        keep_alive=-1,
                    )
                    print(f"   job rule {rule.name} scored in {monotonic() - start_time} sec") # temp

                    feature_results[rule.key] = result

                    if rule.terminate_options and result in rule.terminate_options:
                        # double and negative the rules score if its a dealbreaker
                        applied_score = -(abs(rule.score) * 2) if result == rule.trigger_result_normalized else 0.0
                    else:
                        applied_score = rule.score if result == rule.trigger_result_normalized else 0.0

                    rule_score_total += applied_score
                    breakdown.append({
                            "rule_key": rule.key,
                            "rule_name": rule.name,
                            "result": result,
                            "trigger_result": rule.trigger_result_normalized,
                            "base_score": rule.score,
                            "applied_score": applied_score,
                        })

                    if rule.terminate_options and result in rule.terminate_options:
                        break # exit rule scoring loop for jobs that hit the terminate option / dealbreaker

                jobs_scored_ok += 1
                successful_rows.append(row)
            except Exception as exc:
                status = "failed"
                error_message = str(exc).strip()[:4000] or "Unknown scoring error."
                jobs_failed += 1

            _upsert_rule_score(
                connection=connection,
                job_id=job_id,
                rule_score=rule_score_total,
                total_score=rule_score_total,
                llm_provider=settings.llm_provider,
                llm_model=settings.llm_rule_model,
                feature_results=feature_results,
                breakdown=breakdown,
                scoring_status=status,
                scoring_error=error_message,
                scoring_version=settings.version,
            )
    finally:
        unload_model(settings.llm_rule_model)

    return RulePassResult(
        jobs_scored_ok=jobs_scored_ok,
        jobs_failed=jobs_failed,
        successful_rows=successful_rows,
    )


def _run_fit_scoring_pass(
    connection: sqlite3.Connection,
    config: WorkerConfig,
    rows: list[sqlite3.Row],
) -> FitPassResult:
    """Run the fit model across the rule-scored batch and store fit labels."""
    settings = config.scoring_config
    jobs_attempted = 0
    jobs_scored_ok = 0
    jobs_failed = 0

    for row in rows:
        job_id = int(row["id"])
        job_text = _build_job_text(row)
        fit_recommendation: str | None = None
        print(f"scoring fit for job_id {job_id}")
        jobs_attempted += 1

        try:
            fit_recommendation = classify_fit_recommendation(
                model=settings.llm_fit_model,
                job_text=job_text,
                resume_text=config.resume_text,
                ideal_job_text=config.ideal_job_text,
                think=settings.llm_fit_think,
                max_retries=settings.llm_max_retries,
                keep_alive=-1,
            )
            jobs_scored_ok += 1
        except Exception:
            fit_recommendation = None
            jobs_failed += 1

        _update_fit_recommendation(
            connection=connection,
            job_id=job_id,
            fit_recommendation=fit_recommendation,
            scoring_version=settings.version,
        )

    return FitPassResult(
        jobs_attempted=jobs_attempted,
        jobs_scored_ok=jobs_scored_ok,
        jobs_failed=jobs_failed,
    )


# ------------------------- JOB TEXT BUILDING ------------------------- #

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


# ---------------------------- TEXT HELPERS --------------------------- #

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


# ----------------------------- DB WRITES ----------------------------- #

def _upsert_rule_score(
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
            total_score,
            llm_provider,
            llm_model,
            feature_results_json,
            breakdown_json,
            scoring_status,
            scoring_error,
            scoring_version,
            scored_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id, scoring_version)
        DO UPDATE SET
            rule_score = excluded.rule_score,
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


def _update_fit_recommendation(
    *,
    connection: sqlite3.Connection,
    job_id: int,
    fit_recommendation: str | None,
    scoring_version: str,
) -> None:
    """Update the fit label for an existing rule-scored row."""
    connection.execute(
        """
        UPDATE job_scores
        SET
            fit_recommendation = ?,
            scored_at = ?
        WHERE job_id = ? AND scoring_version = ?
        """,
        (
            fit_recommendation,
            utc_now_iso(),
            job_id,
            scoring_version,
        ),
    )
