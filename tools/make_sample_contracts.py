#!/usr/bin/env python3
"""Generate synthetic sample contracts for testing the parser / Projectify UI.

These are FAKE contracts (made-up sponsors, no real data) that follow the
formatting standard in CONTRACT_FORMATTING.md, so they exercise the parser and
give a colleague something to drag into the app without touching a real,
PII-laden contract. Output → samples/.

Run:  python3 tools/make_sample_contracts.py

The parser keys on literal bullet glyphs (●/▪/•) and a Courier 'o', so glyphs are
drawn from a Unicode TTF and the 'o' bullet from base-14 Courier.
"""

import os
import sys
from pathlib import Path

from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import letter

ARIAL_UNI = "/Library/Fonts/Arial Unicode.ttf"
SAMPLES = Path(__file__).resolve().parent.parent / "samples"

# kind -> (glyph, glyph_x, glyph_font, text_font, text_x, size, leading)
STYLES = {
    "title":       (None, None, None,       "Times-Bold",  120, 16, 24),
    "preamble":    (None, None, None,       "Times-Roman",  72, 11, 18),
    "group":       (None, None, None,       "Times-Bold",   72, 14, 26),
    "intro":       (None, None, None,       "Times-Bold",   72, 11, 20),
    "sectionline": (None, None, None,       "Times-Bold",   72, 11, 20),
    "section":     ("●", 72, "ArialUni", "Times-Bold", 90, 11, 20),
    "perk":        ("•", 100, "ArialUni", "Times-Roman", 116, 11, 18),
    "task":        ("o",     110, "Courier",  "Times-Roman", 126, 11, 18),
    "note":        ("▪", 150, "ArialUni", "Times-Roman", 166, 10, 16),
    "para":        (None, None, None,       "Times-Roman", 126, 11, 18),
    "stop":        (None, None, None,       "Times-Bold",   72, 11, 22),
}


def render(path: Path, elements: list) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    y = 720
    for kind, text in elements:
        if y < 90:
            c.showPage()
            y = 720
        glyph, gx, gfont, tfont, tx, size, leading = STYLES[kind]
        if glyph:
            c.setFont(gfont, size)
            c.drawString(gx, y, glyph)
        c.setFont(tfont, size)
        c.drawString(tx, y, text)
        y -= leading
    c.save()


ACME = [
    ("title", "SPONSORSHIP & EXHIBITOR AGREEMENT"),
    ("preamble", "This Sponsorship Agreement is entered into between CyberCon LLC and Acme Robotics Inc."),
    ("preamble", "COMPANY NAME: Acme Robotics Inc.   MAIN CONTACT: Dana Lee"),
    ("group", "2026 Platinum Sponsor Benefits"),
    ("section", "Speaking and Presentation Opportunities"),
    ("task", "One (1) 40-minute main-stage keynote session"),
    ("note", "Topic and speakers approved by host"),
    ("task", "Recorded MP4 of the session for company use"),
    ("section", "Booth and Expo Benefits"),
    ("task", "One (1) 10x10 booth in the expo hall"),
    ("task", "Four (4) complimentary staff passes"),
    ("note", "Redeemable up to 30 days before the event"),
    ("section", "Media and Content"),
    ("task", "One (1) guest podcast appearance"),
    ("group", "Annual Extras"),
    ("perk", "Podcast Sponsorship: one additional guest episode per year"),
    ("perk", "Meeting Room: private room during peak conference days"),
    ("stop", "Payment Schedule"),
    ("preamble", "Total Fees: $65,000 due in year one."),
]

GLOBEX = [
    ("title", "CYBERCON SPONSORSHIP / EXHIBITOR AGREEMENT"),
    ("preamble", "This Agreement is entered into between CyberCon LLC and Globex Media Group."),
    ("preamble", "COMPANY NAME: Globex Media Group   MAIN CONTACT: Sam Ortiz"),
    ("intro", "YOUR SPONSORSHIP PACKAGE SHALL INCLUDE ALL OF THE FOLLOWING:"),
    ("perk", "Exhibit Table"),
    ("task", "One (1) 6ft table and two (2) chairs"),
    ("note", "Located in the main hall"),
    ("task", "Power and wifi included"),
    ("perk", "Tech Talk"),
    ("task", "15-minute stage session in the expo theater"),
    ("task", "Recording shared after the event"),
    ("perk", "Three (3) complimentary conference tickets"),
    ("para", "Valued at approximately $4,500, redeemable by Oct 1."),
    ("stop", "Total Amount Payable"),
    ("preamble", "$28,000 due upon signing."),
]

INITECH = [
    ("title", "PARTNERSHIP AGREEMENT"),
    ("preamble", "This Agreement is entered into between CyberCon LLC and Initech Security."),
    ("group", "Annual Partnership Benefits"),
    ("sectionline", "Joint Content Collaboration"),
    ("task", "Two (2) co-hosted webinars per year"),
    ("note", "Valid for 12 months after term start"),
    ("task", "Joint blog series with backlinks"),
    ("sectionline", "Brand Visibility"),
    ("task", "Logo on the conference website"),
    ("task", "Tier-2 placement on event signage"),
    ("group", "Added Value"),
    ("perk", "Workshop Credit: one private training session"),
    ("stop", "Terms and Conditions"),
]

CONTRACTS = {
    "sample_acme_grouped.pdf": ACME,
    "sample_globex_flat.pdf": GLOBEX,
    "sample_initech_grouped.pdf": INITECH,
}


def main() -> int:
    if not os.path.exists(ARIAL_UNI):
        print(f"error: need a Unicode TTF at {ARIAL_UNI}", file=sys.stderr)
        return 1
    pdfmetrics.registerFont(TTFont("ArialUni", ARIAL_UNI))
    SAMPLES.mkdir(exist_ok=True)
    for name, elements in CONTRACTS.items():
        render(SAMPLES / name, elements)
        print(f"wrote samples/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
