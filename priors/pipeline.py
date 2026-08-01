"""Weekly pipeline orchestration: ingest -> cluster -> enrich -> write ->
render -> linkcheck -> deliver.

Used by both `priors run` (CLI) and the scheduler daemon. The sample path
(`priors preview`) runs the same flow with fixture data, no API keys, and no
email sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from priors import db
from priors.config import Config
from priors.linkcheck import validate_issue
from priors.llm import LLM
from priors.stages import cluster, deliver, enrich, ingest, render, write

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

    print("[1/6] ingest")
    articles = ingest.run(config, sample=sample, conn=None if sample else conn)
    if not articles:
        raise RuntimeError("Ingest produced no articles — check feeds and network.")

    print("[2/6] cluster")
    stories = cluster.run(config, articles, llm=llm)
    if not stories:
        raise RuntimeError("Clustering produced no stories.")

    print("[3/6] enrich")
    stories = enrich.run(config, stories, sample=sample)

    print("[4/6] write")
    issue = write.run(config, stories, sample=sample, llm=llm)

    removed: list[str] = []
    if not sample:
        print("[5/6] validate links")
        removed = validate_issue(issue)
        for item in removed:
            print(f"  [linkcheck] removed {item}")

    print("[5/6] render" if sample else "[6/6] render + deliver")
    html_path, md_path = render.run(
        issue, BUILD_DIR, archive_dir=None if sample or dry_run else ISSUES_DIR
    )
    html = html_path.read_text()
    subject = deliver.build_subject(config, issue.period_end.strftime("%b %d, %Y"))

    send_for_real = not sample and not dry_run
    recipients = deliver.run(config, conn, html, subject, dry_run=not send_for_real)

    if not sample:
        used_ids = [a.id for s in stories for a in s.articles]
        db.mark_articles_used(conn, used_ids, issue.week)
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
