"""Stage 4 — write: compose the issue with the LLM (Claude, structured output).

Phase 0: fills stories from fixture editorial content and assembles an Issue —
no API calls, so `priors preview` works without any keys.
Phase 1: Anthropic API with a JSON schema per story, enforcing the editorial
template (headline / what happened / why it matters / takes), source diversity
caps, and the no-invented-takes rule. Token usage is logged per run.
"""

from __future__ import annotations

from datetime import date, timedelta

from priors.config import Config
from priors.models import Issue, IssueSection, Story
from priors.sample_data import SAMPLE_EDITORIAL, SAMPLE_MARKETS_MOVED


def iso_week(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def run(
    config: Config, stories: list[Story], *, sample: bool = False, today: date | None = None
) -> Issue:
    today = today or date.today()
    if not sample:
        raise NotImplementedError(
            "LLM composition arrives in Phase 1. Run with sample data: `priors preview`."
        )

    for story in stories:
        anchor_id = story.articles[0].id if story.articles else None
        editorial = SAMPLE_EDITORIAL.get(anchor_id or "", {})
        for field, value in editorial.items():
            setattr(story, field, value)

    sections = [
        IssueSection(
            key=s.key,
            title=s.title,
            stories=[st for st in stories if st.section == s.key],
        )
        for s in config.enabled_sections
    ]

    return Issue(
        week=iso_week(today),
        period_start=today - timedelta(days=7),
        period_end=today,
        digest_name=config.digest.name,
        tagline=config.digest.tagline,
        accent_color=config.digest.accent_color,
        exec_summary=[
            "[SAMPLE] Trade summit collapsed; markets now price tariff escalation at 62%.",
            "[SAMPLE] Chip guidance cut suggests the capex cycle is being repriced.",
            "[SAMPLE] Eight-minute net-energy fusion run reported; replication pending.",
            "[SAMPLE] European stress-tech category keeps getting funded (€12M Series A).",
        ],
        sections=sections,
        markets_moved=list(SAMPLE_MARKETS_MOVED),
    )
