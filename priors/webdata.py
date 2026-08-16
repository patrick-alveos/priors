"""Web data export for the PWA reader (docs/ on GitHub Pages).

Each real run writes docs/data/{week}.json (the full Issue model) and rebuilds
docs/data/index.json — newest first — which the app uses to open the latest
issue and to list the archive.
"""

from __future__ import annotations

import json
from pathlib import Path

from priors.models import Issue

DOCS_DATA_DIR = Path("docs/data")


def export_issue(issue: Issue, data_dir: Path = DOCS_DATA_DIR) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{issue.week}.json"
    path.write_text(issue.model_dump_json(indent=2))
    rebuild_index(data_dir)
    return path


def rebuild_index(data_dir: Path = DOCS_DATA_DIR) -> Path:
    entries = []
    for path in data_dir.glob("*-W*.json"):
        try:
            data = json.loads(path.read_text())
            entries.append(
                {
                    "week": data["week"],
                    "period_start": data["period_start"],
                    "period_end": data["period_end"],
                }
            )
        except (json.JSONDecodeError, KeyError):
            continue
    entries.sort(key=lambda e: e["week"], reverse=True)
    index_path = data_dir / "index.json"
    index_path.write_text(json.dumps({"issues": entries}, indent=2))
    return index_path
