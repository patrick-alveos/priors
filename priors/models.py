"""Data model for the pipeline.

Every stage consumes and produces these models, serialized as JSON artifacts in
data/artifacts/ so each stage can be run and inspected independently.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class Article(BaseModel):
    """A candidate article pulled by `ingest`."""

    id: str  # stable hash of the normalized URL
    url: str
    title: str
    source: str  # outlet name, e.g. "Financial Times"
    published_at: datetime | None = None
    summary: str | None = None
    image_url: str | None = None
    section_hint: str | None = None  # section key the ingester thinks this belongs to


class Take(BaseModel):
    """One attributed perspective on a story. Never invented — always sourced."""

    source: str
    source_url: str
    text: str


class Forecast(BaseModel):
    """A prediction-market probability attached to a story."""

    platform: str  # polymarket | kalshi | metaculus
    question: str
    probability: float  # 0..1
    delta_pp: float | None = None  # week-over-week change in percentage points
    url: str


class StoryImage(BaseModel):
    """Image for a story per the sourcing rules (og:image with attribution,
    else a locally generated typographic card)."""

    kind: str  # "og" | "card"
    url: str | None = None  # for kind == "og"
    attribution: str | None = None
    attribution_url: str | None = None


class Story(BaseModel):
    """One deduplicated story in its final editorial form."""

    section: str  # section key
    headline: str
    what_happened: str
    why_it_matters: str
    takes: list[Take] = []
    forecasts: list[Forecast] = []
    no_market_note: bool = False  # True → render "No liquid prediction market covers this yet"
    image: StoryImage | None = None
    articles: list[Article] = []  # underlying sources, for link validation and attribution


class MarketMove(BaseModel):
    """One entry in the 'Markets moved' footer."""

    platform: str
    question: str
    probability: float
    delta_pp: float
    url: str


class IssueSection(BaseModel):
    key: str
    title: str
    stories: list[Story] = []


class Issue(BaseModel):
    """A complete weekly issue, ready to render."""

    week: str  # ISO year-week, e.g. "2026-W31"
    period_start: date
    period_end: date
    digest_name: str
    tagline: str
    accent_color: str
    exec_summary: list[str] = []  # "If you only read one thing" bullets
    sections: list[IssueSection] = []
    markets_moved: list[MarketMove] = []
