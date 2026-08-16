"""Weekly pipeline orchestration: ingest -> cluster -> enrich (images) ->
markets -> write -> extras -> linkcheck -> render -> deliver.

Markets run before write so the composed implications can reference real
probability moves. Used by both `priors run` (CLI) and the scheduler daemon;
the sample path (`priors preview`) runs the same flow with fixture data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx

from priors import db, extras, markets
from priors.config import Config
from priors.linkcheck import validate_issue
from priors.llm import LLM
from priors.sample_data import SAMPLE_HUMAN_STORY, SAMPLE_PHOTO
from priors.stages import cluster, deliver, enrich, ingest, render, write
from priors.stages.write import iso_week

ARTIFACTS_DIR = Path("data/artifacts")
BUILD_DIR = Path("build")
ISSUES_DIR = Path("issues")


@dataclass
class RunResult:
    week: str
    html_path: Path
    md_path: Path
    recipients: list[str]
    sent: bool
    removed_links: list[str] = field(default_factory=list)
    usage_summary: str | None = None


def run_weekly(config: Config, *, sample: bool = False, dry_run: bool = False) -> RunResult:
    conn = db.connect()
    db.init_db(conn)
    db.seed_owner(conn, config.owner.email, config.owner.name)

    llm = None if sample else LLM(config.llm.model)
    week = iso_week(date.today())

    print("[1/8] ingest")
    articles = ingest.run(config, sample=sample, conn=None if sample else conn)
    if not articles:
        raise RuntimeError("Ingest produced no articles — check feeds and network.")

    print("[2/8] cluster")
    stories = cluster.run(config, articles, llm=llm)
    if not stories:
        raise RuntimeError("Clustering produced no stories.")

    print("[3/8] images")
    stories = enrich.run(config, stories, sample=sample)

    print("[4/8] prediction markets")
    movers = []
    if not sample and config.markets.kalshi:
        try:
            kalshi_markets = markets.fetch_markets()
            prior = markets.previous_snapshots(conn, week)
            markets.match_markets(llm, stories, kalshi_markets, prior)
            movers = markets.top_movers(kalshi_markets, prior)
            markets.snapshot_markets(conn, week, kalshi_markets)
        except Exception as e:  # noqa: BLE001 — markets are enrichment, never fatal
            print(f"  [markets] WARN: Kalshi unavailable ({e}); issue ships without odds")
            for story in stories:
                story.no_market_note = True

    print("[5/8] write")
    issue = write.run(config, stories, sample=sample, llm=llm)
    if not sample:
        issue.markets_moved = movers

    print("[6/8] extras")
    if sample:
        issue.human_story = SAMPLE_HUMAN_STORY.model_copy()
        issue.photo = SAMPLE_PHOTO.model_copy()
    else:
        if config.extras.human_story.enabled:
            candidates = extras.fetch_human_candidates(config)
            headers = {"User-Agent": "Mozilla/5.0 (compatible; PriorsDigest/0.1)"}
            with httpx.Client(headers=headers) as client:
                issue.human_story = extras.compose_human_story(llm, candidates, client)
        if config.extras.photo_of_week.enabled:
            issue.photo = extras.fetch_photo_of_week()

    removed: list[str] = []
    if not sample:
        print("[7/8] validate links")
        removed = validate_issue(issue)
        for item in removed:
            print(f"  [linkcheck] removed {item}")

    print("[7/8] render" if sample else "[8/8] render + deliver")
    html_path, md_path = render.run(
        issue, BUILD_DIR, archive_dir=None if sample or dry_run else ISSUES_DIR
    )
    # Persist the composed issue so `priors deliver --send` can ship exactly
    # this build later without re-running the LLM.
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS_DIR / "issue.json").write_text(issue.model_dump_json(indent=2))
    html = html_path.read_text()
    subject = deliver.build_subject(config, issue.period_end.strftime("%b %d, %Y"))

    send_for_real = not sample and not dry_run
    recipients = deliver.run(config, conn, html, subject, dry_run=not send_for_real)

    # Only a real send consumes the articles — a dry-run must not starve
    # the following real run via cross-week dedup.
    if send_for_real:
        used_ids = [a.id for s in stories for a in s.articles]
        db.mark_articles_used(conn, used_ids, issue.week)
        # Publish to the PWA reader (docs/ on GitHub Pages).
        from priors.webdata import export_issue

        export_issue(issue)
    if not sample:
        db.record_issue(conn, issue.week, subject, str(html_path), str(md_path), send_for_real)

    usage_summary = llm.log_run(f"issue-{issue.week}") if llm else None
    if usage_summary:
        print(f"  {usage_summary}")

    return RunResult(
        week=issue.week,
        html_path=html_path,
        md_path=md_path,
        recipients=recipients,
        sent=send_for_real,
        removed_links=removed,
        usage_summary=usage_summary,
    )
