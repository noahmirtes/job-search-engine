# Job Search Decision Engine

This is a local job search tool.

It pulls jobs from Google Jobs through SerpAPI, stores the raw responses so nothing valuable gets lost, turns them into normalized rows, scores them with Ollama, and spits out a report that is actually usable when you are trying to review jobs quickly.

That is the whole point of the project: less noise, better filtering, and a workflow that still keeps you in control.

## What it does

- runs saved job queries from `config/queries.json`
- archives every search page returned by SerpAPI
- keeps a normalized `jobs` table in SQLite
- remembers which query names a job came from
- scores jobs with LLM-based rules from `config/scoring.json`
- runs a separate fit recommendation pass using your resume and ideal role text
- exports `.xlsx` reports to `config/reports/`
- writes lightweight logs to `config/worker.log`
- falls back to `config/raw_response_backup/` if a raw response cannot be written to SQLite

## How the pipeline works

At a high level, the pipeline is:

1. Load config from `config/`
2. Run the enabled searches
3. Save each raw response immediately
4. Parse jobs out of that raw response
5. Upsert the normalized jobs
6. Score the jobs that are usable
7. Generate a report

One design choice matters more than most of the others: raw search responses are treated as the source of truth.

So the search flow is intentionally "archive first, derive second." If parsing or upserting fails later, the raw response is still there and can be recomputed. That matters because every request has tangible monetary and information value.

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

This is where the searches run.

It:

- asks SerpAPI for one page at a time
- stores each returned attempt in `raw_requests`
- commits that raw row right away
- only then parses and upserts jobs
- writes a JSON backup to `config/raw_response_backup/` if the raw DB write fails

### `app/jobs.py`

This is the job normalization layer.

It handles:

- parsing `jobs_results`
- deduping
- query-source tracking with `query_names_json`
- `date_posted`
- deciding whether a job is scorable or not

### `app/scoring.py`

This is the scoring engine.

Scoring is LLM-driven:

- each rule is a closed-set classification question
- the rule results add up into a numeric score
- some rules can stop scoring early
- a separate fit pass adds a `low`, `medium`, or `high` label
- blacklisted companies are excluded from scoring and reporting

### `app/reporting.py`

This builds the Excel report.

Right now the report:

- writes to `config/reports/`
- includes `new` and `all`
- can optionally include `all_jobs_list`
- hyperlinks the apply locations directly in the sheet
- uses color formatting to make the spreadsheet easier to scan
- includes extra job data that is useful during review

## Config files

Everything important lives in `config/`.

### `config/.env`

Private env vars. At minimum you need:

```env
SERPAPI_API_KEY=123456abcdef
```

The app loads this file itself. You do not need to `source` it manually.

If a variable is already set in your shell or on the machine, that value wins over the one in `.env`.

### `config/queries.json`

This file defines the searches.

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

This file controls scoring.

It currently includes:

- scoring version
- rule model and fit model
- think settings
- max retries
- report settings
- company blacklist
- the active rules

Example blacklist shape:

```json
{
  "blacklist": [
    "SynergisticIT"
  ]
}
```

Blacklist matching is intentionally simple: exact match after trim + lowercase normalization.

### `config/resume.txt`

Plain text version of your resume for the fit pass.

### `config/ideal_job.txt`

Plain text description of the kind of role you actually want.

## How the scoring works

The scoring is rule-based, but the rules are judged by an LLM.

Each rule asks one focused question about the posting. For example:

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

The basic flow is:

1. Turn the job into plain text
2. Ask the model each rule question
3. Force the model to answer with one allowed result
4. Apply the score if the result matches the trigger
5. Add everything up into the final numeric score

Some rules are dealbreakers. Those use `terminate_options`. If one of those fires, scoring stops early for that job.

That is useful for obvious cases like:

- clearly senior roles
- clearly non-remote roles
- clearly contract-only roles

There is also a separate fit pass that labels the job as `low`, `medium`, or `high` fit using:

- the job text
- your resume
- your ideal job description

That fit label is useful, but it does not currently change the numeric score. Instead, it acts as another signal and helps to balance out potential incorrectly scored rows due to model failure, inadequate job descriptions, or other speed bumps.

The tradeoff with LLM scoring is pretty straightforward: it is flexible and handles nuance better than raw keyword matching. However, weaker models are more likely to miss obvious things or be more inconsistent overall

So the practical advice is:

- keep the prompts short
- keep the questions direct
- test the scoring on real jobs
- do not assume a smaller model will make great judgment calls just because it can answer basic yes/no questions

## Running it locally

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

You also need:

- a working SerpAPI key
- Ollama running locally
- model choices set in `config/scoring.json`

### 2. Set up your config

Before you run anything for real, make sure these are in decent shape:

- `config/.env`
- `config/queries.json`
- `config/scoring.json`
- `config/resume.txt`
- `config/ideal_job.txt`

If those are sloppy, the pipeline will still run, but the output will probably be sloppy too.

### 3. Pick your models

Right now my recommendation is to use `gemma4:e2b` for both rule scoring and fit recommendations.

That has been giving solid results across both passes without the extra weirdness I was seeing from weaker models. I use the non thinking model on the rule scoring and the thinking model on the fit scoring.

Thinking modes can be set indepentently for those two scoring modules. Thinking settings can be found in `scoring.json`.

Run this command to download your selected model(s)
```bash
ollama pull <model_name>
```

The code does support using different models for each pass:

- `llm.rule_model`
- `llm.fit_model`

So if you want to experiment, you can absolutely split them. But if you just want something that works, start simple and use one strong model for both.

Short version:

- easiest setup: `gemma4:e2b` for both
- advanced setup: separate models if you have a clear reason
- either way, keep the rule prompts clean and direct

A critical factor in selecting your models is your hardware. For those of us without super powerful rigs and GPUs, the model selection is the most important part of the system, as the model quality dictates the scoring quality. I run `gemma4:e2b` on my M4 Mac Mini 16GB RAM and it runs quite well, though I do need to make sure there are no needless apps running that are taking up memory in order to prevent swap.

That said, I recommend:

- `gemma4:e2b` for CPU bound runs with 16GB RAM available.
- `gemma3:4b` for CPU bound runs with 8GB RAM available.

For reference, on my hardware, I average full scoring (rule and fit scoring) of 5.6 jobs per minute. Scoring runs can be long, but I explicitly wanted to keep this pipeline minimal and local, so the tradeoff is okay with me.

### 4. Set up your rules well

The rule list matters a lot. Good rules beat clever wording.

Some practical advice:

- put the most important rules first
- put dealbreakers at the top
- use `terminate_options` for obvious hard stops
- keep each rule focused on one idea
- avoid cramming multiple judgments into one prompt unless you really know what you are doing

Ordering matters because dealbreakers can stop scoring early. If a role is clearly wrong, it is better to catch that immediately than to waste more model calls on the rest of the rule list.

### 5. Cast a wide net with queries

In general, it is better for your queries to be a little broader and let scoring do the filtering.

In other words:

- let the search pull in a wider set of maybe-relevant jobs
- let the scoring rules narrow that set down

If the queries are too narrow, you can miss good jobs before scoring even gets a chance to look at them.

I’d recommend using a mix of:

- ultra-specific queries
- broader general queries
- some queries with `remote`
- some queries with `"ltype": "1"` since that old Google Jobs param still works

More queries means more SerpAPI requests, so there is a consequential tradeoff there depending on your API tier. You can tune that based on how often you run the system, how broad the market is, and what request tier you are on.

At the time of writing, the basic SerpAPI tiers look like this:

```txt
Free = 250 requests
Starter = 1000 requests at $25 / mo
Developer = 5000 requests at $75 / mo
```

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

### 7. Check the outputs

After a run, the main things to check are:

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

That last one is especially handy if the raw responses are still good but the normalized job rows need to be rebuilt.

## Database overview

The main tables are:

- `raw_requests`: every archived search page
- `jobs`: normalized, deduped jobs
- `job_scores`: one scoring row per `job_id + scoring_version`
- `exports`: report history
- `export_jobs`: which jobs were included in each export

A couple of notes that are worth remembering:

- `jobs.query_names_json` tracks which queries found a job
- `job_scores.scoring_status` can be `ok`, `failed`, or `blacklisted`
- "new" jobs in the report are based on the latest row in `exports`, not `export_jobs`

## Logging

Worker logs go to `config/worker.log` and also print to the terminal.

The logging is intentionally light. It covers things like:

- queries starting and finishing
- page/archive results
- scoring progress
- fit recommendation progress
- report generation
- script start and finish summaries

The goal is to make it useful when something breaks.

## Orchestrator

There is also an orchestrator in `orchestrator/` for scheduled profile runs.

That is separate from the local interactive runner. If you are just working with the system manually, start with `scripts/run_pipeline.py`.

## A few honest rough edges

This tool is useful, but it is still a working tool, not a polished product.

Some current realities:

- Ollama behavior is still one of the main sources of instability
- the repo is optimized for a personal workflow first

## If you are picking this up later

If you come back to this later and just want the shortest path back in:

1. Check `config/scoring.json`
2. Check `config/queries.json`
3. Make sure Ollama is running
4. Run `python3 scripts/run_pipeline.py`
5. Read `config/worker.log` if anything feels off
