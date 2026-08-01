"""Priors CLI.

Each pipeline stage is independently runnable (`priors ingest`, `priors cluster`,
...) via JSON artifacts in data/artifacts/, and `priors preview` runs the whole
pipeline end-to-end with no email sent and no API keys required.
"""

from __future__ import annotations

import json
from pathlib import Path

import click
from dotenv import load_dotenv

from priors import db
from priors.config import DEFAULT_CONFIG_PATH, Config, load_config
from priors.models import Article, Issue, Story
from priors.stages import cluster as cluster_stage
from priors.stages import deliver as deliver_stage
from priors.stages import enrich as enrich_stage
from priors.stages import ingest as ingest_stage
from priors.stages import render as render_stage
from priors.stages import write as write_stage

ARTIFACTS_DIR = Path("data/artifacts")
BUILD_DIR = Path("build")
ISSUES_DIR = Path("issues")


def _save(name: str, items: list) -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS_DIR / f"{name}.json"
    path.write_text(json.dumps([i.model_dump(mode="json") for i in items], indent=2))
    return path


def _load_articles() -> list[Article]:
    raw = json.loads((ARTIFACTS_DIR / "articles.json").read_text())
    return [Article.model_validate(a) for a in raw]


def _load_stories(name: str = "stories") -> list[Story]:
    raw = json.loads((ARTIFACTS_DIR / f"{name}.json").read_text())
    return [Story.model_validate(s) for s in raw]


@click.group()
@click.option("--config", "config_path", default=str(DEFAULT_CONFIG_PATH), show_default=True,
              help="Path to config.yaml")
@click.pass_context
def main(ctx: click.Context, config_path: str) -> None:
    """Priors — a self-hosted weekly news digest. Update your priors, weekly."""
    load_dotenv()
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


def _config(ctx: click.Context) -> Config:
    return load_config(ctx.obj["config_path"])


@main.command()
@click.pass_context
def init_db(ctx: click.Context) -> None:
    """Create the SQLite database and seed the owner as subscriber #1."""
    config = _config(ctx)
    conn = db.connect()
    db.init_db(conn)
    db.seed_owner(conn, config.owner.email, config.owner.name)
    click.echo(f"Database ready at {db.DEFAULT_DB_PATH} (owner {config.owner.email} subscribed).")


@main.command()
@click.option("--sample", is_flag=True, help="Use fixture data instead of live sources.")
@click.pass_context
def ingest(ctx: click.Context, sample: bool) -> None:
    """Stage 1: pull candidate articles from configured sources."""
    config = _config(ctx)
    conn = None
    if not sample:
        conn = db.connect()
        db.init_db(conn)
    articles = ingest_stage.run(config, sample=sample, conn=conn)
    path = _save("articles", articles)
    click.echo(f"Ingested {len(articles)} articles -> {path}")


@main.command()
@click.option("--live", is_flag=True, help="Use the LLM for clustering (default: naive grouping).")
@click.pass_context
def cluster(ctx: click.Context, live: bool) -> None:
    """Stage 2: group articles into stories and rank them."""
    from priors.llm import LLM

    config = _config(ctx)
    llm = LLM(config.llm.model) if live else None
    stories = cluster_stage.run(config, _load_articles(), llm=llm)
    path = _save("stories", stories)
    click.echo(f"Clustered into {len(stories)} stories -> {path}")


@main.command()
@click.option("--sample", is_flag=True, help="Skip live market/image lookups.")
@click.pass_context
def enrich(ctx: click.Context, sample: bool) -> None:
    """Stage 3: attach prediction-market data and images."""
    stories = enrich_stage.run(_config(ctx), _load_stories(), sample=sample)
    path = _save("stories_enriched", stories)
    click.echo(f"Enriched {len(stories)} stories -> {path}")


@main.command()
@click.option("--sample", is_flag=True, help="Use fixture editorial content (no LLM call).")
@click.pass_context
def write(ctx: click.Context, sample: bool) -> None:
    """Stage 4: compose the issue with the LLM."""
    from priors.llm import LLM

    config = _config(ctx)
    llm = None if sample else LLM(config.llm.model)
    issue = write_stage.run(config, _load_stories("stories_enriched"), sample=sample, llm=llm)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS_DIR / "issue.json"
    path.write_text(issue.model_dump_json(indent=2))
    click.echo(f"Composed issue {issue.week} -> {path}")


@main.command()
@click.option("--archive/--no-archive", default=False,
              help="Also write the Markdown copy into issues/ (the public archive).")
@click.pass_context
def render(ctx: click.Context, archive: bool) -> None:
    """Stage 5: render HTML email + Markdown archive."""
    issue = Issue.model_validate_json((ARTIFACTS_DIR / "issue.json").read_text())
    html_path, md_path = render_stage.run(
        issue, BUILD_DIR, archive_dir=ISSUES_DIR if archive else None
    )
    click.echo(f"Rendered {html_path} and {md_path}")


@main.command()
@click.option("--dry-run/--send", default=True, show_default=True)
@click.pass_context
def deliver(ctx: click.Context, dry_run: bool) -> None:
    """Stage 6: send the issue via Resend to all active subscribers."""
    config = _config(ctx)
    issue = Issue.model_validate_json((ARTIFACTS_DIR / "issue.json").read_text())
    conn = db.connect()
    db.init_db(conn)
    db.seed_owner(conn, config.owner.email, config.owner.name)
    html_path = BUILD_DIR / f"{issue.week}.html"
    html = html_path.read_text()
    subject = deliver_stage.build_subject(config, issue.period_end.strftime("%b %d, %Y"))
    recipients = deliver_stage.run(config, conn, html, subject, dry_run=dry_run)
    if not dry_run:
        # Bookkeeping for a deliver-only send: consume articles, archive, record.
        used_ids = [a.id for s in issue.sections for st in s.stories for a in st.articles]
        db.mark_articles_used(conn, used_ids, issue.week)
        md_src = BUILD_DIR / f"{issue.week}.md"
        md_dest = ISSUES_DIR / f"{issue.week}.md"
        if md_src.exists():
            ISSUES_DIR.mkdir(parents=True, exist_ok=True)
            md_dest.write_text(md_src.read_text())
        db.record_issue(conn, issue.week, subject, str(html_path), str(md_dest), sent=True)
    verb = "Would send" if dry_run else "Sent"
    click.echo(
        f"{verb} issue {issue.week} to {len(recipients)} subscriber(s): {', '.join(recipients)}"
    )


@main.command()
@click.pass_context
def preview(ctx: click.Context) -> None:
    """Run the full pipeline with sample data; render locally, send nothing."""
    from priors.pipeline import run_weekly

    result = run_weekly(_config(ctx), sample=True)
    click.echo(f"Preview issue {result.week} built.")
    click.echo(f"  HTML:     {result.html_path}")
    click.echo(f"  Markdown: {result.md_path}")
    click.echo(f"  Would deliver to: {', '.join(result.recipients)}")
    click.echo("Open the HTML file in a browser to see the issue.")


@main.command()
@click.option("--dry-run", is_flag=True,
              help="Run the live pipeline (real sources + LLM) but send no email.")
@click.pass_context
def run(ctx: click.Context, dry_run: bool) -> None:
    """Full weekly run: ingest -> cluster -> enrich -> write -> render -> deliver."""
    from priors.pipeline import run_weekly

    result = run_weekly(_config(ctx), dry_run=dry_run)
    verb = "Sent" if result.sent else "Built (no email sent)"
    click.echo(f"{verb} issue {result.week} -> {result.html_path}")
    if result.removed_links:
        click.echo(f"  {len(result.removed_links)} broken link(s) removed before send.")


@main.command()
@click.pass_context
def daemon(ctx: click.Context) -> None:
    """Run forever, executing the weekly pipeline on the configured schedule."""
    from priors.scheduler import run_forever

    run_forever(_config(ctx))


@main.command()
def setup() -> None:
    """Interactive onboarding wizard (arrives in Phase 3)."""
    click.echo(
        "The onboarding wizard arrives in Phase 3.\n"
        "For now: edit config.yaml, copy .env.example to .env, then `priors preview`."
    )


if __name__ == "__main__":
    main()
