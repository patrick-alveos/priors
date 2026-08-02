"""Link validation — no URL reaches the email unless it resolves.

Editorial quality bar from the brief: every factual claim traceable to a
linked source, no hallucinated URLs. Anything that fails is removed (takes)
or downgraded (images) rather than shipped broken.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from priors.models import Issue, StoryImage

# Browser-like UA: several sites (e.g. kalshi.com) reject bot-style agents.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}


def url_resolves(client: httpx.Client, url: str) -> bool:
    try:
        resp = client.head(url, timeout=10, follow_redirects=True)
        if resp.status_code in (403, 405):  # some sites reject HEAD; retry with GET
            resp = client.get(url, timeout=10, follow_redirects=True)
        # 429 = alive but rate-limiting our checker; that's not a broken link.
        return resp.status_code < 400 or resp.status_code == 429
    except httpx.HTTPError:
        return False


def validate_issue(issue: Issue, check: Callable[[str], bool] | None = None) -> list[str]:
    """Validate every outbound URL in the issue; mutate the issue to remove failures.

    Returns a list of removed/downgraded URL descriptions for logging.
    """
    if check is None:
        client = httpx.Client(headers=HEADERS)
        cache: dict[str, bool] = {}

        def check(url: str) -> bool:  # noqa: PLR0911
            if url not in cache:
                cache[url] = url_resolves(client, url)
            return cache[url]

    removed: list[str] = []
    for section in issue.sections:
        for story in section.stories:
            kept_takes = []
            for take in story.takes:
                if check(take.source_url):
                    kept_takes.append(take)
                else:
                    removed.append(f"take link {take.source_url}")
            story.takes = kept_takes

            kept_forecasts = []
            for forecast in story.forecasts:
                if check(forecast.url):
                    kept_forecasts.append(forecast)
                else:
                    removed.append(f"forecast link {forecast.url}")
            story.forecasts = kept_forecasts

            if story.image and story.image.kind == "og":
                image_ok = story.image.url and check(story.image.url)
                attr_ok = story.image.attribution_url and check(story.image.attribution_url)
                if not (image_ok and attr_ok):
                    removed.append(f"image {story.image.url}")
                    story.image = StoryImage(kind="card")

    kept_markets = []
    for market in issue.markets_moved:
        if check(market.url):
            kept_markets.append(market)
        else:
            removed.append(f"market link {market.url}")
    issue.markets_moved = kept_markets

    if issue.human_story is not None:
        if not check(issue.human_story.source_url):
            removed.append(f"human story link {issue.human_story.source_url}")
            issue.human_story = None
        elif issue.human_story.image and issue.human_story.image.url:
            if not check(issue.human_story.image.url):
                removed.append(f"human story image {issue.human_story.image.url}")
                issue.human_story.image = None

    if issue.photo is not None and not (
        check(issue.photo.image_url) and check(issue.photo.link)
    ):
        removed.append(f"photo of the week {issue.photo.image_url}")
        issue.photo = None
    return removed
