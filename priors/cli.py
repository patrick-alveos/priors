"""Priors CLI.

Each pipeline stage is independently runnable (`priors ingest`, `priors cluster`,
...) via JSON artifacts in data/artifacts/, and `priors preview` runs the whole
pipeline end-to-end with no email sent and no API keys required.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

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
    articles = ingest_stage.run(_config(ctx), sample=sample)
    path = _save("articles", articles)
    click.echo(f"Ingested {len(articles)} articles -> {path}")


@main.command()
@click.pass_context
def cluster(ctx: click.Context) -> None:
    """Stage 2: group articles into stories and rank them."""
    stories = cluster_stage.run(_config(ctx), _load_articles())
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
    """Stage 4: compose the issue (LLM in Phase 1)."""
    issue = write_stage.run(_config(ctx), _load_stories("stories_enriched"), sample=sample)
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
    recipients = deliver_stage.run(config, conn, BUILD_DIR / f"{issue.week}.html", dry_run=dry_run)
    verb = "Would send" if dry_run else "Sent"
    click.echo(
        f"{verb} issue {issue.week} to {len(recipients)} subscriber(s): {', '.join(recipients)}"
    )


@main.command()
@click.pass_context
def preview(ctx: click.Context) -> None:
    """Run the full pipeline with sample data; render locally, send nothing."""
    config = _config(ctx)
    articles = ingest_stage.run(config, sample=True)
    stories = cluster_stage.run(config, articles)
    stories = enrich_stage.run(config, stories, sample=True)
    issue = write_stage.run(config, stories, sample=True)
    html_path, md_path = render_stage.run(issue, BUILD_DIR)
    conn = db.connect()
    db.init_db(conn)
    db.seed_owner(conn, config.owner.email, config.owner.name)
    recipients = deliver_stage.run(config, conn, html_path, dry_run=True)
    click.echo(f"Preview issue {issue.week} built from {len(articles)} sample articles.")
    click.echo(f"  HTML:     {html_path}")
    click.echo(f"  Markdown: {md_path}")
    click.echo(f"  Would deliver to: {', '.join(recipients)}")
    click.echo("Open the HTML file in a browser to see the issue.")


@main.command()
@click.pass_context
def run(ctx: click.Context) -> None:
    """Full weekly run: ingest -> cluster -> enrich -> write -> render -> deliver."""
    raise click.ClickException(
        "The live pipeline arrives in Phase 1. Use `priors preview` for now."
    )


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
