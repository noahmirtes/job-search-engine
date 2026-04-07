# Job Search Decision Engine

This repo is a personal, local-first job search pipeline.

The idea is simple: pull job results from Google Jobs through SerpApi, save the raw responses so nothing valuable gets lost, turn those results into normalized job rows, score them with Ollama, and export a spreadsheet that is actually usable when you're reviewing jobs.

This is not an auto-apply bot. It is not trying to be a full SaaS app either. It is more like a practical filtering and review tool for one person running their own search.

## What it does

- runs saved job search queries from `config/queries.json`
- archives every returned search page in SQLite
- keeps a normalized `jobs` table for deduped job records
- remembers which query names a job came from
- scores jobs with LLM-driven rules from `config/scoring.json`
- adds a separate fit recommendation pass using your resume and ideal role text
- exports `.xlsx` reports to `config/reports/`
- writes light operational logs to `config/worker.log`
- falls back to `config/raw_response_backup/` if a raw response can't be written to SQLite

## How the pipeline works

At a high level, the flow is:

1. Load config from `config/`.
2. Run the enabled SerpApi queries.
3. Archive each returned raw search page right away.
4. Parse and upsert jobs from that raw payload.
5. Score jobs that are scorable.
6. Generate an Excel report.

One important design choice here: raw search responses are treated as the source of truth.

That means the search stage is intentionally "archive first, derive second." If parsing or job upserting fails later, the raw response is still preserved and can be replayed with the backfill script.

## Project layout

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
│   ├── serpapi.py
│   └── worker_logging.py
├── config/
│   ├── .env
│   ├── ideal_job.txt
│   ├── jobs.db
│   ├── queries.json
│   ├── reports/
│   ├── resume.txt
│   ├── scoring.json
│   └── worker.log
├── orchestrator/
├── scripts/
│   ├── init_db.py
│   ├── recompute_job_scorability.py
│   ├── run_pipeline.py
│   └── upsert_jobs_from_raw.py
├── README.md
└── requirements.txt
```

## Main pieces

### `app/search.py`

Runs the search queries and handles the archive-first ingest flow.

- asks SerpApi for one page at a time
- stores each returned attempt in `raw_requests`
- commits that raw row immediately
- only then upserts normalized jobs
- writes a JSON backup to `config/raw_response_backup/` if the raw DB write fails

### `app/jobs.py`

Turns `jobs_results` payloads into normalized rows in `jobs`.

It also handles:

- deduping
- query-source tracking with `query_names_json`
- derived `date_posted`
- scorable vs unscorable flagging

### `app/scoring.py`

Scores jobs using the rules in `config/scoring.json`.

Right now scoring is LLM-driven, not keyword-driven.

- each rule is a closed-set classification call
- scores add up into a numeric total
- some rules can terminate scoring early
- a separate pass adds a `low` / `medium` / `high` fit recommendation
- blacklisted companies are skipped before Ollama is called

### `app/reporting.py`

Builds the Excel output.

Current report behavior:

- exports to `config/reports/`
- includes `new` and `all` sheets
- can optionally include `all_jobs_list`
- shows source query names
- hyperlinks apply locations directly in the sheet
- uses light pastel formatting for readability

## Config files

Everything important lives in `config/`.

### `config/.env`

Private env vars. At minimum you need:

```env
SERPAPI_API_KEY=your_key_here
```

The app loads this file itself in Python. You do not need to `source` it manually.

If an env var is already set in the shell or on the machine, that existing value wins over the `.env` file.

### `config/queries.json`

Defines the searches to run.

Each entry has:

- `name`
- `enabled`
- `max_pages`
- `request`

Example:

```json
[
  {
    "name": "junior_backend_engineer_ltype",
    "enabled": true,
    "max_pages": 2,
    "request": {
      "engine": "google_jobs",
      "google_domain": "google.com",
      "q": "junior backend engineer",
      "location": "United States",
      "ltype": "1",
      "hl": "en",
      "gl": "us"
    }
  }
]
```

### `config/scoring.json`

Controls the scoring behavior.

It currently includes:

- scoring version
- rule model and fit model
- think-mode settings
- max retries for each LLM call
- report settings
- company blacklist
- active rules

Example blacklist shape:

```json
{
  "blacklist": [
    "SynergisticIT"
  ]
}
```

Blacklist matching is exact after trim + lowercase normalization.

### `config/resume.txt`

Plain text version of your resume for the fit recommendation pass.

### `config/ideal_job.txt`

Plain text description of the kind of job you actually want.

## Running it locally

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

You will also need:

- a working SerpApi key
- Ollama running locally
- the models referenced in `config/scoring.json`

### 2. Run the pipeline

The main local entrypoint is:

```bash
python3 scripts/run_pipeline.py
```

That script prompts you to choose:

- search only
- scoring only
- report only
- search + scoring
- scoring + report
- search + scoring + report

### 3. Check outputs

After a run, the main things to look at are:

- `config/jobs.db`
- `config/reports/`
- `config/worker.log`

If something goes wrong during raw archival, also check:

- `config/raw_response_backup/`

## Utility scripts

These are still useful, but they are not part of the main interactive runner.

### Initialize or sync the DB

```bash
python3 scripts/init_db.py
```

### Recompute which jobs are scorable

```bash
python3 scripts/recompute_job_scorability.py
```

### Replay archived raw responses back into `jobs`

```bash
python3 scripts/upsert_jobs_from_raw.py
```

That last one is especially helpful if raw responses are intact but normalized job rows need to be rebuilt.

## Database overview

The main tables are:

- `raw_requests`: every archived search page
- `jobs`: normalized, deduped jobs
- `job_scores`: one scoring row per `job_id + scoring_version`
- `exports`: report history
- `export_jobs`: which jobs were included in each export

A couple of helpful notes:

- `jobs.query_names_json` tracks which queries a job came from
- `job_scores.scoring_status` can be things like `ok`, `failed`, or `blacklisted`
- "new" jobs in the report are based on the latest row in `exports`, not `export_jobs`

## Logging

Worker logs go to `config/worker.log` and also print to the terminal.

The logging is intentionally light and top-level. It covers things like:

- queries starting and finishing
- page/archive results
- scoring progress
- fit recommendation progress
- report generation
- script start/finish summaries

It is meant to be useful when something breaks, without turning into a wall of noise.

## Orchestrator

There is also an orchestrator in `orchestrator/` for scheduled profile-based runs.

That path is separate from the local interactive runner and is mainly for full automated runs. If you're just working on the system manually, start with `scripts/run_pipeline.py`.

## A few honest rough edges

This project is useful, but it is still a working tool rather than a polished product.

Some current realities:

- there are no real automated tests yet
- Ollama model behavior can still be the main source of instability
- `app/main.py` is basically an old local smoke script, not the real entrypoint
- the repo is optimized for one person's workflow first

## If you are picking this up later

If you come back to this after a while and want the shortest possible path back in:

1. Check `config/scoring.json`
2. Check `config/queries.json`
3. Make sure Ollama is running
4. Run `python3 scripts/run_pipeline.py`
5. Read `config/worker.log` if anything feels off

That should be enough to get your bearings again without having to rediscover the whole codebase from scratch.
