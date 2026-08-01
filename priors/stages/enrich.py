"""Stage 3 — enrich: attach prediction-market data and images to stories.

Phase 0: attaches the sample typographic-card image; markets untouched.
Phase 2: Polymarket/Kalshi/Metaculus market matching + week-over-week deltas
from the market_snapshots table.
Phase 1 (images): og:image extraction with attribution, typographic-card
fallback, compression per the image rules.
"""

from __future__ import annotations

from priors.config import Config
from priors.models import Story
from priors.sample_data import SAMPLE_IMAGE


def run(config: Config, stories: list[Story], *, sample: bool = False) -> list[Story]:
    for story in stories:
        if story.image is None:
            story.image = SAMPLE_IMAGE.model_copy()
    return stories
