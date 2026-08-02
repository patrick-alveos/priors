"""Configuration loading and validation.

config.yaml holds everything editorial (safe to commit after personalization);
secrets come exclusively from environment variables / .env.
"""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, field_validator

DEFAULT_CONFIG_PATH = Path("config.yaml")

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class DigestConfig(BaseModel):
    name: str = "Priors"
    tagline: str = "Update your priors, weekly."
    accent_color: str = "#1A4D8F"
    language: str = "en"


class OwnerConfig(BaseModel):
    name: str
    email: str
    timezone: str = "UTC"

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError(f"owner.email does not look like an email address: {v!r}")
        return v

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(
                f"Unknown timezone {v!r} — use an IANA name like 'Europe/Helsinki'"
            ) from e
        return v


class ScheduleConfig(BaseModel):
    day: str = "monday"
    time: str = "06:00"

    @field_validator("day")
    @classmethod
    def _valid_day(cls, v: str) -> str:
        if v.lower() not in WEEKDAYS:
            raise ValueError(f"schedule.day must be one of {WEEKDAYS}")
        return v.lower()

    @field_validator("time")
    @classmethod
    def _valid_time(cls, v: str) -> str:
        hh, mm = v.split(":")
        if not (0 <= int(hh) < 24 and 0 <= int(mm) < 60):
            raise ValueError("schedule.time must be HH:MM (24h)")
        return v


class SectionConfig(BaseModel):
    key: str
    title: str
    enabled: bool = True
    topics: list[str] = []


class NewsApiConfig(BaseModel):
    provider: str = "gnews"
    enabled: bool = True


class RssFeed(BaseModel):
    url: str
    section: str | None = None  # section key articles from this feed default to


class SourcesConfig(BaseModel):
    rss: list[RssFeed] = []
    news_api: NewsApiConfig = NewsApiConfig()

    @field_validator("rss", mode="before")
    @classmethod
    def _coerce_plain_urls(cls, v: object) -> object:
        if isinstance(v, list):
            return [{"url": item} if isinstance(item, str) else item for item in v]
        return v


class MarketsConfig(BaseModel):
    polymarket: bool = True
    kalshi: bool = True
    metaculus: bool = True


class HumanStoryConfig(BaseModel):
    enabled: bool = True
    feeds: list[str] = []


class PhotoOfWeekConfig(BaseModel):
    enabled: bool = True


class ExtrasConfig(BaseModel):
    human_story: HumanStoryConfig = HumanStoryConfig()
    photo_of_week: PhotoOfWeekConfig = PhotoOfWeekConfig()


class LLMConfig(BaseModel):
    model: str = "claude-sonnet-5"
    max_stories_per_section: int = 4


class EmailConfig(BaseModel):
    from_address: str = ""
    subject_template: str = "{name} — week of {date}"

    model_config = {"populate_by_name": True}

    def __init__(self, **data: object) -> None:
        if "from" in data:
            data["from_address"] = data.pop("from")
        super().__init__(**data)


class Config(BaseModel):
    digest: DigestConfig = DigestConfig()
    owner: OwnerConfig
    schedule: ScheduleConfig = ScheduleConfig()
    sections: list[SectionConfig]
    sources: SourcesConfig = SourcesConfig()
    markets: MarketsConfig = MarketsConfig()
    extras: ExtrasConfig = ExtrasConfig()
    llm: LLMConfig = LLMConfig()
    email: EmailConfig = EmailConfig()

    @property
    def enabled_sections(self) -> list[SectionConfig]:
        return [s for s in self.sections if s.enabled]


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config.yaml from the repo root "
            "or run `priors setup` to generate one."
        )
    with path.open() as f:
        raw = yaml.safe_load(f)
    return Config.model_validate(raw)
