# Job Search Decision Engine

## Overview

This project is a local-first job search pipeline for collecting Google Jobs results through SerpApi, storing them historically, scoring them, and exporting reviewable Excel reports.

The current codebase supports:

- search ingestion from SerpApi Google Jobs
- raw request/response archival in SQLite
- normalized job upsert and deduplication
- rule-based job scoring through Ollama
- report generation to Excel
- optional orchestration for scheduled profile runs

This is a decision engine for job search. It is not an auto-apply tool, not an ATS, and not a dashboard app.

## Current Pipeline

The implemented flow is:

1. Load config and environment from `config/`.
2. Run enabled SerpApi Google Jobs searches.
3. Store every raw API page in `raw_requests`.
4. Normalize `jobs_results` and upsert them into `jobs`.
5. Score scorable jobs into `job_scores`.
6. Export a workbook to `config/reports/`.
7. Record export history in `exports` and `export_jobs`.

There are also helper scripts to replay historical raw responses into `jobs` and to recompute scoring eligibility flags.

## Repo Layout

```text
job-search-engine/
├── app/
│   ├── config.py
│   ├── db.py
│   ├── jobs.py
│   ├── ollama.py
│   ├── posting_date.py
│   ├── reporting.py
│   ├── scoring.py
│   ├── search.py
│   └── serpapi.py
├── config/
│   ├── .env
│   ├── ideal_job.txt
│   ├── jobs.db
│   ├── queries.json
│   ├── reports/
│   ├── resume.txt
│   └── scoring.json
├── orchestrator/
│   ├── .env
│   ├── emailer.py
│   ├── main.py
│   ├── models.py
│   ├── pipeline.py
│   ├── profiles.json
│   └── state.json
├── scripts/
│   ├── init_db.py
│   ├── recompute_job_scorability.py
│   ├── run_report.py
│   ├── run_scoring.py
│   ├── run_search.py
│   ├── score_and_report.py
│   └── upsert_jobs_from_raw.py
├── README.md
└── requirements.txt
```

## Configuration

The worker is driven by the files in `config/`:

- `config/.env`: private environment values such as `SERPAPI_API_KEY`
- `config/queries.json`: enabled search requests and page limits
- `config/scoring.json`: scoring rules, model config, and report settings
- `config/resume.txt`: resume text for future comparison features
- `config/ideal_job.txt`: target-role reference text for future comparison features
- `config/jobs.db`: SQLite database
- `config/reports/`: generated report workbooks

### `queries.json`

Each query is close to the raw SerpApi request shape:

```json
[
  {
    "name": "backend_remote_us",
    "enabled": true,
    "max_pages": 1,
    "request": {
      "engine": "google_jobs",
      "q": "python backend engineer",
      "location": "United States",
      "google_domain": "google.com",
      "hl": "en",
      "gl": "us"
    }
  }
]
```

### `scoring.json`

`scoring.json` currently controls:

- scoring version
- Ollama provider/model settings
- rule definitions and scoring weights
- report threshold
- whether to include the `all_jobs_list` tab

## Search / Ingestion

Search execution lives in `app/search.py`. For each enabled query it:

- calls SerpApi through `app/serpapi.py`
- paginates using SerpApi `next_page_token`
- stores every raw page response in `raw_requests`
- upserts normalized jobs from that payload into `jobs`

Job normalization lives in `app/jobs.py`. It currently extracts and stores fields including:

- title
- company
- location
- description
- apply URL
- share link
- schedule type
- qualifications
- raw job JSON
- apply options JSON
- extensions JSON
- detected extensions JSON
- job highlights JSON
- derived `date_posted`
- `is_scorable`
- `scorable_missing_fields_json`
- `normalized_hash`

Deduplication/upsert identity currently works by:

- `source_job_id` when available
- otherwise `normalized_hash`

## Scoring

Scoring lives in `app/scoring.py`.

The current implementation is rule-based classification driven by Ollama:

- each job is turned into compact prompt text
- each configured rule asks a closed-set question
- Ollama must return one allowed result
- matching results add or subtract score
- some rules can terminate scoring early
- one row per `job_id + scoring_version` is upserted into `job_scores`

Important current-state note:

- embedding scoring is planned but not implemented yet
- `resume_embedding_score` and `ideal_job_embedding_score` exist in the schema but are currently stored as `NULL`
- scoring is currently based on rule evaluation only

## Reporting

Report generation lives in `app/reporting.py`.

Reports are written to `config/reports/` as `.xlsx` files with:

- `new` tab: jobs considered new since the latest export
- `all` tab: all scored jobs above the configured threshold
- `all_jobs_list` tab: optional full list of scorable jobs

The current report logic defines "new" like this:

- read the most recent `exports.exported_at`
- include rows where `jobs.first_seen_at > latest exported_at`

That means the export reset lever is the `exports` table. Clearing only `export_jobs` does not reset what counts as new.

## Database Schema

The SQLite schema is defined in `app/db.py`.

### `raw_requests`

Stores every search page fetched from SerpApi.

- `id`
- `query_name`
- `query_params_json`
- `response_json`
- `response_status`
- `result_count`
- `requested_at`

### `jobs`

Stores normalized and deduplicated jobs.

- `id`
- `source_job_id`
- `title`
- `company`
- `location`
- `description`
- `apply_url`
- `share_link`
- `via`
- `thumbnail`
- `posted_at_text`
- `schedule_type`
- `work_from_home`
- `qualifications_text`
- `raw_job_json`
- `apply_options_json`
- `extensions_json`
- `detected_extensions_json`
- `job_highlights_json`
- `date_posted`
- `is_scorable`
- `scorable_missing_fields_json`
- `normalized_hash`
- `first_seen_at`
- `last_seen_at`

### `job_scores`

Stores one scoring row per job and scoring version.

- `id`
- `job_id`
- `rule_score`
- `resume_embedding_score`
- `ideal_job_embedding_score`
- `total_score`
- `llm_provider`
- `llm_model`
- `feature_results_json`
- `breakdown_json`
- `scoring_status`
- `scoring_error`
- `scoring_version`
- `scored_at`

### `exports`

Stores report run history.

- `id`
- `exported_at`
- `export_file_name`

### `export_jobs`

Stores the jobs included in a given export.

- `id`
- `export_id`
- `job_id`

## Scripts

### Initialize the database

```bash
.venv/bin/python scripts/init_db.py
```

Creates or syncs the SQLite schema in `config/jobs.db`.

### Run search ingestion

```bash
.venv/bin/python scripts/run_search.py
```

Runs all enabled queries, stores every raw page, and upserts jobs.

### Replay raw responses into jobs

```bash
.venv/bin/python scripts/upsert_jobs_from_raw.py
```

Useful for backfills if raw requests are already stored.

### Recompute job scorable flags

```bash
.venv/bin/python scripts/recompute_job_scorability.py
```

Rebuilds `jobs.is_scorable` and `jobs.scorable_missing_fields_json`.

### Run scoring

```bash
.venv/bin/python scripts/run_scoring.py
```

Scores jobs using the current `config/scoring.json` rules and model.

### Run report export

```bash
.venv/bin/python scripts/run_report.py
```

Builds a report workbook from scored jobs and records export metadata.

### Score and export in one command

```bash
.venv/bin/python scripts/score_and_report.py
```

Runs scoring first, then writes a report.

## Orchestrator

The `orchestrator/` package is a thin profile runner around the worker code. It exists to support scheduled runs and email delivery.

It currently reads:

- `orchestrator/profiles.json` for profile definitions and paths
- `orchestrator/state.json` for run timestamps and last-run status
- `orchestrator/.env` for mail credentials and orchestrator-specific env

The orchestrator pipeline calls the same worker logic used by the scripts:

- search
- scoring
- report generation
- optional email notification

## Setup

Create a virtualenv, install dependencies, and make sure these are available:

```bash
pip install -r requirements.txt
```

Required runtime pieces:

- SerpApi key in `config/.env` as `SERPAPI_API_KEY=...`
- Ollama running locally on `http://localhost:11434`
- the model referenced by `config/scoring.json` pulled locally

## Current Design Principles

- keep the system local-first and inspectable
- preserve every API response page historically
- keep config close to the raw API request shape
- use modular worker code with thin scripts
- prefer simple, explicit flow over heavy abstraction

## What Is Not Implemented Yet

These are still planned rather than live:

- embedding similarity scoring
- multi-resume routing
- UI/dashboard
- application tracking
- interview/rejection workflow
- auto-apply behavior
