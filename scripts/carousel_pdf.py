"""Render a LinkedIn carousel PDF from a Priors issue + carousel-content.json.

Usage: python scripts/carousel_pdf.py
Reads  data/artifacts/issue.json + build/carousel-content.json
Writes build/priors-carousel-<week>.pdf  (1080x1350 per slide, LI portrait)
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas

from priors.models import Issue

W, H = 1080, 1350
M = 96  # margin

PAPER = HexColor("#F4EFE4")
CARD = HexColor("#FDFAF3")
INK = HexColor("#2B2820")
MUTED = HexColor("#6E6759")
FAINT = HexColor("#9A9284")
HAIR = HexColor("#E3DBC9")
GREEN = HexColor("#3E5C48")
ODDSBG = HexColor("#EFEADB")

FONT_DIR = Path("/System/Library/Fonts/Supplemental")
pdfmetrics.registerFont(TTFont("Georgia", str(FONT_DIR / "Georgia.ttf")))
pdfmetrics.registerFont(TTFont("Georgia-Bold", str(FONT_DIR / "Georgia Bold.ttf")))
pdfmetrics.registerFont(TTFont("Georgia-Italic", str(FONT_DIR / "Georgia Italic.ttf")))

SERIF, SERIF_B, SERIF_I, SANS, SANS_B = (
    "Georgia", "Georgia-Bold", "Georgia-Italic", "Helvetica", "Helvetica-Bold",
)


def wrap(text: str, font: str, size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if pdfmetrics.stringWidth(trial, font, size) <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def draw_par(c, text, x, y, font, size, leading, color, max_width) -> float:
    """Draw wrapped text with top edge at y; return the new y below the block."""
    c.setFont(font, size)
    c.setFillColor(color)
    for line in wrap(text, font, size, max_width):
        y -= leading
        c.drawString(x, y, line)
    return y


def start_slide(c, footer_page: int | None, week: str) -> None:
    c.setFillColor(PAPER)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    if footer_page is not None:
        c.setFont(SANS, 20)
        c.setFillColor(FAINT)
        c.drawString(M, 52, "Priors · update your priors, weekly")
        c.drawRightString(W - M, 52, f"{week}   ·   {footer_page}")


def header(c, label: str) -> float:
    c.setFont(SANS_B, 26)
    c.setFillColor(GREEN)
    c.drawString(M, H - 110, label.upper())
    c.setStrokeColor(HAIR)
    c.setLineWidth(2)
    c.line(M, H - 132, W - M, H - 132)
    return H - 132


def chip(c, x, y, pct: int, basis: str) -> None:
    """Probability chip: solid green = Kalshi market price, outlined = estimate."""
    cw, ch = 132, 62
    if basis == "kalshi":
        c.setFillColor(GREEN)
        c.roundRect(x, y - ch, cw, ch, 14, stroke=0, fill=1)
        c.setFillColor(CARD)
    else:
        c.setFillColor(CARD)
        c.setStrokeColor(GREEN)
        c.setLineWidth(2.5)
        c.roundRect(x, y - ch, cw, ch, 14, stroke=1, fill=1)
        c.setFillColor(GREEN)
    c.setFont(SANS_B, 32)
    c.drawCentredString(x + cw / 2, y - ch + 18, f"{pct}%")
    c.setFont(SANS, 19)
    c.setFillColor(GREEN if basis == "kalshi" else FAINT)
    c.drawCentredString(x + cw / 2, y - ch - 26, "Kalshi" if basis == "kalshi" else "estimate")


def fetch_image(url: str) -> ImageReader | None:
    try:
        resp = httpx.get(url, timeout=20, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        return ImageReader(io.BytesIO(resp.content))
    except Exception as e:  # noqa: BLE001
        print(f"  WARN: image fetch failed {url}: {e}")
        return None


def draw_image_fitted(c, img: ImageReader, x, y_top, max_w, max_h) -> float:
    iw, ih = img.getSize()
    scale = min(max_w / iw, max_h / ih)
    w, h = iw * scale, ih * scale
    x_off = x + (max_w - w) / 2
    c.drawImage(img, x_off, y_top - h, w, h, preserveAspectRatio=True, mask="auto")
    c.setStrokeColor(HAIR)
    c.setLineWidth(2)
    c.rect(x_off, y_top - h, w, h, stroke=1, fill=0)
    return y_top - h


def main() -> None:
    issue = Issue.model_validate_json(Path("data/artifacts/issue.json").read_text())
    content = json.loads(Path("build/carousel-content.json").read_text())
    out = Path(f"build/priors-carousel-{issue.week}.pdf")
    c = pdfcanvas.Canvas(str(out), pagesize=(W, H))
    date_range = (
        f"{issue.period_start.strftime('%B %-d')} – {issue.period_end.strftime('%B %-d, %Y')}"
    )
    total_stories = sum(len(s.stories) for s in issue.sections)

    # ---- cover ----
    start_slide(c, None, issue.week)
    c.setFont(SERIF, 150)
    c.setFillColor(GREEN)
    c.drawCentredString(W / 2, H - 420, issue.digest_name)
    c.setFont(SERIF_I, 42)
    c.setFillColor(MUTED)
    c.drawCentredString(W / 2, H - 500, issue.tagline)
    c.setStrokeColor(HAIR)
    c.setLineWidth(2)
    c.line(W / 2 - 140, H - 560, W / 2 + 140, H - 560)
    c.setFont(SERIF, 46)
    c.setFillColor(INK)
    c.drawCentredString(W / 2, H - 680, "One week of news,")
    c.drawCentredString(W / 2, H - 742, "with probabilities.")
    c.setFont(SANS, 26)
    c.setFillColor(FAINT)
    c.drawCentredString(W / 2, H - 850, f"{date_range}   ·   {issue.week}")
    c.setFont(SERIF_I, 30)
    c.setFillColor(MUTED)
    c.drawCentredString(W / 2, 240, f"{len(content['slides'])} of this week's "
                                    f"{total_stories} stories, for decision makers.")
    c.setFont(SANS, 22)
    c.setFillColor(FAINT)
    c.drawCentredString(W / 2, 130,
                        "Solid % = live Kalshi market price · outlined % = author's estimate")
    c.showPage()

    # ---- story slides ----
    page = 1
    for slide in content["slides"]:
        page += 1
        start_slide(c, page, issue.week)
        header(c, slide["section"])
        y = H - 190
        y = draw_par(c, slide["headline"], M, y, SERIF, 56, 68, INK, W - 2 * M)
        y -= 26
        y = draw_par(c, slide["what_happened"], M, y, SERIF, 31, 44, MUTED, W - 2 * M)
        y -= 56

        # implications box
        box_top = y
        c.setFont(SANS_B, 24)
        c.setFillColor(GREEN)
        c.drawString(M, y - 30, "IF YOU'RE MAKING DECISIONS THIS WEEK")
        y -= 78
        text_x = M + 176
        text_w = W - M - text_x
        for bullet in slide["bullets"]:
            lines = wrap(bullet["text"], SERIF, 30, text_w)
            block_h = max(len(lines) * 42, 96)
            chip(c, M, y, bullet["probability_pct"], bullet["basis"])
            ty = y + 34 - (block_h - len(lines) * 42) / 2
            draw_par(c, bullet["text"], text_x, ty, SERIF, 30, 42, INK, text_w)
            y -= block_h + 44
        del box_top
        c.showPage()

    # ---- human story ----
    if issue.human_story:
        page += 1
        hs = issue.human_story
        start_slide(c, page, issue.week)
        header(c, "Human story of the week")
        y = H - 190
        y = draw_par(c, hs.headline, M, y, SERIF, 52, 64, INK, W - 2 * M)
        y -= 30
        img = fetch_image(hs.image.url) if hs.image and hs.image.url else None
        if img is not None:
            y = draw_image_fitted(c, img, M, y, W - 2 * M, 360) - 40
        # Body must clear the footer; shrink type until it fits.
        for size, leading in ((30, 44), (27, 39), (24, 35)):
            if y - len(wrap(hs.text, SERIF, size, W - 2 * M)) * leading - 80 > 100:
                break
        y = draw_par(c, hs.text, M, y, SERIF, size, leading, INK, W - 2 * M)
        y -= 40
        c.setFont(SANS, 22)
        c.setFillColor(FAINT)
        c.drawString(M, y, f"Via {hs.source}")
        c.showPage()

    # ---- photo of the week ----
    if issue.photo:
        page += 1
        start_slide(c, page, issue.week)
        header(c, "Photo of the week")
        img = fetch_image(issue.photo.image_url)
        y = H - 190
        if img is not None:
            y = draw_image_fitted(c, img, M, y, W - 2 * M, 760) - 44
        if issue.photo.description:
            y = draw_par(c, issue.photo.description, M, y, SERIF_I, 28, 40, MUTED, W - 2 * M)
            y -= 24
        c.setFont(SANS, 22)
        c.setFillColor(FAINT)
        c.drawString(M, y, f"{issue.photo.attribution} · Wikimedia Commons")
        c.showPage()

    # ---- CTA ----
    page += 1
    start_slide(c, None, issue.week)
    c.setFont(SERIF, 64)
    c.setFillColor(INK)
    c.drawCentredString(W / 2, H - 340, "Want this every Monday?")
    c.setStrokeColor(HAIR)
    c.line(W / 2 - 140, H - 400, W / 2 + 140, H - 400)
    y = H - 500
    for line, font, color in [
        ("Fork it: it's open source.", SERIF, INK),
        ("github.com/patrick-alveos/priors", SANS, GREEN),
        ("Bring your own keys:", SERIF, INK),
        ("Anthropic · GNews · Kalshi · Resend", SERIF, MUTED),
    ]:
        c.setFont(font, 38 if font == SERIF else 32)
        c.setFillColor(color)
        c.drawCentredString(W / 2, y, line)
        y -= 64
    c.setFont(SERIF_I, 36)
    c.setFillColor(GREEN)
    c.drawCentredString(W / 2, y - 60, "Or comment “priors” and I'll turn it")
    c.drawCentredString(W / 2, y - 110, "into a proper newsletter.")
    c.setFont(SERIF, 54)
    c.setFillColor(GREEN)
    c.drawCentredString(W / 2, 200, issue.digest_name)
    c.setFont(SERIF_I, 26)
    c.setFillColor(MUTED)
    c.drawCentredString(W / 2, 150, issue.tagline)
    c.showPage()

    c.save()
    print(f"wrote {out} ({page + 1} slides)")


if __name__ == "__main__":
    main()
