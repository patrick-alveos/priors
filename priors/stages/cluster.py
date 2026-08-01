"""Stage 2 — cluster: group articles into stories, rank by significance.

Phase 0: trivial grouping by section_hint, one story per unique headline topic.
Phase 1: embedding/LLM-based clustering so 15 outlets covering one event become
one story, ranked for the owner's profile.
"""

from __future__ import annotations

from priors.config import Config
from priors.models import Article, Story


def run(config: Config, articles: list[Article]) -> list[Story]:
    """Group articles into proto-stories (editorial fields filled by `write`)."""
    enabled_keys = {s.key for s in config.enabled_sections}
    stories: list[Story] = []
    # Phase 0 stub: the first article of each section anchors a story; later
    # articles in the same section attach as additional sources for takes.
    by_section: dict[str, list[Article]] = {}
    for a in articles:
        key = a.section_hint or "scitech"
        if key in enabled_keys:
            by_section.setdefault(key, []).append(a)
    for key, arts in by_section.items():
        anchor = arts[0]
        stories.append(
            Story(
                section=key,
                headline=anchor.title,
                what_happened=anchor.summary or "",
                why_it_matters="",
                articles=arts,
            )
        )
    return stories
