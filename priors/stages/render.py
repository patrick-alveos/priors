"""Stage 5 — render: produce the HTML email and the Markdown archive copy.

HTML is a table-based Jinja2 template with inline styles (Gmail/Outlook/Apple
Mail safe, dark-mode aware via meta tags and non-pure colors). Markdown goes to
issues/YYYY-WW.md — the public archive that doubles as marketing.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from priors.models import Issue

_env = Environment(
    loader=PackageLoader("priors", "templates"),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _pct(probability: float) -> str:
    return f"{round(probability * 100)}%"


def _delta(delta_pp: float | None, label: str = "week-over-week") -> str:
    if delta_pp is None:
        return ""
    arrow = "↑" if delta_pp > 0 else "↓"
    return f"({arrow}{abs(delta_pp):g}pp {label})"


_env.filters["pct"] = _pct
_env.filters["delta"] = _delta


def render_html(issue: Issue) -> str:
    return _env.get_template("email.html.j2").render(issue=issue)


def render_markdown(issue: Issue) -> str:
    return _env.get_template("issue.md.j2").render(issue=issue)


def run(issue: Issue, out_dir: Path, *, archive_dir: Path | None = None) -> tuple[Path, Path]:
    """Render both formats. Returns (html_path, md_path)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{issue.week}.html"
    html_path.write_text(render_html(issue))

    md_dir = archive_dir if archive_dir is not None else out_dir
    md_dir.mkdir(parents=True, exist_ok=True)
    md_path = md_dir / f"{issue.week}.md"
    md_path.write_text(render_markdown(issue))
    return html_path, md_path
