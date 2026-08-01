"""Stage 6 — deliver: send the issue via Resend to everyone in `subscribers`.

Resend is a deliberate choice: its Audiences/broadcast features make the future
hosted-newsletter phase a config change, not new infrastructure.

Phase 0: dry-run only — lists would-be recipients and points at the local HTML.
Phase 1: real Resend send with RESEND_API_KEY from .env.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from priors.config import Config
from priors.db import active_subscribers


def run(
    config: Config,
    conn: sqlite3.Connection,
    html_path: Path,
    *,
    dry_run: bool = True,
) -> list[str]:
    """Returns the list of recipient emails (sent to, or would send to)."""
    recipients = [row["email"] for row in active_subscribers(conn)]
    if dry_run:
        return recipients
    raise NotImplementedError(
        "Real email delivery arrives in Phase 1. Use --dry-run (or `priors preview`)."
    )
