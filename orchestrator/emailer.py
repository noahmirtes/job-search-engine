"""Email delivery for orchestrator profile runs."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from orchestrator.models import EmailResult, PipelineResult, ProfileConfig, SmtpConfig


def send_profile_email(
    *,
    profile: ProfileConfig,
    smtp: SmtpConfig,
    pipeline_result: PipelineResult,
) -> EmailResult:
    """Send report email, optional no-new email, or skip."""
    if pipeline_result.new_count > 0:
        subject = f"[{profile.id}] Job report: {pipeline_result.new_count} new jobs"
        body = (
            f"Profile: {profile.id}\n"
            f"New jobs in report: {pipeline_result.new_count}\n"
            f"Scored jobs in 'all' tab: {pipeline_result.all_count}\n"
            f"Pages fetched: {pipeline_result.pages_fetched}\n"
            f"Jobs upserted this run: {pipeline_result.jobs_upserted}\n"
            f"Jobs scored ok this run: {pipeline_result.jobs_scored_ok}\n"
        )
        try:
            _send_email(
                smtp=smtp,
                recipients=profile.recipients,
                subject=subject,
                body=body,
                attachment_path=pipeline_result.report_path,
            )
            return EmailResult(status="sent")
        except Exception as exc:
            return EmailResult(status="failed", error=_trim_error(str(exc)))

    if profile.send_no_new_email:
        subject = f"[{profile.id}] Job report: no new jobs"
        body = (
            f"Profile: {profile.id}\n"
            "No new jobs passed report criteria for this run.\n"
            f"Report generated at: {pipeline_result.report_path.name}\n"
        )
        try:
            _send_email(
                smtp=smtp,
                recipients=profile.recipients,
                subject=subject,
                body=body,
                attachment_path=None,
            )
            return EmailResult(status="sent")
        except Exception as exc:
            return EmailResult(status="failed", error=_trim_error(str(exc)))

    return EmailResult(status="skipped")


def _send_email(
    *,
    smtp: SmtpConfig,
    recipients: list[str],
    subject: str,
    body: str,
    attachment_path: Path | None,
) -> None:
    """Send one SMTP email with optional XLSX attachment."""
    if not recipients:
        raise ValueError("Profile recipients list is empty.")

    username = os.getenv("ORCH_SMTP_USERNAME", "").strip()
    password = os.getenv("ORCH_SMTP_APP_PASSWORD", "").strip()
    if not username:
        raise ValueError("Missing ORCH_SMTP_USERNAME in environment.")
    if not password:
        raise ValueError("Missing ORCH_SMTP_APP_PASSWORD in environment.")

    message = EmailMessage()
    message["From"] = smtp.sender_email
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)

    if attachment_path is not None:
        data = attachment_path.read_bytes()
        message.add_attachment(
            data,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=attachment_path.name,
        )

    with smtplib.SMTP(host=smtp.host, port=smtp.port, timeout=30) as client:
        client.ehlo()
        client.starttls()
        client.ehlo()
        client.login(username, password)
        client.send_message(message)


def _trim_error(message: str) -> str:
    """Trim long error messages for state/status output."""
    text = message.strip() or "Unknown email error."
    return text[:4000]
