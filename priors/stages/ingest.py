"""Stage 1 — ingest: pull candidate articles from configured sources.

Phase 0: returns fixture data so the pipeline runs end-to-end.
Phase 1: RSS feeds (feedparser) + news API (GNews free tier) + targeted search
for the owner's custom topics. Dedup against the articles table happens here.
"""

from __future__ import annotations

from priors.config import Config
from priors.models import Article
from priors.sample_data import SAMPLE_ARTICLES


def run(config: Config, *, sample: bool = False) -> list[Article]:
    if sample:
        return list(SAMPLE_ARTICLES)
    raise NotImplementedError(
        "Live ingestion arrives in Phase 1. Run with sample data: `priors preview`."
    )
