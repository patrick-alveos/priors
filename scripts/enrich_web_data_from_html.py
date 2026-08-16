"""One-off: copy story/human-story images from a rendered issue HTML into the
corresponding docs/data/{week}.json (backfilled issues lack images because the
Markdown archive never carried them).

Matches by headline text. Usage:
    python scripts/enrich_web_data_from_html.py <issue.html> <week>
"""

from __future__ import annotations

import html as html_mod
import json
import re
import sys
from pathlib import Path

H2_SPLIT_RE = re.compile(r"<h2[^>]*>")
IMG_RE = re.compile(r'<img src="([^"]+)"')
ATTR_RE = re.compile(r'Photo: <a href="([^"]+)"[^>]*>([^<]+)</a>')


def extract_images(html: str) -> dict[str, dict]:
    """headline text -> {url, attribution, attribution_url} from preceding markup."""
    parts = H2_SPLIT_RE.split(html)
    result: dict[str, dict] = {}
    for i in range(1, len(parts)):
        headline = html_mod.unescape(re.split(r"</h2>", parts[i], maxsplit=1)[0]).strip()
        preceding = parts[i - 1]
        imgs = IMG_RE.findall(preceding)  # last img in the chunk belongs to this story
        if not imgs:
            continue
        attr = ATTR_RE.search(preceding)
        result[headline] = {
            "url": imgs[-1],
            "attribution": html_mod.unescape(attr.group(2)) if attr else None,
            "attribution_url": attr.group(1) if attr else None,
        }
    return result


def main() -> None:
    html_path, week = Path(sys.argv[1]), sys.argv[2]
    json_path = Path("docs/data") / f"{week}.json"
    images = extract_images(html_path.read_text())
    data = json.loads(json_path.read_text())

    updated = 0
    for section in data["sections"]:
        for story in section["stories"]:
            if story.get("image") and story["image"].get("url"):
                continue
            match = images.get(story["headline"])
            if match:
                story["image"] = {"kind": "og", **match}
                updated += 1
    hs = data.get("human_story")
    if hs and not (hs.get("image") or {}).get("url"):
        match = images.get(hs["headline"])
        if match:
            hs["image"] = {"kind": "og", **match}
            updated += 1

    json_path.write_text(json.dumps(data, indent=2))
    print(f"{week}: attached {updated} images (of {len(images)} found in HTML)")


if __name__ == "__main__":
    main()
