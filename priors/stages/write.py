"""Stage 4 — write: compose the issue with the LLM (structured output).

One call per story plus one for the executive summary. Editorial rules are
enforced twice: in the prompt, and again in code — a take whose source_url is
not one of the story's actual article URLs is dropped, so an invented
attribution can never reach the email.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from pydantic import BaseModel

from priors.config import Config
from priors.llm import LLM
from priors.models import Issue, IssueSection, Story, Take
from priors.sample_data import SAMPLE_EDITORIAL, SAMPLE_MARKETS_MOVED

STORY_SYSTEM = """You write one story for a weekly briefing for decision makers \
(founders, executives, investors). Tone: dry, precise, lightly witty — The \
Economist, not BuzzFeed. Never use hype words ("game-changing", "revolutionary", \
"groundbreaking").

Strict rules:
- headline: rewritten in your own words, never copied from an outlet.
- what_happened: 2-4 sentences, strictly factual, only events from the provided \
articles. Paraphrase; direct quotes max 10 words.
- why_it_matters: implications for a decision maker — second- and third-order \
effects, not a restatement of the news.
- takes: 2-3 distinct perspectives. Each take MUST be attributed to one of the \
provided articles: source = the outlet name, source_url = that article's exact \
URL, text = a paraphrase of that outlet's actual angle, phrased to follow the \
outlet name (e.g. "argues the collapse was choreographed."). Never invent a \
take, never attribute to a source not in the list, never use the same outlet \
twice within the story."""


class TakeDraft(BaseModel):
    source: str
    source_url: str
    text: str


class StoryDraft(BaseModel):
    headline: str
    what_happened: str
    why_it_matters: str
    takes: list[TakeDraft]


class ExecSummary(BaseModel):
    bullets: list[str]


def iso_week(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def validate_takes(story: Story, drafts: list[TakeDraft]) -> list[Take]:
    """Keep only takes attributable to a real article in this story; one per outlet."""
    valid_urls = {a.url for a in story.articles}
    seen_sources: set[str] = set()
    takes: list[Take] = []
    for draft in drafts:
        if draft.source_url not in valid_urls:
            continue
        key = draft.source.lower().strip()
        if key in seen_sources:
            continue
        seen_sources.add(key)
        takes.append(Take(source=draft.source, source_url=draft.source_url, text=draft.text))
    return takes[:3]


def _compose_story(llm: LLM, story: Story) -> None:
    records = [
        {
            "title": a.title,
            "source": a.source,
            "url": a.url,
            "published_at": a.published_at.isoformat() if a.published_at else None,
            "summary": a.summary,
        }
        for a in story.articles
    ]
    draft = llm.parse(
        system=STORY_SYSTEM,
        user=f"Articles for this story (JSON):\n{json.dumps(records, ensure_ascii=False)}",
        output_format=StoryDraft,
        max_tokens=2048,
    )
    story.headline = draft.headline
    story.what_happened = draft.what_happened
    story.why_it_matters = draft.why_it_matters
    story.takes = validate_takes(story, draft.takes)
    dropped = len(draft.takes) - len(story.takes)
    if dropped:
        print(f"  [write] dropped {dropped} unattributable take(s) from '{story.headline[:50]}'")


def _compose_exec_summary(llm: LLM, stories: list[Story]) -> list[str]:
    digest = [
        {"headline": s.headline, "why_it_matters": s.why_it_matters} for s in stories
    ]
    summary = llm.parse(
        system=(
            "Write the 'If you only read one thing' section of a weekly decision-maker "
            "briefing: 3-5 bullets, one per major story, each a single dry, information-"
            "dense sentence. No hype words. Only use the provided stories."
        ),
        user=json.dumps(digest, ensure_ascii=False),
        output_format=ExecSummary,
        max_tokens=1024,
    )
    return summary.bullets[:5]


def run(
    config: Config,
    stories: list[Story],
    *,
    sample: bool = False,
    today: date | None = None,
    llm: LLM | None = None,
) -> Issue:
    today = today or date.today()

    if sample:
        for story in stories:
            anchor_id = story.articles[0].id if story.articles else None
            editorial = SAMPLE_EDITORIAL.get(anchor_id or "", {})
            for field, value in editorial.items():
                setattr(story, field, value)
        exec_summary = [
            "[SAMPLE] Trade summit collapsed; markets now price tariff escalation at 62%.",
            "[SAMPLE] Chip guidance cut suggests the capex cycle is being repriced.",
            "[SAMPLE] Eight-minute net-energy fusion run reported; replication pending.",
            "[SAMPLE] European stress-tech category keeps getting funded (€12M Series A).",
        ]
        markets_moved = list(SAMPLE_MARKETS_MOVED)
    else:
        if llm is None:
            raise ValueError("Live composition requires an LLM instance")
        composed: list[Story] = []
        for story in stories:
            try:
                _compose_story(llm, story)
                composed.append(story)
            except Exception as e:  # noqa: BLE001 — one bad story must not kill the issue
                print(f"  [write] WARN: dropped story '{story.headline[:60]}': {e}")
        stories = composed
        exec_summary = _compose_exec_summary(llm, stories) if stories else []
        markets_moved = []  # Phase 2: prediction-market swings of the week

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
        exec_summary=exec_summary,
        sections=sections,
        markets_moved=markets_moved,
    )
