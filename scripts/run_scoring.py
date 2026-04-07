"""Run configured LLM scoring against jobs stored in the local DB."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import initialize_config
from app.db import get_connection, init_db
from app.scoring import run_job_scoring
from _default_paths import _default_paths


def main() -> None:
    """Entrypoint for scoring all jobs with the configured Ollama model."""
    config = initialize_config(_default_paths(PROJECT_ROOT))
    init_db(config.paths.db_path)

    with get_connection(config.paths.db_path) as connection:
        summary = run_job_scoring(connection, config, only_unscored=False)

    print(f"Scoring version: {summary.scoring_version}")
    print(f"LLM provider: {summary.llm_provider}")
    print(f"Jobs selected: {summary.jobs_selected}")
    print(
        "Rule pass: "
        f"model={summary.rule_model}, "
        f"ok={summary.jobs_scored_ok}, "
        f"failed={summary.jobs_failed}"
    )
    print(
        "Fit pass: "
        f"model={summary.fit_model}, "
        f"attempted={summary.fit_jobs_attempted}, "
        f"ok={summary.fit_jobs_scored_ok}, "
        f"failed={summary.fit_jobs_failed}"
    )


if __name__ == "__main__":
    main()
