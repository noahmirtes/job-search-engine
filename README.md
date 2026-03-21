Job Search Decision Engine

Overview

This project is a local-first job search system that replaces manual job board browsing with a structured pipeline for ingesting, storing, scoring, and exporting job opportunities.

The system pulls job listings from SerpApi (Google Jobs), stores every request and all returned data historically, normalizes job records, deduplicates jobs at the normalized level, scores them using deterministic rules and embedding similarity, and exports a curated list of high-quality opportunities.

This is a decision engine for job search. It is not a scraper, not an application tracker, and not an auto-apply system.

⸻

Core Goals
	•	Collect job data from diverse aggregated sources through Google Jobs / SerpApi
	•	Preserve every request and response for historical reference
	•	Normalize job data into a clean internal schema
	•	Deduplicate repeated jobs without discarding raw source data
	•	Score jobs using:
	•	rule-based relevance signals
	•	embedding similarity against target reference text
	•	Export jobs that have not yet been surfaced in a previous export
	•	Produce a periodic (e.g., weekly) review sheet of relevant jobs to apply to

⸻

Core Architecture

The system has two primary entry points:

1. Ingestion

Responsible for:
	•	executing configured search queries against SerpApi
	•	storing every raw request/response
	•	normalizing returned jobs
	•	deduplicating job records
	•	automatically scoring newly ingested jobs

This creates a historical archive of all collected job data.

⸻

2. Export

Responsible for:
	•	selecting jobs that have not been exported before
	•	filtering to jobs worth reviewing
	•	generating an .xlsx file
	•	including full job descriptions in the export

This is the primary interface for reviewing and applying to jobs.

⸻

Core Pipeline

request jobs → store raw response → normalize jobs → deduplicate → score → store score → export unseen jobs

Scoring is automatic and occurs during ingestion.

⸻

Data Retention Rules
	•	Every API request must be stored
	•	Every raw response must be preserved
	•	Duplicate prevention applies only to normalized job entries
	•	Scoring results are stored per job and scoring version
	•	Export operations track which jobs have already been surfaced

⸻

Scoring System

Each job is scored using a combination of deterministic rules and embedding similarity.

Rule-Based Scoring

Explicit signals such as:
	•	job title relevance
	•	keyword matches (Python, backend, APIs, etc.)
	•	seniority alignment
	•	remote alignment
	•	penalties for mismatch

Embedding Similarity

Embedding similarity is used as a scoring signal.

Each job description is compared against:
	•	Resume reference (your current resume text)
	•	Ideal job reference (a manually written description of target roles)

These similarity scores contribute to the final score but do not dominate it.

⸻

Reference Inputs

Embedding references are stored as plain text files:
	•	config/resume.txt
	•	config/ideal_job.txt

These files are embedded and used as comparison targets for job descriptions.

⸻

Deduplication Strategy

Duplicates are identified using multiple signals:
	•	title
	•	company
	•	apply URL
	•	normalized composite hash

The goal is to prevent duplicate job entries while preserving all raw data.

⸻

Scoring Persistence

The job_scores table stores the latest score for each job under a given scoring version.

Behavior:
	•	new jobs are scored automatically during ingestion
	•	scoring logic is versioned
	•	manual rescoring can be triggered when scoring logic changes
	•	rescoring updates jobs to the new scoring version
	•	duplicate score entries for the same job and version are not retained

⸻

Export Behavior

Exports include:
	•	jobs that have not been included in a previous export
	•	jobs from the most recent ingestion window
	•	jobs with scores above a configurable threshold

This ensures exports contain only new, relevant opportunities.

Export format:
	•	.xlsx

Each row includes:
	•	title
	•	company
	•	location
	•	apply URL
	•	score
	•	description
	•	date posted
	•	source query (optional but recommended)

⸻

Configuration

Search queries are stored in a JSON config file:

config/queries.json

This allows:
	•	easy iteration on search strategy
	•	separation of configuration from code
	•	flexible control over:
	•	search phrases
	•	location
	•	remote filters
	•	pagination depth

⸻

Non-Goals (v1)
	•	no application tracking
	•	no interview/rejection tracking
	•	no multi-resume routing
	•	no UI/dashboard
	•	no auto-apply system
	•	no LLM-based parsing as a core dependency

⸻

Planned Extensions (Future)

Analysis Module
	•	identify recurring employer requirements
	•	extract common tools and technologies
	•	surface skill gaps
	•	analyze trends across job listings

Multi-Resume Support
	•	route jobs to different resume variants

Advanced AI Parsing
	•	structured extraction of job requirements

⸻

Suggested Project Structure

job-search-engine/
	•	app/
	•	clients/
	•	ingest/
	•	scoring/
	•	embeddings/
	•	export/
	•	db/
	•	config/
	•	scripts/
	•	ingest_jobs.py
	•	export_jobs.py
	•	data/
	•	jobs.db
	•	cache/
	•	config/
	•	queries.json
	•	resume.txt
	•	ideal_job.txt
	•	README.md
	•	requirements.txt
	•	.env
	•	.env.example

⸻

Database Model (High Level)

raw_requests

Stores every API request/response
	•	id
	•	query_name
	•	query_params_json
	•	response_json
	•	requested_at

jobs

Stores normalized unique job entries
	•	id
	•	source_job_id
	•	title
	•	company
	•	location
	•	description
	•	apply_url
	•	date_posted
	•	normalized_hash
	•	first_seen_at
	•	last_seen_at

job_scores

Stores scoring results
	•	id
	•	job_id
	•	rule_score
	•	resume_embedding_score
	•	ideal_job_embedding_score
	•	total_score
	•	scoring_version
	•	scored_at

exports

Stores export runs
	•	id
	•	exported_at
	•	export_file_name

export_jobs

Join table for jobs included in each export
	•	id
	•	export_id
	•	job_id

⸻

Tech Stack
	•	Python
	•	SerpApi (Google Jobs)
	•	SQLite
	•	Ollama (for embeddings)
	•	requests / httpx
	•	openpyxl or pandas (for XLSX export)

⸻

Usage (Planned)

Run ingestion:

python scripts/ingest_jobs.py

Run export:

python scripts/export_jobs.py


⸻

Design Principles
	•	historical completeness: no data loss
	•	deterministic core: rules are explicit and inspectable
	•	embeddings as signal: similarity informs ranking
	•	modular architecture: ingestion, scoring, and export are decoupled
	•	cost-aware: minimize API usage through controlled queries

⸻

Purpose

This project exists to:
	•	eliminate manual job searching
	•	prioritize high-fit opportunities
	•	create a repeatable, optimized job search workflow

It also serves as a portfolio project demonstrating:
	•	API integration
	•	data pipeline design
	•	embedding-based similarity systems
	•	practical automation for real-world use

⸻

:::