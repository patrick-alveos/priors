"""End-to-end test of the sample pipeline: ingest -> cluster -> enrich -> write -> render."""

from datetime import date
from pathlib import Path

from priors.config import load_config
from priors.stages import cluster, enrich, ingest, render, write

REPO_ROOT = Path(__file__).parent.parent


def _build_issue():
    config = load_config(REPO_ROOT / "config.yaml")
    articles = ingest.run(config, sample=True)
    stories = cluster.run(config, articles)
    stories = enrich.run(config, stories, sample=True)
    return config, write.run(config, stories, sample=True, today=date(2026, 8, 3))


def test_pipeline_produces_complete_issue() -> None:
    config, issue = _build_issue()
    assert issue.week == "2026-W32"
    assert issue.digest_name == config.digest.name
    assert issue.markets_moved
    section_keys = {s.key for s in issue.sections}
    assert section_keys == {s.key for s in config.enabled_sections}
    stories = [st for s in issue.sections for st in s.stories]
    assert stories, "sample pipeline must yield at least one story"
    for story in stories:
        assert story.headline
        assert story.what_happened
        # Every story must either carry forecasts or explicitly say no market exists.
        assert story.forecasts or story.no_market_note


def test_render_html_and_markdown(tmp_path: Path) -> None:
    from priors.sample_data import SAMPLE_HUMAN_STORY, SAMPLE_PHOTO

    config, issue = _build_issue()
    issue.human_story = SAMPLE_HUMAN_STORY.model_copy()
    issue.photo = SAMPLE_PHOTO.model_copy()
    html_path, md_path = render.run(issue, tmp_path, archive_dir=tmp_path / "issues")
    html = html_path.read_text()
    md = md_path.read_text()
    assert config.digest.name in html
    assert "Potential implications" in html
    assert "Markets moved" in html
    assert "Human story of the week" in html
    assert "Photo of the week" in html
    assert config.digest.accent_color in html
    assert md_path.name == f"{issue.week}.md"
    assert "No liquid prediction market covers this yet" in md
    assert "week-over-week" in md
