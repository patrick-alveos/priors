"""Built-in weekly scheduler — no cron dependency inside the container.

Sleeps until the next configured (day, time) in the owner's timezone, then runs
the pipeline. Deliberately boring: a loop with datetime math, no scheduling
library.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from priors.config import WEEKDAYS, Config


def next_run(config: Config, now: datetime | None = None) -> datetime:
    tz = ZoneInfo(config.owner.timezone)
    now = now.astimezone(tz) if now else datetime.now(tz)
    target_weekday = WEEKDAYS.index(config.schedule.day)
    hour, minute = (int(p) for p in config.schedule.time.split(":"))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    days_ahead = (target_weekday - now.weekday()) % 7
    candidate += timedelta(days=days_ahead)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def run_forever(config: Config) -> None:
    while True:
        target = next_run(config)
        wait = (target - datetime.now(ZoneInfo(config.owner.timezone))).total_seconds()
        print(f"[scheduler] Next run: {target.isoformat()} (sleeping {wait / 3600:.1f}h)")
        time.sleep(max(wait, 1))
        print("[scheduler] Triggering weekly run...")
        try:
            # Phase 1 wires this to the real pipeline; Phase 0 logs and continues.
            print("[scheduler] Pipeline not yet implemented (Phase 0 skeleton).")
        except Exception as e:  # noqa: BLE001 — a failed week must not kill the daemon
            print(f"[scheduler] Run failed: {e}")
