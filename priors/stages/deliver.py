"""Stage 6 — deliver: send the issue via Resend to everyone in `subscribers`.

Resend is a deliberate choice: its Audiences/broadcast features make the future
hosted-newsletter phase a config change, not new infrastructure. One API call
per subscriber (individual sends — no recipient list leakage).
"""

from __future__ import annotations

import os
import sqlite3

import httpx

from priors.config import Config
from priors.db import active_subscribers

RESEND_API_URL = "https://api.resend.com/emails"


def build_subject(config: Config, period_end_str: str) -> str:
    return config.email.subject_template.format(
        name=config.digest.name, date=period_end_str
    )


def send_email(
    api_key: str, from_address: str, to: str, subject: str, html: str
) -> None:
    resp = httpx.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"from": from_address, "to": [to], "subject": subject, "html": html},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Resend rejected email to {to}: {resp.status_code} {resp.text}")


def run(
    config: Config,
    conn: sqlite3.Connection,
    html: str,
    subject: str,
    *,
    dry_run: bool = True,
) -> list[str]:
    """Send (or pretend to send) the issue. Returns recipient emails."""
    recipients = [row["email"] for row in active_subscribers(conn)]
    if dry_run:
        return recipients

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError(
            "RESEND_API_KEY is not set. Get one at https://resend.com/api-keys, "
            "add it to .env, and set email.from in config.yaml to a verified sender "
            "(onboarding@resend.dev works for sending to your own account email)."
        )
    if not config.email.from_address:
        raise RuntimeError("email.from is not set in config.yaml")

    for to in recipients:
        send_email(api_key, config.email.from_address, to, subject, html)
        print(f"  [deliver] sent to {to}")
    return recipients
