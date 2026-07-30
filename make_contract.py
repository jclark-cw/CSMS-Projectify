#!/usr/bin/env python3
"""Generate a sample marketing-conference services agreement with a
checkbox-based Scope of Work section. Doubles as a DocuSign test document."""

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

OUT = "/Users/josephclark/Projects/Marketing_Conference_Services_Agreement.pdf"

NAVY = HexColor("#1F2A44")
ACCENT = HexColor("#3B6EA5")
GREY = HexColor("#6B7280")
LIGHT = HexColor("#F1F4F8")

styles = getSampleStyleSheet()

title_style = ParagraphStyle(
    "title", parent=styles["Title"], fontName="Helvetica-Bold",
    fontSize=20, textColor=NAVY, spaceAfter=2, alignment=TA_CENTER,
)
subtitle_style = ParagraphStyle(
    "subtitle", parent=styles["Normal"], fontSize=10, textColor=GREY,
    alignment=TA_CENTER, spaceAfter=14,
)
h2 = ParagraphStyle(
    "h2", parent=styles["Heading2"], fontName="Helvetica-Bold",
    fontSize=12, textColor=NAVY, spaceBefore=14, spaceAfter=6,
)
body = ParagraphStyle(
    "body", parent=styles["Normal"], fontSize=9.5, leading=14,
    alignment=TA_JUSTIFY, spaceAfter=6, textColor=HexColor("#222222"),
)
small = ParagraphStyle(
    "small", parent=styles["Normal"], fontSize=8.5, leading=12, textColor=GREY,
)
deliverable_style = ParagraphStyle(
    "deliverable", parent=styles["Normal"], fontSize=9.5, leading=13,
)
deliverable_desc = ParagraphStyle(
    "ddesc", parent=styles["Normal"], fontSize=8, leading=11, textColor=GREY,
)
label_style = ParagraphStyle(
    "label", parent=styles["Normal"], fontSize=8, textColor=GREY,
    fontName="Helvetica-Oblique",
)

story = []

# ---- Header ----
story.append(Paragraph("MARKETING &amp; EVENT SERVICES AGREEMENT", title_style))
story.append(Paragraph("Conference Marketing Engagement", subtitle_style))
story.append(HRFlowable(width="100%", thickness=1.2, color=ACCENT, spaceAfter=12))

# ---- Parties ----
parties = Table(
    [
        [Paragraph("<b>Agency</b>", small), Paragraph("<b>Client</b>", small)],
        [
            Paragraph("Summit &amp; Spark Marketing, LLC<br/>"
                      "1450 Market Street, Suite 600<br/>"
                      "Denver, CO 80202", body),
            Paragraph("____________________________<br/>"
                      "____________________________<br/>"
                      "____________________________", body),
        ],
    ],
    colWidths=[3.25 * inch, 3.25 * inch],
)
parties.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
    ("LINEBELOW", (0, 0), (-1, 0), 0.5, ACCENT),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 6),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ("LEFTPADDING", (0, 0), (-1, -1), 8),
]))
story.append(parties)
story.append(Spacer(1, 10))

story.append(Paragraph(
    "This Marketing &amp; Event Services Agreement (the “Agreement”) is entered "
    "into as of ______________, 20____ (the “Effective Date”) by and between "
    "Summit &amp; Spark Marketing, LLC (the “Agency”) and the Client identified above. "
    "The Agency will provide marketing services in support of the Client’s conference "
    "or event (the “Event”) as described in the Scope of Work below.", body))

# ---- Engagement details ----
story.append(Paragraph("1. Engagement Summary", h2))
details = Table(
    [
        [Paragraph("<b>Event Name</b>", small), Paragraph("____________________________", body),
         Paragraph("<b>Event Dates</b>", small), Paragraph("________________", body)],
        [Paragraph("<b>Venue / Location</b>", small), Paragraph("____________________________", body),
         Paragraph("<b>Expected Attendance</b>", small), Paragraph("________________", body)],
    ],
    colWidths=[1.3 * inch, 2.1 * inch, 1.5 * inch, 1.6 * inch],
)
details.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ("LINEBELOW", (0, 0), (-1, -1), 0.4, HexColor("#D9DEE6")),
]))
story.append(details)

# ---- Scope of Work / Deliverables ----
story.append(Paragraph("2. Scope of Work — Deliverables", h2))
story.append(Paragraph(
    "The services covered by this Agreement are those checked below. Items left "
    "unchecked are not included in this engagement and may be added by written "
    "amendment. <i>(To be completed by Agency prior to sending.)</i>", body))
story.append(Spacer(1, 4))

# Each row: checkbox glyph, deliverable name + desc, data-label hint
deliverables = [
    ("deliverable_event_branding", "Event Branding &amp; Identity",
     "Logo, color system, typography, and visual theme for the event."),
    ("deliverable_website", "Event Website &amp; Registration Page",
     "Landing page, agenda pages, and registration / ticketing setup."),
    ("deliverable_email_campaign", "Email Marketing Campaign",
     "Announcement, reminder, and post-event email sequences."),
    ("deliverable_social_media", "Social Media Campaign",
     "Content calendar, graphics, and paid/organic promotion across channels."),
    ("deliverable_print_collateral", "Printed Collateral &amp; Signage",
     "Badges, programs, banners, booth graphics, and on-site signage."),
    ("deliverable_sponsorship", "Sponsorship &amp; Exhibitor Materials",
     "Sponsor decks, prospectus, and exhibitor kits."),
    ("deliverable_presentation", "Presentation &amp; Slide Templates",
     "Branded keynote / session slide templates and speaker guidelines."),
    ("deliverable_video_photo", "Video &amp; Photography",
     "Promo video, on-site photography, and session recording highlights."),
    ("deliverable_press_pr", "Press &amp; Public Relations",
     "Press release, media list outreach, and media kit."),
    ("deliverable_post_event_report", "Post-Event Analytics &amp; Report",
     "Performance dashboard, attendee survey, and wrap-up report."),
]

rows = []
for data_label, name, desc in deliverables:
    cell = Paragraph(f"<b>{name}</b><br/>"
                     f"<font size=8 color='#6B7280'>{desc}</font>", deliverable_style)
    label = Paragraph(data_label, label_style)
    # empty checkbox box drawn via a small table cell styled with a border
    rows.append(["", cell, label])

scope = Table(rows, colWidths=[0.32 * inch, 4.3 * inch, 1.9 * inch])
scope_style = [
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 7),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ("LEFTPADDING", (1, 0), (1, -1), 6),
    ("LINEBELOW", (0, 0), (-1, -2), 0.4, HexColor("#E3E7ED")),
    ("VALIGN", (2, 0), (2, -1), "MIDDLE"),
    ("TEXTCOLOR", (2, 0), (2, -1), GREY),
]
# draw a checkbox square in the first column of each row
for i in range(len(rows)):
    scope_style.append(("BOX", (0, i), (0, i), 0.0, LIGHT))
scope.setStyle(TableStyle(scope_style))


# Custom flowable approach for checkbox: simpler to overlay squares.
# Instead, replace first column with a drawn square using a mini-table.
def checkbox_cell():
    t = Table([[""]], colWidths=[0.16 * inch], rowHeights=[0.16 * inch])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.9, NAVY),
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#FFFFFF")),
    ]))
    return t


rows2 = []
for data_label, name, desc in deliverables:
    cell = Paragraph(f"<b>{name}</b><br/>"
                     f"<font size=8 color='#6B7280'>{desc}</font>", deliverable_style)
    label = Paragraph(f"<font face='Courier' size=7 color='#9AA3B0'>{data_label}</font>",
                      deliverable_desc)
    rows2.append([checkbox_cell(), cell, label])

scope = Table(rows2, colWidths=[0.34 * inch, 4.25 * inch, 1.95 * inch])
scope.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 8),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ("LEFTPADDING", (1, 0), (1, -1), 8),
    ("VALIGN", (2, 0), (2, -1), "TOP"),
    ("LINEBELOW", (0, 0), (-1, -2), 0.4, HexColor("#E3E7ED")),
]))
story.append(scope)
story.append(Spacer(1, 4))
story.append(Paragraph(
    "The grey monospace labels above mirror the DocuSign field <i>Data Labels</i> "
    "and are shown here for testing only; remove them from the client-facing version.",
    small))

# ---- Fees ----
story.append(Paragraph("3. Fees &amp; Payment", h2))
story.append(Paragraph(
    "Total fees for the checked deliverables are $______________, invoiced as 50% "
    "upon execution of this Agreement and 50% upon completion of the Event. Invoices "
    "are due within fifteen (15) days of receipt. Third-party costs (printing, media "
    "spend, venue, talent) are billed separately at cost.", body))

# ---- Term / boilerplate (brief) ----
story.append(Paragraph("4. Term &amp; Termination", h2))
story.append(Paragraph(
    "This Agreement begins on the Effective Date and continues until the deliverables "
    "are completed and the Event concludes. Either party may terminate with fourteen "
    "(14) days’ written notice; the Client remains responsible for work performed "
    "and costs committed through the termination date.", body))

story.append(Paragraph("5. Ownership &amp; Confidentiality", h2))
story.append(Paragraph(
    "Upon full payment, final delivered materials become the property of the Client. "
    "The Agency retains the right to display the work in its portfolio. Each party "
    "agrees to keep the other’s non-public information confidential.", body))

# ---- Signatures ----
story.append(Spacer(1, 16))
story.append(HRFlowable(width="100%", thickness=0.6, color=HexColor("#D9DEE6"), spaceAfter=12))
sig = Table(
    [
        [Paragraph("<b>Agency</b>", small), Paragraph("<b>Client</b>", small)],
        [Spacer(1, 26), Spacer(1, 26)],
        [Paragraph("___________________________", body),
         Paragraph("___________________________", body)],
        [Paragraph("Signature / Date", small), Paragraph("Signature / Date", small)],
        [Spacer(1, 14), Spacer(1, 14)],
        [Paragraph("___________________________", body),
         Paragraph("___________________________", body)],
        [Paragraph("Printed Name / Title", small), Paragraph("Printed Name / Title", small)],
    ],
    colWidths=[3.25 * inch, 3.25 * inch],
)
sig.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
    ("TOPPADDING", (0, 0), (-1, -1), 2),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
]))
story.append(sig)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GREY)
    canvas.drawString(0.85 * inch, 0.5 * inch,
                      "Summit & Spark Marketing, LLC — Confidential")
    canvas.drawRightString(7.65 * inch, 0.5 * inch, f"Page {doc.page}")
    canvas.restoreState()


doc = SimpleDocTemplate(
    OUT, pagesize=letter,
    leftMargin=0.85 * inch, rightMargin=0.85 * inch,
    topMargin=0.7 * inch, bottomMargin=0.7 * inch,
    title="Marketing & Event Services Agreement",
    author="Summit & Spark Marketing, LLC",
)
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
