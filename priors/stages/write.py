"""Stage 4 — write: compose the issue with the LLM (structured output).

One call per story. Editorial rules are enforced twice: in the prompt, and
again in code — a take whose source_url is not one of the story's actual
article URLs is dropped, so an invented attribution can never reach the email.

Markets are attached BEFORE this stage runs, so the model can weave real
probability moves into the implications.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from pydantic import BaseModel

from priors.config import Config
from priors.llm import LLM
from priors.models import Issue, IssueSection, Story, Take
from priors.sample_data import SAMPLE_EDITORIAL, SAMPLE_MARKETS_MOVED

STORY_SYSTEM = """You write one story for a weekly briefing read slowly on a \
Sunday morning by decision makers (founders, executives, investors).

Voice: think Scott Alexander — conversational but precise, epistemically \
honest, comfortable with numbers and probabilities, quietly funny when the \
material allows it. You reason in public: say what's known, what's uncertain, \
and what would change your mind. Never breathless, never hype ("game-changing", \
"revolutionary" are banned). Plain words over jargon.

Fields:
- headline: rewritten in your own words, never copied from an outlet. \
Informative first, wry second. Sentence case: capitalize the first word and \
proper nouns as in normal prose ("Apple warns of chip shortages ahead of \
holidays") — never Title Case, never all-lowercase.
- what_happened: 2-4 sentences, strictly factual, only events from the \
provided articles. Paraphrase; direct quotes max 10 words.
- potential_implications: how a thoughtful reader should update. Second- and \
third-order effects, base rates where relevant, honest uncertainty ("this \
could just as easily be X"). If prediction markets are provided for this \
story, anchor the update in them — e.g. "markets moved the odds of X from \
52% to 61% this week, which suggests...". Never invent market numbers; use \
only the ones provided. If none are provided, reason qualitatively.
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
    potential_implications: str
    takes: list[TakeDraft]


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
    market_records = [
        {
            "question": f.question,
            "probability_pct": round(f.probability * 100),
            "change_pp": f.delta_pp,
            "change_measured": f.delta_label,
        }
        for f in story.forecasts
    ]
    user = f"Articles for this story (JSON):\n{json.dumps(records, ensure_ascii=False)}"
    if market_records:
        user += (
            f"\n\nPrediction markets matched to this story (JSON):\n"
            f"{json.dumps(market_records, ensure_ascii=False)}"
        )
    draft = llm.parse(
        system=STORY_SYSTEM,
        user=user,
        output_format=StoryDraft,
        max_tokens=2048,
    )
    story.headline = draft.headline
    story.what_happened = draft.what_happened
    story.potential_implications = draft.potential_implications
    story.takes = validate_takes(story, draft.takes)
    dropped = len(draft.takes) - len(story.takes)
    if dropped:
        print(f"  [write] dropped {dropped} unattributable take(s) from '{story.headline[:50]}'")


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
        markets_moved = []  # filled by the pipeline from market snapshots

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
        sections=sections,
        markets_moved=markets_moved,
    )
