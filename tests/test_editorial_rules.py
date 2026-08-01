"""Tests for the code-enforced editorial rules: attribution, dedup, link validity."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from priors.config import load_config
from priors.linkcheck import validate_issue
from priors.models import Article, Forecast, Story, StoryImage, Take
from priors.stages.cluster import ClusterGroup, ClusterResult, apply_clusters
from priors.stages.ingest import article_id, filter_articles, normalize_url
from priors.stages.write import TakeDraft, validate_takes

REPO_ROOT = Path(__file__).parent.parent


def _article(id_: str, url: str, section: str = "politics", days_old: int = 1) -> Article:
    return Article(
        id=id_,
        url=url,
        title=f"Title {id_}",
        source=f"Source {id_}",
        published_at=datetime.now(UTC) - timedelta(days=days_old),
        section_hint=section,
    )


class TestTakeValidation:
    def test_invented_source_url_is_dropped(self) -> None:
        story = Story(section="politics", headline="h", what_happened="", why_it_matters="",
                      articles=[_article("a1", "https://real.example/article")])
        drafts = [
            TakeDraft(source="Real Outlet", source_url="https://real.example/article",
                      text="argues X."),
            TakeDraft(source="Invented", source_url="https://fabricated.example/x",
                      text="claims Y."),
        ]
        takes = validate_takes(story, drafts)
        assert len(takes) == 1
        assert takes[0].source == "Real Outlet"

    def test_same_outlet_not_quoted_twice(self) -> None:
        story = Story(section="politics", headline="h", what_happened="", why_it_matters="",
                      articles=[_article("a1", "https://x.example/1"),
                                _article("a2", "https://x.example/2")])
        drafts = [
            TakeDraft(source="Outlet", source_url="https://x.example/1", text="first."),
            TakeDraft(source="outlet", source_url="https://x.example/2", text="second."),
        ]
        assert len(validate_takes(story, drafts)) == 1


class TestIngest:
    def test_url_normalization_strips_tracking(self) -> None:
        a = "https://Example.com/story/?utm_source=x&utm_campaign=y"
        b = "https://example.com/story"
        assert normalize_url(a) == normalize_url(b)
        assert article_id(a) == article_id(b)

    def test_filter_drops_old_used_and_duplicate(self) -> None:
        fresh = _article("f1", "https://e.example/fresh")
        dupe = _article("f1", "https://e.example/fresh")
        old = _article("o1", "https://e.example/old", days_old=10)
        used = _article("u1", "https://e.example/used")
        kept = filter_articles([fresh, dupe, old, used], used_ids={"u1"})
        assert [a.id for a in kept] == ["f1"]

    def test_filter_keeps_undated_articles(self) -> None:
        undated = Article(id="n1", url="https://e.example/n", title="t", source="s")
        assert filter_articles([undated], used_ids=set()) == [undated]


class TestClusterValidation:
    def test_hallucinated_ids_and_overflow_are_dropped(self) -> None:
        config = load_config(REPO_ROOT / "config.yaml")
        articles = [_article(f"a{i}", f"https://e.example/{i}") for i in range(8)]
        result = ClusterResult(stories=[
            ClusterGroup(section="politics", article_ids=["a0", "ghost-id"], rank=1),
            ClusterGroup(section="nonexistent-section", article_ids=["a1"], rank=2),
            # more groups than max_stories_per_section allows
            *[ClusterGroup(section="politics", article_ids=[f"a{i}"], rank=i + 2)
              for i in range(1, 8)],
        ])
        stories = apply_clusters(config, articles, result)
        politics = [s for s in stories if s.section == "politics"]
        assert len(politics) <= config.llm.max_stories_per_section
        all_ids = {a.id for s in stories for a in s.articles}
        assert "ghost-id" not in all_ids
        # each article appears in at most one story
        assert len(all_ids) == sum(len(s.articles) for s in stories)


class TestLinkcheck:
    def test_broken_links_removed_and_image_downgraded(self) -> None:
        from datetime import date

        from priors.models import Issue, IssueSection

        story = Story(
            section="politics", headline="h", what_happened="w", why_it_matters="y",
            takes=[
                Take(source="Good", source_url="https://ok.example/a", text="t"),
                Take(source="Bad", source_url="https://dead.example/b", text="t"),
            ],
            forecasts=[Forecast(platform="polymarket", question="q", probability=0.5,
                                url="https://dead.example/m")],
            image=StoryImage(kind="og", url="https://dead.example/img.jpg",
                             attribution="X", attribution_url="https://ok.example/a"),
        )
        issue = Issue(
            week="2026-W31", period_start=date(2026, 7, 25), period_end=date(2026, 8, 1),
            digest_name="Priors", tagline="t", accent_color="#000",
            sections=[IssueSection(key="politics", title="Politics", stories=[story])],
        )
        removed = validate_issue(issue, check=lambda url: "dead.example" not in url)
        assert len(story.takes) == 1 and story.takes[0].source == "Good"
        assert story.forecasts == []
        assert story.image is not None and story.image.kind == "card"
        assert len(removed) == 3
