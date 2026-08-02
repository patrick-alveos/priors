"""Stage 2 — cluster: group articles into stories, rank by significance.

One LLM call: the model sees compact article records and returns groups of
article IDs per story, capped per section, ranked for a decision-maker
audience. Output is post-validated in code — unknown IDs are dropped, so a
hallucinated ID can never pull in a nonexistent article.
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from priors.config import Config
from priors.llm import LLM
from priors.models import Article, Story

SYSTEM = """You are the news editor of a weekly briefing for decision makers \
(founders, executives, investors). You receive candidate articles from the past \
7 days and must select and cluster them into stories.

Rules:
- One story = one real-world event or development. Articles from different \
outlets covering the same event belong in the same story.
- Assign each story to exactly one of the allowed sections.
- Select at most the given maximum stories per section; choose by significance \
for decision makers (macro impact, industry shifts, second-order effects), not \
by volume of coverage.
- Use only article IDs from the provided list. Never invent IDs.
- Prefer stories with multiple independent sources.
- Skip celebrity news, sports results, and one-off crime stories unless they \
have clear business or policy implications.
- Sections that list specific topics are strict: assign a story there ONLY if \
it is squarely about one of those topics. A loosely related story belongs in a \
general section instead, and it is normal for a topical section to have fewer \
stories than the maximum — or none at all."""


class ClusterGroup(BaseModel):
    section: str
    article_ids: list[str]
    rank: int  # 1 = most significant within its section


class ClusterResult(BaseModel):
    stories: list[ClusterGroup]


def _fallback_story(config: Config, articles: list[Article]) -> list[Story]:
    """Degenerate grouping if the LLM output is unusable: one story per section anchor."""
    stories = []
    for section in config.enabled_sections:
        arts = [a for a in articles if a.section_hint == section.key]
        if arts:
            stories.append(
                Story(section=section.key, headline=arts[0].title, what_happened="",
                      potential_implications="", articles=arts[:5])
            )
    return stories


def apply_clusters(
    config: Config, articles: list[Article], result: ClusterResult
) -> list[Story]:
    """Turn validated cluster groups into proto-stories (editorial fields come from `write`)."""
    by_id = {a.id: a for a in articles}
    allowed_sections = {s.key for s in config.enabled_sections}
    max_per_section = config.llm.max_stories_per_section
    per_section_count: dict[str, int] = {}
    stories: list[Story] = []
    used_ids: set[str] = set()

    for group in sorted(result.stories, key=lambda g: g.rank):
        if group.section not in allowed_sections:
            continue
        members = [by_id[i] for i in group.article_ids if i in by_id and i not in used_ids]
        if not members:
            continue
        if per_section_count.get(group.section, 0) >= max_per_section:
            continue
        per_section_count[group.section] = per_section_count.get(group.section, 0) + 1
        used_ids.update(a.id for a in members)
        anchor = members[0]
        stories.append(
            Story(
                section=group.section,
                headline=anchor.title,
                what_happened=anchor.summary or "",
                potential_implications="",
                articles=members,
            )
        )
    return stories


def run(
    config: Config, articles: list[Article], *, llm: LLM | None = None
) -> list[Story]:
    if llm is None:
        # Sample/offline path (Phase 0 behavior): trivial grouping by section hint.
        result = ClusterResult(
            stories=[
                ClusterGroup(section=key, article_ids=[a.id for a in arts], rank=i + 1)
                for i, (key, arts) in enumerate(_group_by_hint(config, articles).items())
            ]
        )
        return apply_clusters(config, articles, result)

    if not articles:
        return []
    records = [
        {
            "id": a.id,
            "title": a.title,
            "source": a.source,
            "section_hint": a.section_hint,
            "summary": (a.summary or "")[:300],
        }
        for a in articles
    ]
    sections = [
        {"key": s.key, "title": s.title, **({"topics": s.topics} if s.topics else {})}
        for s in config.enabled_sections
    ]
    user = (
        f"Allowed sections (JSON):\n{json.dumps(sections, ensure_ascii=False)}\n"
        f"Maximum stories per section: {config.llm.max_stories_per_section}\n\n"
        f"Candidate articles (JSON):\n{json.dumps(records, ensure_ascii=False)}"
    )
    try:
        result = llm.parse(
            system=SYSTEM, user=user, output_format=ClusterResult, max_tokens=8192
        )
    except Exception as e:  # noqa: BLE001 — a bad clustering must not kill the weekly run
        print(f"  [cluster] WARN: LLM clustering failed ({e}); falling back to naive grouping")
        return _fallback_story(config, articles)
    stories = apply_clusters(config, articles, result)
    print(f"  [cluster] {len(articles)} articles -> {len(stories)} stories")
    return stories


def _group_by_hint(config: Config, articles: list[Article]) -> dict[str, list[Article]]:
    enabled = {s.key for s in config.enabled_sections}
    grouped: dict[str, list[Article]] = {}
    for a in articles:
        key = a.section_hint or "scitech"
        if key in enabled:
            grouped.setdefault(key, []).append(a)
    return grouped
