"""Interactive local entrypoint for running worker pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass

from _script_runtime import load_local_worker_config
from app.db import get_connection, init_db
from app.worker_logging import get_logger



LOGGER = get_logger("scripts.run_pipeline")


@dataclass(frozen=True)
class StagePlan:
    """Normalized stage selection from the interactive prompt."""

    key: str
    label: str
    run_search: bool
    run_scoring: bool
    run_report: bool


STAGE_PLANS: dict[str, StagePlan] = {
    "1": StagePlan("1", "search only", True, False, False),
    "2": StagePlan("2", "scoring only", False, True, False),
    "3": StagePlan("3", "report only", False, False, True),
    "4": StagePlan("4", "search + scoring", True, True, False),
    "5": StagePlan("5", "scoring + report", False, True, True),
    "6": StagePlan("6", "search + scoring + report", True, True, True),
}

ALIASES = {
    "search": "1",
    "scoring": "2",
    "score": "2",
    "report": "3",
    "search+scoring": "4",
    "search,scoring": "4",
    "scoring+report": "5",
    "scoring,report": "5",
    "score+report": "5",
    "search+scoring+report": "6",
    "search,scoring,report": "6",
}


def main() -> None:
    """Prompt for a stage combination and run the chosen local pipeline flow."""
    config = load_local_worker_config(context="run_pipeline")
    LOGGER.info("Script start: run_pipeline")

    stage_plan = _prompt_for_stage_plan()
    LOGGER.info("Selected stage plan: key=%s label=%s", stage_plan.key, stage_plan.label)

    init_db(config.paths.db_path)

    search_summary = None
    scoring_summary = None
    report_summary = None

    if stage_plan.run_search:
        from app.search import run_enabled_queries

        LOGGER.info("Stage start: search")
        search_summary = run_enabled_queries(config)

    if stage_plan.run_scoring:
        from app.scoring import run_job_scoring

        LOGGER.info("Stage start: scoring")
        with get_connection(config.paths.db_path) as connection:
            scoring_summary = run_job_scoring(connection, config, only_unscored=False)

    if stage_plan.run_report:
        from app.reporting import generate_report

        LOGGER.info("Stage start: report")
        with get_connection(config.paths.db_path) as connection:
            report_summary = generate_report(connection, config)

    _print_summary(stage_plan, search_summary, scoring_summary, report_summary)
    LOGGER.info("Script complete: run_pipeline plan=%s", stage_plan.label)


def _prompt_for_stage_plan() -> StagePlan:
    """Prompt until the user selects a valid stage combination."""
    prompt = (
        "\nChoose what to run:\n"
        "  1. search only\n"
        "  2. scoring only\n"
        "  3. report only\n"
        "  4. search + scoring\n"
        "  5. scoring + report\n"
        "  6. search + scoring + report\n"
        "> "
    )

    while True:
        raw_value = input(prompt).strip().lower()
        normalized = ALIASES.get(raw_value, raw_value)
        stage_plan = STAGE_PLANS.get(normalized)
        if stage_plan is not None:
            return stage_plan
        print("Invalid choice. Enter 1-6.")


def _print_summary(
    stage_plan: StagePlan,
    search_summary,
    scoring_summary,
    report_summary,
) -> None:
    """Print a compact terminal summary for the selected run."""
    print("\nRun complete")
    print(f"Plan: {stage_plan.label}")

    if search_summary is not None:
        print(
            "Search: "
            f"queries={search_summary.queries_run}, "
            f"pages={search_summary.total_pages_fetched}, "
            f"raw_requests={search_summary.total_raw_requests_stored}, "
            f"jobs_upserted={search_summary.total_jobs_upserted}, "
            f"errors={search_summary.total_error_count}"
        )

    if scoring_summary is not None:
        print(
            "Scoring: "
            f"jobs_selected={scoring_summary.jobs_selected}, "
            f"rule_ok={scoring_summary.jobs_scored_ok}, "
            f"rule_failed={scoring_summary.jobs_failed}, "
            f"fit_attempted={scoring_summary.fit_jobs_attempted}, "
            f"fit_ok={scoring_summary.fit_jobs_scored_ok}, "
            f"fit_failed={scoring_summary.fit_jobs_failed}"
        )

    if report_summary is not None:
        print(
            "Report: "
            f"export_id={report_summary.export_id}, "
            f"path={report_summary.export_path}, "
            f"new={report_summary.new_count}, "
            f"all={report_summary.all_count}, "
            f"all_jobs_list={report_summary.all_jobs_list_count}"
        )



if __name__ == "__main__":
    main()
