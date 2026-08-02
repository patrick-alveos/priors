"""Prediction markets — Kalshi integration.

Pulls open Kalshi markets, matches them to the issue's stories with one LLM
call (post-validated: only real tickers survive), attaches probabilities with
deltas, and snapshots every fetched market so next week's issue can report
week-over-week moves. Forecasts are market prices, never our own guesses.
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel

from priors.llm import LLM
from priors.models import Forecast, MarketMove, Story

KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
MAX_MARKETS = 600  # snapshot + candidate-pool cap
MIN_VOLUME = 500  # contracts traded; ignore illiquid markets
MAX_EVENT_PAGES = 8  # 200 events/page

# News-relevant categories only — keeps NBA parlays out of a news digest.
ALLOWED_CATEGORIES = {
    "Politics",
    "Elections",
    "World",
    "Economics",
    "Financials",
    "Companies",
    "Science and Technology",
    "Climate and Weather",
    "Health",
}


@dataclass
class Market:
    ticker: str
    event_ticker: str
    title: str
    probability: float  # 0..1, from last trade price
    previous_probability: float | None  # previous day close, 0..1
    volume: int
    volume_24h: int
    url: str


def _auth_headers(method: str, path: str) -> dict[str, str]:
    """RSA-PSS signed headers for Kalshi. Returns {} if no credentials set."""
    key_id = os.environ.get("KALSHI_API_KEY_ID")
    private_key_pem = os.environ.get("KALSHI_PRIVATE_KEY")
    if not key_id or not private_key_pem:
        return {}
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}{method}{path}".encode()
    signature = key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
    }


def _float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def fetch_markets(limit: int = MAX_MARKETS) -> list[Market]:
    """Fetch open Kalshi markets in news-relevant categories, most liquid first.

    Uses the /events endpoint (nested markets) because only events carry a
    category — the flat /markets listing is dominated by unpriced sports
    parlays.
    """
    markets: list[Market] = []
    cursor = None
    with httpx.Client(timeout=20) as client:
        for _ in range(MAX_EVENT_PAGES):
            params: dict[str, str | int] = {
                "limit": 200,
                "status": "open",
                "with_nested_markets": "true",
            }
            if cursor:
                cursor = str(cursor)
                params["cursor"] = cursor
            resp = client.get(
                f"{KALSHI_API}/events",
                params=params,
                headers=_auth_headers("GET", "/trade-api/v2/events"),
            )
            resp.raise_for_status()
            data = resp.json()
            for event in data.get("events", []):
                if event.get("category") not in ALLOWED_CATEGORIES:
                    continue
                series = event.get("series_ticker") or event.get("event_ticker", "")
                for m in event.get("markets") or []:
                    last = _float(m.get("last_price_dollars"))
                    if not m.get("ticker") or not 0 < last < 1:
                        continue
                    prev = _float(m.get("previous_price_dollars")) or None
                    title = m.get("title") or ""
                    sub = m.get("yes_sub_title") or ""
                    if not title:
                        title = f"{event.get('title', series)} — {sub}" if sub else series
                    markets.append(
                        Market(
                            ticker=m["ticker"],
                            event_ticker=event.get("event_ticker", series),
                            title=title,
                            probability=last,
                            previous_probability=prev,
                            volume=int(_float(m.get("volume_fp"))),
                            volume_24h=int(_float(m.get("volume_24h_fp"))),
                            url=f"https://kalshi.com/markets/{series.lower()}",
                        )
                    )
            cursor = data.get("cursor")
            if not cursor or not data.get("events"):
                break
    liquid = [m for m in markets if m.volume >= MIN_VOLUME]
    if len(liquid) < 30:  # thin day — take what's most liquid rather than nothing
        liquid = sorted(markets, key=lambda m: m.volume, reverse=True)[:limit]
    liquid.sort(key=lambda m: m.volume, reverse=True)
    return liquid[:limit]


# --- snapshots & deltas ------------------------------------------------------


def snapshot_markets(conn: sqlite3.Connection, week: str, markets: list[Market]) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO market_snapshots"
        " (platform, market_id, question, probability, week, captured_at)"
        " VALUES ('kalshi', ?, ?, ?, ?, ?)",
        [
            (m.ticker, m.title, m.probability, week, datetime.now(UTC).isoformat())
            for m in markets
        ],
    )
    conn.commit()


def previous_snapshots(conn: sqlite3.Connection, current_week: str) -> dict[str, float]:
    """Probabilities from the most recent snapshot week before this one."""
    row = conn.execute(
        "SELECT week FROM market_snapshots WHERE week != ? ORDER BY captured_at DESC LIMIT 1",
        (current_week,),
    ).fetchone()
    if row is None:
        return {}
    rows = conn.execute(
        "SELECT market_id, probability FROM market_snapshots"
        " WHERE week = ? AND platform = 'kalshi'",
        (row["week"],),
    )
    return {r["market_id"]: r["probability"] for r in rows}


def _delta(market: Market, prior: dict[str, float]) -> tuple[float | None, str]:
    """Week-over-week delta when a prior snapshot exists, else day-over-day."""
    if market.ticker in prior:
        return round((market.probability - prior[market.ticker]) * 100, 1), "week-over-week"
    if market.previous_probability is not None:
        return round((market.probability - market.previous_probability) * 100, 1), "day-over-day"
    return None, "week-over-week"


# --- matching markets to stories --------------------------------------------

MATCH_SYSTEM = """You match prediction markets to news stories for a weekly \
briefing whose purpose is helping readers update their priors. For each story, \
select 0-2 Kalshi markets a thoughtful reader tracking that story would want \
to watch — the market's outcome should be clearly informative about the \
story's underlying situation, even if it doesn't name this week's exact event. \
(Example: an Israel-Saudi normalization market is a good match for a story \
about a Gaza ceasefire step; a "2028 presidential nominee" market is NOT a \
good match for a generic politics story.)

Rules:
- Only use tickers from the provided market list. Never invent tickers.
- The connection must be specific to this story's subject — same conflict, \
same company or person, same policy question, same technology race. Reject \
matches that would work equally well for any story in the section.
- When a market genuinely bears on the story's subject, include it — a \
reader prefers a relevant adjacent market over none. (A story about Apple's \
earnings matches an Apple-specific outcome market; a story about a Gaza \
ceasefire matches an Israel-related diplomacy market.)
- It's fine for a story to have no match when nothing specific exists.
- At most 2 markets per story."""


_STOPWORDS = frozenset(
    "the a an and or of in on to for with will be is are was at by from as its "
    "this that after over under new says say said week year years how what who".split()
)


def _keywords(text: str) -> set[str]:
    return {w for w in "".join(c if c.isalnum() else " " for c in text.lower()).split()
            if len(w) > 3 and w not in _STOPWORDS}


def candidate_markets(stories: list[Story], markets: list[Market]) -> list[Market]:
    """Blend three views so relevant markets reach the matcher: most-traded
    overall, most-traded today (newsy), and keyword overlap with the stories."""
    chosen: dict[str, Market] = {}
    by_total = sorted(markets, key=lambda m: m.volume, reverse=True)
    by_24h = sorted(markets, key=lambda m: m.volume_24h, reverse=True)
    for m in by_total[:100]:
        chosen[m.ticker] = m
    for m in by_24h[:60]:
        chosen[m.ticker] = m
    for story in stories:
        story_kw = _keywords(story.headline + " " + story.what_happened)
        scored = [
            (len(story_kw & _keywords(m.title)), m)
            for m in markets
        ]
        scored.sort(key=lambda t: (t[0], t[1].volume), reverse=True)
        # A single overlapping token is often the load-bearing one ("Apple",
        # "Israel") — include a few per story and let the LLM filter.
        for score, m in scored[:4]:
            if score >= 1:
                chosen[m.ticker] = m
    return list(chosen.values())


class StoryMatch(BaseModel):
    story_index: int
    tickers: list[str]


class MatchResult(BaseModel):
    matches: list[StoryMatch]


def match_markets(
    llm: LLM,
    stories: list[Story],
    markets: list[Market],
    prior: dict[str, float],
) -> None:
    """Attach Forecast objects to stories in place; set no_market_note honestly."""
    if not markets:
        for story in stories:
            story.no_market_note = True
        return
    candidates = candidate_markets(stories, markets)
    story_records = [
        {"index": i, "headline": s.headline, "summary": s.what_happened[:200]}
        for i, s in enumerate(stories)
    ]
    market_records = [
        {"ticker": m.ticker, "title": m.title, "price_pct": round(m.probability * 100)}
        for m in candidates
    ]
    user = (
        f"Stories (JSON):\n{json.dumps(story_records, ensure_ascii=False)}\n\n"
        f"Open Kalshi markets (JSON):\n{json.dumps(market_records, ensure_ascii=False)}"
    )
    by_ticker = {m.ticker: m for m in markets}
    try:
        result = llm.parse(
            system=MATCH_SYSTEM, user=user, output_format=MatchResult, max_tokens=4096
        )
    except Exception as e:  # noqa: BLE001 — markets are enrichment, never fatal
        print(f"  [markets] WARN: matching failed ({e}); stories get no forecasts")
        result = MatchResult(matches=[])

    used_tickers: set[str] = set()
    for match in result.matches:
        if not 0 <= match.story_index < len(stories):
            continue
        story = stories[match.story_index]
        for ticker in match.tickers[:2]:
            market = by_ticker.get(ticker)
            # One market belongs to one story — the same odds box repeated
            # across stories reads like a rendering glitch.
            if market is None or ticker in used_tickers:
                continue
            used_tickers.add(ticker)
            delta_pp, delta_label = _delta(market, prior)
            story.forecasts.append(
                Forecast(
                    platform="kalshi",
                    question=market.title,
                    probability=market.probability,
                    delta_pp=delta_pp,
                    delta_label=delta_label,
                    url=market.url,
                )
            )
    matched = sum(1 for s in stories if s.forecasts)
    for story in stories:
        if not story.forecasts:
            story.no_market_note = True
    print(f"  [markets] {matched}/{len(stories)} stories matched to Kalshi markets")


def top_movers(markets: list[Market], prior: dict[str, float], n: int = 5) -> list[MarketMove]:
    """Biggest probability swings for the 'Markets moved' footer."""
    moves: list[MarketMove] = []
    for market in markets:
        delta_pp, delta_label = _delta(market, prior)
        if delta_pp is None or abs(delta_pp) < 5:
            continue
        moves.append(
            MarketMove(
                platform="kalshi",
                question=market.title,
                probability=market.probability,
                delta_pp=delta_pp,
                delta_label=delta_label,
                url=market.url,
            )
        )
    moves.sort(key=lambda m: abs(m.delta_pp), reverse=True)
    return moves[:n]
