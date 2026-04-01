"""Shared dataclasses for the simplified orchestrator flow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SmtpConfig:
    """Non-secret SMTP settings loaded from profiles.json."""

    sender_email: str
    host: str
    port: int


@dataclass(frozen=True)
class ProfilePaths:
    """Per-profile worker path mapping."""

    db_path: Path
    queries_path: Path
    scoring_path: Path
    resume_path: Path
    ideal_job_path: Path
    env_path: Path
    report_export_dir: Path
    log_path: Path | None = None


@dataclass(frozen=True)
class ProfileConfig:
    """Orchestrator configuration for one profile."""

    id: str
    enabled: bool
    search_every_days: float
    recipients: list[str]
    send_no_new_email: bool
    paths: ProfilePaths


@dataclass(frozen=True)
class OrchestratorConfig:
    """Top-level orchestrator config."""

    smtp: SmtpConfig
    profiles: list[ProfileConfig]


@dataclass(frozen=True)
class PipelineResult:
    """Compact summary of one completed profile pipeline run."""

    profile_id: str
    report_path: Path
    new_count: int
    all_count: int
    pages_fetched: int
    jobs_upserted: int
    jobs_scored_ok: int


@dataclass(frozen=True)
class EmailResult:
    """Result of the email send decision for one profile run."""

    status: str
    error: str | None = None
