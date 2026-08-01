from pathlib import Path

import pytest
from pydantic import ValidationError

from priors.config import Config, load_config

REPO_ROOT = Path(__file__).parent.parent


def test_default_config_loads() -> None:
    config = load_config(REPO_ROOT / "config.yaml")
    assert config.digest.name == "Priors"
    assert config.owner.timezone == "Europe/Helsinki"
    assert config.schedule.day == "monday"
    assert len(config.enabled_sections) == 4
    custom = next(s for s in config.sections if s.key == "custom")
    assert custom.topics


def test_missing_config_has_helpful_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="priors setup"):
        load_config(tmp_path / "nope.yaml")


def test_invalid_timezone_rejected() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate(
            {
                "owner": {"name": "X", "email": "x@example.com", "timezone": "Mars/Olympus"},
                "sections": [{"key": "politics", "title": "Politics"}],
            }
        )


def test_invalid_schedule_day_rejected() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate(
            {
                "owner": {"name": "X", "email": "x@example.com", "timezone": "UTC"},
                "schedule": {"day": "someday"},
                "sections": [{"key": "politics", "title": "Politics"}],
            }
        )
