"""Stage 3 — enrich: attach images (and, in Phase 2, prediction markets).

Image rules from the brief, in order of preference:
1. The publisher's og:image from a linked source article, with attribution.
2. A typographic card (rendered as HTML by the email template) — zero
   copyright risk.
Never hotlink without attribution; never use AI-generated imagery.
"""

from __future__ import annotations

import re

import httpx

from priors.config import Config
from priors.models import Story, StoryImage

OG_IMAGE_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image["\']',
    re.IGNORECASE,
)

CARD = StoryImage(kind="card")


def _find_og_image(html: str) -> str | None:
    match = OG_IMAGE_RE.search(html)
    if not match:
        return None
    url = match.group(1) or match.group(2)
    return url if url and url.startswith("http") else None


def fetch_og_image(client: httpx.Client, url: str) -> str | None:
    try:
        resp = client.get(url, timeout=10, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    # Only scan the head-ish portion; og tags live early in the document.
    return _find_og_image(resp.text[:200_000])


# Known low-resolution URL patterns → their higher-resolution variants.
_UPSCALE_PATTERNS = [
    ("ichef.bbci.co.uk/ace/standard/240/", "ichef.bbci.co.uk/ace/standard/976/"),
    ("ichef.bbci.co.uk/ace/standard/480/", "ichef.bbci.co.uk/ace/standard/976/"),
]


def upgrade_image_url(url: str) -> str:
    for low, high in _UPSCALE_PATTERNS:
        if low in url:
            return url.replace(low, high)
    return url


_JUNK_IMAGE_RE = re.compile(r"favicon|apple-touch|/icons?/|logo|-\d{1,2}x\d{1,2}\.", re.IGNORECASE)


def usable_image(url: str | None) -> str | None:
    """Reject favicons/logos that sometimes masquerade as article images."""
    if url and not _JUNK_IMAGE_RE.search(url):
        return url
    return None


def run(config: Config, stories: list[Story], *, sample: bool = False) -> list[Story]:
    if sample:
        for story in stories:
            if story.image is None:
                story.image = CARD.model_copy()
        return stories

    headers = {"User-Agent": "Mozilla/5.0 (compatible; PriorsDigest/0.1)"}
    with httpx.Client(headers=headers) as client:
        for story in stories:
            image = None
            anchor = story.articles[0] if story.articles else None
            if anchor is not None:
                # Prefer the page's og:image — RSS thumbnails are often tiny.
                url = usable_image(fetch_og_image(client, anchor.url)) or usable_image(
                    anchor.image_url
                )
                if url:
                    image = StoryImage(
                        kind="og",
                        url=upgrade_image_url(url),
                        attribution=anchor.source,
                        attribution_url=anchor.url,
                    )
            story.image = image or CARD.model_copy()
    og_count = sum(1 for s in stories if s.image and s.image.kind == "og")
    print(f"  [enrich] images: {og_count} og:image, {len(stories) - og_count} typographic card")
    return stories
