"""Stage 1 — ingest: pull candidate articles from configured sources.

Live sources: RSS feeds (keyless) + GNews top headlines (free-tier key,
optional — the pipeline degrades gracefully to RSS-only without it).
Articles are normalized, hashed by URL for stable IDs, filtered to the last
7 days, and deduplicated against articles used in past issues.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import httpx

from priors.config import Config
from priors.models import Article
from priors.sample_data import SAMPLE_ARTICLES

# GNews category → section key for the three standard sections.
GNEWS_CATEGORIES = {
    "world": "politics",
    "business": "business",
    "science": "scitech",
    "technology": "scitech",
}

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "CMP"}


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parsed.query) if k not in TRACKING_PARAMS]
    )
    return urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", query, "")
    )


def article_id(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:16]


def _fetch_rss(config: Config) -> list[Article]:
    articles: list[Article] = []
    for feed in config.sources.rss:
        parsed = feedparser.parse(feed.url)
        if parsed.bozo and not parsed.entries:
            print(f"  [ingest] WARN: could not parse feed {feed.url}")
            continue
        source = parsed.feed.get("title", urlparse(feed.url).netloc)
        for entry in parsed.entries:
            link = entry.get("link")
            title = entry.get("title")
            if not link or not title:
                continue
            published = None
            for key in ("published_parsed", "updated_parsed"):
                if entry.get(key):
                    published = datetime.fromtimestamp(time.mktime(entry[key]), tz=UTC)
                    break
            image_url = None
            for media in entry.get("media_thumbnail", []) or entry.get("media_content", []):
                if media.get("url"):
                    image_url = media["url"]
                    break
            articles.append(
                Article(
                    id=article_id(link),
                    url=link,
                    title=title.strip(),
                    source=source,
                    published_at=published,
                    summary=(entry.get("summary") or "")[:1000] or None,
                    image_url=image_url,
                    section_hint=feed.section,
                )
            )
    return articles


def _fetch_gnews(config: Config) -> list[Article]:
    api_key = os.environ.get("GNEWS_API_KEY")
    if not api_key or not config.sources.news_api.enabled:
        return []
    articles: list[Article] = []
    with httpx.Client(timeout=15) as client:
        for category, section in GNEWS_CATEGORIES.items():
            try:
                resp = client.get(
                    "https://gnews.io/api/v4/top-headlines",
                    params={"category": category, "lang": "en", "max": 10, "apikey": api_key},
                )
                resp.raise_for_status()
            except httpx.HTTPError as e:
                print(f"  [ingest] WARN: GNews {category} failed: {e}")
                continue
            for item in resp.json().get("articles", []):
                if not item.get("url") or not item.get("title"):
                    continue
                published = None
                if item.get("publishedAt"):
                    try:
                        published = datetime.fromisoformat(
                            item["publishedAt"].replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass
                articles.append(
                    Article(
                        id=article_id(item["url"]),
                        url=item["url"],
                        title=item["title"].strip(),
                        source=(item.get("source") or {}).get("name", "GNews"),
                        published_at=published,
                        summary=(item.get("description") or "")[:1000] or None,
                        image_url=item.get("image"),
                        section_hint=section,
                    )
                )
    return articles


def filter_articles(
    articles: list[Article],
    *,
    used_ids: set[str],
    now: datetime | None = None,
    window_days: int = 7,
) -> list[Article]:
    """Dedupe by ID, drop previously-used articles, keep the 7-day window."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=window_days)
    seen: set[str] = set()
    kept: list[Article] = []
    for a in articles:
        if a.id in seen or a.id in used_ids:
            continue
        if a.published_at is not None and a.published_at < cutoff:
            continue
        seen.add(a.id)
        kept.append(a)
    return kept


def run(
    config: Config, *, sample: bool = False, conn: sqlite3.Connection | None = None
) -> list[Article]:
    if sample:
        return list(SAMPLE_ARTICLES)
    raw = _fetch_rss(config) + _fetch_gnews(config)
    used = set()
    if conn is not None:
        from priors import db

        used = db.used_article_ids(conn)
    articles = filter_articles(raw, used_ids=used)
    if conn is not None:
        from priors import db

        db.record_articles(conn, articles)
    print(f"  [ingest] {len(raw)} fetched, {len(articles)} after dedup + 7-day filter")
    return articles
