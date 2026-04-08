# Job Search Decision Engine

This repo is a personal, local-first job search pipeline.

The idea is simple: pull job results from Google Jobs through SerpApi, save the raw responses, turn those results into normalized job rows, score them with Ollama, and export a spreadsheet that is actually usable when you're reviewing jobs.

## What it does

- runs saved job search queries from `config/queries.json`
- archives every returned search page in SQLite
- keeps a normalized `jobs` table for deduped job records
- remembers which query names a job came from
- scores jobs with LLM driven rules from `config/scoring.json`
- adds a separate LLM driven fit recommendation pass using your resume and ideal role text
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

## How The Scoring Works

Scoring is rule-based, but the rules are judged by an LLM.

Each rule in `config/scoring.json` asks one simple question about the job posting. For example:

```json
{
  "name": "seniority_too_high",
  "prompt": "Does this role clearly target senior, staff, lead, principal, architect, manager, or otherwise advanced-level software engineers?",
  "score": -10,
  "result_options": ["true", "false"],
  "trigger_result": "true",
  "terminate_options": ["true"]
}
```

The flow is pretty simple:

1. A job gets turned into plain text.
2. The model is asked each rule question one at a time.
3. The model must answer using one of the allowed results, like `true` or `false`.
4. If the answer matches the `trigger_result`, that rule's score is applied.
5. All the rule scores are added together into the final numeric score.

Some rules can also stop scoring early. Those use `terminate_options`.

That is useful for obvious dealbreakers. For example, if a job is clearly senior-only or clearly not remote, there is not much value in spending more model calls scoring the rest of the posting. In those cases, the rule can act like an early exit.

There is also a separate fit recommendation pass that labels the job as `low`, `medium`, or `high` fit using the job text, your resume, and your ideal job description. That fit label is helpful for review, but it does not currently change the numeric score.

The tradeoff with LLM scoring is that it is flexible, but it is not perfectly consistent.

A weaker model can still work, especially if the prompts are short and direct, but it will usually:

- miss nuance more often
- be less consistent from one job to the next
- struggle more with messy or vague postings
- need retries more often when the answer format is not clean

A stronger model usually does a better job with gray-area decisions, but the cost is more compute, more memory pressure, and often slower runs.

So the practical rule here is: keep the prompts simple, test the scoring on real examples, and do not assume a smaller model will make great judgment calls just because it can answer basic yes/no questions.


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
- model selections specified in `config/scoring.json`

### 2. Set up your config

Before you run anything for real, make sure these files are in decent shape:

- `config/.env`
- `config/queries.json`
- `config/scoring.json`
- `config/resume.txt`
- `config/ideal_job.txt`

If those are messy or malformed, the pipeline will still run, but the output will usually be messy too.

### 3. Pick your models

My recommendation is to use two different kinds of models:

- a smaller, coherent, "tiny but dependable" model for the rule scoring pass
- a stronger thinking model for the fit recommendation pass

That split works well because the rule scoring step is repetitive and structured. It is asking a lot of short closed-set questions like "is this senior?" or "is this remote?" That usually benefits more from consistency and speed than from heavy reasoning.

The fit recommendation step is different. That one is trying to look at the job, your resume, and your target role together and make a broader judgment call. That tends to benefit from a stronger model.

So in practice:

- use the smaller model for `llm.rule_model`
- use the stronger model for `llm.fit_model`
- keep rule prompts short and clear
- do not waste a big thinking model on every single rule unless you really need it

I recommend gemma3:4b for rule scoring and gemma4:e2b for fit recommendations.

### 4. Set up your rules well

The rules matter a lot. A good rule set is usually better than a clever prompt.

Some practical advice:

- put the most important rules first
- put clear dealbreakers at the top
- use `terminate_options` for obvious hard stops
- keep each rule focused on one idea
- avoid stacking multiple judgments into one prompt

The reason ordering matters is that dealbreakers can stop scoring early. So if you already know a job is senior-only, not remote, or otherwise clearly wrong, it is better to catch that fast instead of burning extra model calls on the rest of the rule list.

### 5. Cast a wide net with queries

It is usually better for the search queries to be broad and let scoring do the filtering.

In other words:

- let the queries pull in a wide range of maybe-relevant jobs
- let the scoring rules narrow that set down

If the queries are too narrow, you might miss jobs before the scoring system ever gets a chance to look at them. If the queries are a little broader, the scoring layer can do the cleanup.

### 6. Run the pipeline

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

### 7. Check outputs

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
- the repo is optimized for one person's workflow first

## If you are picking this up later

If you come back to this after a while and want the shortest possible path back in:

1. Check `config/scoring.json`
2. Check `config/queries.json`
3. Make sure Ollama is running
4. Run `python3 scripts/run_pipeline.py`
5. Read `config/worker.log` if anything feels off

That should be enough to get your bearings again without having to rediscover the whole codebase from scratch.
