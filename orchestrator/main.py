"""Simplified orchestrator entrypoint for personal multi-profile runs."""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from orchestrator.emailer import send_profile_email
from orchestrator.models import (
    OrchestratorConfig,
    ProfileConfig,
    ProfilePaths,
    SmtpConfig,
)
from orchestrator.pipeline import run_profile_pipeline

ORCHESTRATOR_DIR = Path(__file__).resolve().parent
PROFILES_PATH = ORCHESTRATOR_DIR / "profiles.json"
STATE_PATH = ORCHESTRATOR_DIR / "state.json"


def main() -> None:
    """Run due profiles with profile-level failure isolation."""
    config = _load_orchestrator_config(PROFILES_PATH)
    state = _load_state(STATE_PATH)
    now_utc = datetime.now(UTC)

    due_count = 0
    ran_count = 0
    failed_count = 0

    for profile in config.profiles:
        profile_state = _ensure_profile_state(state, profile.id)

        if not profile.enabled:
            print(f"[{profile.id}] disabled; skipping.")
            continue

        if not _is_due(profile, profile_state, now_utc):
            profile_state["last_run_status"] = "skipped_not_due"
            profile_state["last_error"] = None
            _write_state_atomic(STATE_PATH, state)
            print(f"[{profile.id}] not due; skipping.")
            continue

        due_count += 1
        ran_count += 1
        print(f"[{profile.id}] running search -> scoring -> report")

        try:
            result = run_profile_pipeline(profile)
            run_stamp = _utc_now_iso()
            profile_state["last_search_at"] = run_stamp
            profile_state["last_report_at"] = run_stamp

            email_result = send_profile_email(
                profile=profile,
                smtp=config.smtp,
                pipeline_result=result,
            )
            if email_result.status == "failed":
                failed_count += 1
                profile_state["last_run_status"] = "email_failed"
                profile_state["last_error"] = email_result.error
            else:
                if email_result.status == "sent":
                    profile_state["last_email_at"] = _utc_now_iso()
                profile_state["last_run_status"] = "ok"
                profile_state["last_error"] = None

            print(
                f"[{profile.id}] pages={result.pages_fetched}, "
                f"jobs_upserted={result.jobs_upserted}, "
                f"scored_ok={result.jobs_scored_ok}, "
                f"report_new={result.new_count}, "
                f"email={email_result.status}"
            )
        except Exception as exc:
            failed_count += 1
            profile_state["last_run_status"] = "failed"
            profile_state["last_error"] = _trim_error(str(exc))
            print(f"[{profile.id}] failed: {profile_state['last_error']}")
        finally:
            _write_state_atomic(STATE_PATH, state)

    print(f"Orchestrator summary: due={due_count}, ran={ran_count}, failed={failed_count}")


def _load_orchestrator_config(config_path: Path) -> OrchestratorConfig:
    """Load and validate orchestrator/profiles.json."""
    payload = _read_json_object(config_path, "profiles.json")

    smtp_payload = payload.get("smtp")
    if not isinstance(smtp_payload, dict):
        raise ValueError("profiles.json must include a top-level 'smtp' object.")

    sender_email = _required_str(smtp_payload, "sender_email", context="smtp")
    host = _required_str(smtp_payload, "host", context="smtp")
    port = smtp_payload.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or port <= 0:
        raise ValueError("profiles.json smtp.port must be a positive integer.")

    profiles_payload = payload.get("profiles")
    if not isinstance(profiles_payload, list):
        raise ValueError("profiles.json must include a top-level 'profiles' array.")

    profiles: list[ProfileConfig] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(profiles_payload):
        profiles.append(_parse_profile(item, index=index, seen_ids=seen_ids))

    return OrchestratorConfig(
        smtp=SmtpConfig(sender_email=sender_email, host=host, port=port),
        profiles=profiles,
    )


def _parse_profile(payload: Any, *, index: int, seen_ids: set[str]) -> ProfileConfig:
    """Validate and parse one profile object from config."""
    if not isinstance(payload, dict):
        raise ValueError(f"profiles.json profiles[{index}] must be an object.")

    profile_id = _required_str(payload, "id", context=f"profiles[{index}]")
    if profile_id in seen_ids:
        raise ValueError(f"Duplicate profile id found: '{profile_id}'.")
    seen_ids.add(profile_id)

    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError(f"profiles[{index}].enabled must be boolean.")

    search_every_days = payload.get("search_every_days")
    if isinstance(search_every_days, bool) or not isinstance(search_every_days, (int, float)):
        raise ValueError(f"profiles[{index}].search_every_days must be numeric.")
    search_every_days = float(search_every_days)
    if not math.isfinite(search_every_days) or search_every_days <= 0:
        raise ValueError(f"profiles[{index}].search_every_days must be > 0.")

    recipients = payload.get("recipients")
    if not isinstance(recipients, list) or not recipients:
        raise ValueError(f"profiles[{index}].recipients must be a non-empty array.")
    normalized_recipients = []
    for value in recipients:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"profiles[{index}].recipients entries must be non-empty strings.")
        normalized_recipients.append(value.strip())

    send_no_new_email = payload.get("send_no_new_email")
    if not isinstance(send_no_new_email, bool):
        raise ValueError(f"profiles[{index}].send_no_new_email must be boolean.")

    paths_payload = payload.get("paths")
    if not isinstance(paths_payload, dict):
        raise ValueError(f"profiles[{index}].paths must be an object.")

    paths = ProfilePaths(
        db_path=_resolve_path(_required_str(paths_payload, "db_path", context="paths")),
        queries_path=_resolve_path(_required_str(paths_payload, "queries_path", context="paths")),
        scoring_path=_resolve_path(_required_str(paths_payload, "scoring_path", context="paths")),
        resume_path=_resolve_path(_required_str(paths_payload, "resume_path", context="paths")),
        ideal_job_path=_resolve_path(_required_str(paths_payload, "ideal_job_path", context="paths")),
        env_path=_resolve_path(_required_str(paths_payload, "env_path", context="paths")),
        report_export_dir=_resolve_path(
            _required_str(paths_payload, "report_export_dir", context="paths")
        ),
        log_path=_optional_path(paths_payload, "log_path"),
    )

    return ProfileConfig(
        id=profile_id,
        enabled=enabled,
        search_every_days=search_every_days,
        recipients=normalized_recipients,
        send_no_new_email=send_no_new_email,
        paths=paths,
    )


def _required_str(payload: dict[str, Any], key: str, *, context: str) -> str:
    """Read required non-empty string values from JSON objects."""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"profiles.json {context}.{key} must be a non-empty string.")
    return value.strip()


def _optional_path(payload: dict[str, Any], key: str) -> Path | None:
    """Resolve optional path when provided."""
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"profiles.json paths.{key} must be a non-empty string when provided.")
    return _resolve_path(value.strip())


def _resolve_path(raw_path: str) -> Path:
    """Resolve relative paths against project root."""
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _load_state(path: Path) -> dict[str, Any]:
    """Load state.json and recover to defaults on malformed content."""
    if not path.exists():
        return {"profiles": {}}

    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"profiles": {}}

    if not isinstance(payload, dict):
        return {"profiles": {}}
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict):
        return {"profiles": {}}
    return {"profiles": profiles}


def _ensure_profile_state(state: dict[str, Any], profile_id: str) -> dict[str, Any]:
    """Ensure expected state keys exist for one profile."""
    profiles = state.setdefault("profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
        state["profiles"] = profiles

    entry = profiles.get(profile_id)
    if not isinstance(entry, dict):
        entry = {}

    entry.setdefault("last_search_at", None)
    entry.setdefault("last_report_at", None)
    entry.setdefault("last_email_at", None)
    entry.setdefault("last_run_status", None)
    entry.setdefault("last_error", None)

    profiles[profile_id] = entry
    return entry


def _is_due(profile: ProfileConfig, profile_state: dict[str, Any], now_utc: datetime) -> bool:
    """Return True when a profile should run based on last_search_at cadence."""
    last_search_at = _parse_iso_utc(profile_state.get("last_search_at"))
    if last_search_at is None:
        return True
    return now_utc >= (last_search_at + timedelta(days=profile.search_every_days))


def _parse_iso_utc(value: Any) -> datetime | None:
    """Parse stored state timestamp to UTC datetime."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _write_state_atomic(path: Path, state: dict[str, Any]) -> None:
    """Atomically write state.json to reduce corruption risk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, path)


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    """Load a JSON file that must contain an object."""
    if not path.exists():
        raise FileNotFoundError(f"Missing {label}: {path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object.")
    return payload


def _trim_error(message: str) -> str:
    """Trim long errors before persisting."""
    text = message.strip() or "Unknown error."
    return text[:4000]


def _utc_now_iso() -> str:
    """UTC ISO timestamp used for state updates."""
    return datetime.now(UTC).isoformat(timespec="seconds")


if __name__ == "__main__":
    main()
