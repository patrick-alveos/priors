"""One-off: rebuild docs/data/{week}.json for issues that exist only as
Markdown in issues/ (the archive predates the JSON export).

Parses the issue.md.j2 output format. Backfilled issues have no story images
(the Markdown archive never carried them). Skips weeks that already have JSON.

Usage: python scripts/backfill_web_data.py
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from priors.models import (  # noqa: E402
    Forecast,
    HumanStory,
    Issue,
    IssueSection,
    MarketMove,
    PhotoOfWeek,
    Story,
    Take,
)
from priors.webdata import DOCS_DATA_DIR, export_issue  # noqa: E402

LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
ODDS_RE = re.compile(
    r'\[(?P<platform>[^\]]+)\]\((?P<url>[^)]+)\)(?::| puts)? ["“](?P<q>.+?)["”]'
    r"(?: at | — )\*\*(?P<pct>\d+)%\*\*"
    r"(?: \((?P<arrow>[↑↓])(?P<delta>[\d.]+)pp (?P<label>[^)]+)\))?"
)


def _parse_odds_line(line: str) -> Forecast | None:
    m = ODDS_RE.search(line)
    if not m:
        return None
    delta = float(m.group("delta")) if m.group("delta") else None
    if delta is not None and m.group("arrow") == "↓":
        delta = -delta
    return Forecast(
        platform=m.group("platform").lower(),
        question=m.group("q"),
        probability=int(m.group("pct")) / 100,
        delta_pp=delta,
        delta_label=m.group("label") or "week-over-week",
        url=m.group("url"),
    )


def parse_issue_md(path: Path) -> Issue:
    text = path.read_text()
    week = re.search(r"^# .+ — (\d{4}-W\d{2})", text, re.M).group(1)
    tagline = re.search(r"^\*(.+)\*$", text, re.M).group(1)
    digest_name = re.search(r"^# (.+?) — ", text, re.M).group(1)
    covering = re.search(r"^Covering (\S+) to (\S+)\.", text, re.M)
    period_start = date.fromisoformat(covering.group(1))
    period_end = date.fromisoformat(covering.group(2))

    sections: list[IssueSection] = []
    markets_moved: list[MarketMove] = []
    human_story: HumanStory | None = None
    photo: PhotoOfWeek | None = None

    # Split into ## blocks
    blocks = re.split(r"^## ", text, flags=re.M)[1:]
    for block in blocks:
        title, _, body = block.partition("\n")
        title = title.strip()
        if title == "Markets moved":
            for line in body.splitlines():
                f = _parse_odds_line(line)
                if f:
                    markets_moved.append(
                        MarketMove(
                            platform=f.platform, question=f.question,
                            probability=f.probability, delta_pp=f.delta_pp or 0.0,
                            delta_label=f.delta_label, url=f.url,
                        )
                    )
            continue
        if title == "Human story of the week":
            headline_m = re.search(r"^### (.+)$", body, re.M)
            via_m = re.search(r"^Via \[([^\]]+)\]\(([^)]+)\)", body, re.M)
            paras = [
                p.strip() for p in body.split("\n\n")
                if p.strip() and not p.strip().startswith(("###", "Via ["))
            ]
            if headline_m and via_m:
                human_story = HumanStory(
                    headline=headline_m.group(1), text=paras[0] if paras else "",
                    source=via_m.group(1), source_url=via_m.group(2),
                )
            continue
        if title == "Photo of the week":
            img_m = re.search(r"^!\[([^\]]*)\]\(([^)]+)\)", body, re.M)
            attr_m = re.search(r"^\[([^\]]+)\]\(([^)]+)\) · Wikimedia Commons", body, re.M)
            desc_m = re.search(r"^\*(.+)\*$", body, re.M)
            if img_m and attr_m:
                photo = PhotoOfWeek(
                    image_url=img_m.group(2), title=img_m.group(1),
                    description=desc_m.group(1) if desc_m else None,
                    attribution=attr_m.group(1), link=attr_m.group(2),
                )
            continue

        # Regular content section
        stories: list[Story] = []
        for chunk in re.split(r"^### ", body, flags=re.M)[1:]:
            headline, _, rest = chunk.partition("\n")
            what = re.search(r"\*\*What happened\.\*\* (.+)", rest)
            impl = re.search(r"\*\*(?:Potential implications|Why it matters)\.\*\* (.+)", rest)
            takes = []
            takes_block = re.search(
                r"\*\*The takes\.\*\*\n((?:- .+\n?)+)", rest
            )
            if takes_block:
                for line in takes_block.group(1).splitlines():
                    lm = LINK_RE.search(line)
                    if lm:
                        takes.append(
                            Take(
                                source=lm.group(1), source_url=lm.group(2),
                                text=line[lm.end():].strip(),
                            )
                        )
            forecasts = []
            no_market = "No liquid prediction market covers this yet" in rest
            odds_block = re.search(
                r"\*\*(?:Updating the priors|What's next \(odds\))\.\*\*\n((?:- .+\n?)+)", rest
            )
            if odds_block:
                for line in odds_block.group(1).splitlines():
                    f = _parse_odds_line(line)
                    if f:
                        forecasts.append(f)
            stories.append(
                Story(
                    section=re.sub(r"\W+", "-", title.lower()).strip("-"),
                    headline=headline.strip(),
                    what_happened=what.group(1).strip() if what else "",
                    potential_implications=impl.group(1).strip() if impl else "",
                    takes=takes, forecasts=forecasts, no_market_note=no_market,
                )
            )
        if stories:
            sections.append(
                IssueSection(key=stories[0].section, title=title, stories=stories)
            )

    return Issue(
        week=week, period_start=period_start, period_end=period_end,
        digest_name=digest_name, tagline=tagline, accent_color="#3E5C48",
        sections=sections, markets_moved=markets_moved,
        human_story=human_story, photo=photo,
    )


def main() -> None:
    for md in sorted(Path("issues").glob("*-W*.md")):
        week = md.stem
        target = DOCS_DATA_DIR / f"{week}.json"
        if target.exists():
            print(f"skip {week} (JSON exists)")
            continue
        issue = parse_issue_md(md)
        export_issue(issue)
        n_stories = sum(len(s.stories) for s in issue.sections)
        print(f"backfilled {week}: {len(issue.sections)} sections, {n_stories} stories")


if __name__ == "__main__":
    main()
