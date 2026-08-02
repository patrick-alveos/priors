"""Issue extras: the Human Story of the Week and the Photo of the Week.

Human story: pulled from good-news feeds, one chosen and retold by the LLM.
Photo: Wikimedia Commons Picture of the Day — freely licensed, properly
attributed, reliably beautiful. Both close the issue on a warm note.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from pydantic import BaseModel

from priors.config import Config
from priors.llm import LLM
from priors.models import Article, HumanStory, PhotoOfWeek, StoryImage
from priors.stages.enrich import fetch_og_image
from priors.stages.ingest import filter_articles, parse_feed

WIKIMEDIA_FEED = "https://api.wikimedia.org/feed/v1/wikipedia/en/featured/{y}/{m:02d}/{d:02d}"
HEADERS = {"User-Agent": "PriorsDigest/0.1 (self-hosted weekly digest)"}


# --- human story -------------------------------------------------------------

HUMAN_SYSTEM = """You pick and retell the "Human story of the week" for a \
weekly briefing — one true story from the provided articles about a person \
helping another person, something that restores faith in humanity.

Rules:
- Choose ONE story: a concrete act of kindness, courage, or generosity between
  people. Not policy news, not fundraising totals, not institutional press
  releases — a person, a moment.
- Retell it in 3-5 sentences, warm but unsentimental. Let the facts carry the
  feeling; no moralizing coda, no "faith in humanity restored" phrasing.
- source and source_url must be the actual article you drew from — copy the
  URL exactly from the list.
- source_index is that article's index in the provided list."""


class HumanStoryDraft(BaseModel):
    headline: str
    text: str
    source_index: int


def fetch_human_candidates(config: Config) -> list[Article]:
    articles: list[Article] = []
    for url in config.extras.human_story.feeds:
        articles.extend(parse_feed(url))
    return filter_articles(articles, used_ids=set(), window_days=14)


def compose_human_story(
    llm: LLM, candidates: list[Article], client: httpx.Client | None = None
) -> HumanStory | None:
    if not candidates:
        return None
    records = [
        {"index": i, "title": a.title, "summary": (a.summary or "")[:400], "source": a.source}
        for i, a in enumerate(candidates[:30])
    ]
    import json

    try:
        draft = llm.parse(
            system=HUMAN_SYSTEM,
            user=f"Candidate articles (JSON):\n{json.dumps(records, ensure_ascii=False)}",
            output_format=HumanStoryDraft,
            max_tokens=1024,
        )
    except Exception as e:  # noqa: BLE001 — extras must never kill the issue
        print(f"  [extras] WARN: human story composition failed: {e}")
        return None
    if not 0 <= draft.source_index < len(candidates):
        return None
    article = candidates[draft.source_index]
    image = None
    if client is not None:
        image_url = article.image_url or fetch_og_image(client, article.url)
        if image_url:
            image = StoryImage(
                kind="og", url=image_url, attribution=article.source,
                attribution_url=article.url,
            )
    return HumanStory(
        headline=draft.headline,
        text=draft.text,
        source=article.source,
        source_url=article.url,
        image=image,
    )


# --- photo of the week -------------------------------------------------------


def fetch_photo_of_week(today: datetime | None = None) -> PhotoOfWeek | None:
    """Wikimedia's Picture of the Day; walks back a few days if today's is missing."""
    today = today or datetime.now(UTC)
    with httpx.Client(timeout=15, headers=HEADERS, follow_redirects=True) as client:
        for days_back in range(7):
            day = today - timedelta(days=days_back)
            url = WIKIMEDIA_FEED.format(y=day.year, m=day.month, d=day.day)
            try:
                resp = client.get(url)
                resp.raise_for_status()
            except httpx.HTTPError:
                continue
            image = resp.json().get("image")
            if not image:
                continue
            source = (image.get("image") or {}).get("source")
            thumb = (image.get("thumbnail") or {}).get("source")
            if not (source or thumb):
                continue
            artist = ((image.get("artist") or {}).get("text") or "Unknown photographer").strip()
            license_ = ((image.get("license") or {}).get("type") or "").strip()
            attribution = f"{artist} ({license_})" if license_ else artist
            description = ((image.get("description") or {}).get("text") or "").strip()
            return PhotoOfWeek(
                image_url=thumb or source,  # thumbnail is already email-friendly
                title=image.get("title", "Picture of the day").replace("File:", ""),
                description=description[:300] or None,
                attribution=attribution,
                link=image.get("file_page", "https://commons.wikimedia.org"),
            )
    print("  [extras] WARN: no Wikimedia picture of the day found")
    return None
