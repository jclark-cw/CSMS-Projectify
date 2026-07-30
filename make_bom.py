#!/usr/bin/env python3
"""Generate a Bill of Materials (Scope of Deliverables) page derived from the
CyberMarketingCon 3-Year Platinum Sponsorship + Partnership agreement with
Content Workshop. One checkbox per deliverable CATEGORY (-> Asana Section);
line items beneath are the task set (-> Asana Tasks). Doubles as DocuSign Doc 2."""

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether,
)

OUT = "/Users/josephclark/Projects/CSMS/CMC26_Bill_of_Materials.pdf"

NAVY = HexColor("#1F2A44")
ACCENT = HexColor("#3B6EA5")
GREEN = HexColor("#2E7D52")
GREY = HexColor("#6B7280")
LIGHT = HexColor("#F1F4F8")
LINE = HexColor("#E3E7ED")

styles = getSampleStyleSheet()

title_style = ParagraphStyle("title", parent=styles["Title"], fontName="Helvetica-Bold",
                             fontSize=19, textColor=NAVY, spaceAfter=2, alignment=TA_CENTER)
subtitle_style = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=10,
                                textColor=GREY, alignment=TA_CENTER, spaceAfter=12)
body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9, leading=13,
                      alignment=TA_JUSTIFY, spaceAfter=5, textColor=HexColor("#222222"))
small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=11, textColor=GREY)
sec_name = ParagraphStyle("sec_name", parent=styles["Normal"], fontName="Helvetica-Bold",
                          fontSize=10.5, leading=13, textColor=NAVY)
sec_label = ParagraphStyle("sec_label", parent=styles["Normal"], fontName="Courier",
                           fontSize=7, leading=10, textColor=HexColor("#9AA3B0"))
item_style = ParagraphStyle("item", parent=styles["Normal"], fontSize=8.5, leading=12,
                            textColor=HexColor("#333333"), leftIndent=2)

story = []

story.append(Paragraph("BILL OF MATERIALS", title_style))
story.append(Paragraph("Scope of Deliverables — drives Asana project build", subtitle_style))
story.append(HRFlowable(width="100%", thickness=1.2, color=ACCENT, spaceAfter=10))

# ---- Deal header ----
hdr = Table(
    [
        [Paragraph("<b>Company</b>", small), Paragraph("______________________________", body),
         Paragraph("<b>Package</b>", small), Paragraph("______________________________", body)],
        [Paragraph("<b>Term</b>", small), Paragraph("______________________________", body),
         Paragraph("<b>Annual Term</b>", small), Paragraph("______________________________", body)],
        [Paragraph("<b>Annual Fee</b>", small), Paragraph("______________________________", body),
         Paragraph("<b>Main Contact</b>", small), Paragraph("______________________________", body)],
    ],
    colWidths=[0.85 * inch, 2.55 * inch, 0.95 * inch, 2.15 * inch],
)
hdr.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
]))
story.append(hdr)
story.append(Spacer(1, 8))
story.append(Paragraph(
    "Check each deliverable category included in this engagement. Each checked category "
    "creates a Section in the Asana project; the line items beneath become its tasks. "
    "Categories left unchecked are not included. <i>(Completed by CMS prior to sending.)</i>", body))
story.append(Spacer(1, 6))

# (section title, data_label, checked?, [line item task strings])
SECTIONS = [
    ("Speaking & Presentation", "dlv_speaking", False, [
        "1× 35–45 min main-stage non-exclusive speaking session (CMS-approved topic/time)",
        "Submit speaking title, abstract & topic by CMC call-for-speakers deadline",
        "Annual speaking upgrade: co-note style (only 1 concurrent session)",
        "Deliver MP4 recording of session with public/repurpose/publish license",
    ]),
    ("Booth & Expo", "dlv_booth", False, [
        "1× 10'×20' Expo Hall booth space",
        "Upgrade: 1× adjacent 10'×10' booth (annual)",
        "Booth priority — first choice among Platinum sponsors",
        "Lead scanning enabled at booth",
        "Virtual booth (largest size)",
        "6× complimentary staff tickets (redeem ≤30 days prior)",
        "4× complimentary prospect/guest tickets (redeem ≤30 days prior)",
    ]),
    ("Media & Content", "dlv_media", False, [
        "1× 'Breaking Through' podcast guest appearance + MP4 with license",
        "1× additional 'Breaking Through' podcast appearance (Annual Extra) + MP4",
        "1× Pre-Conference Interview Video (30–160s promo, ~4 mo. before conf.)",
    ]),
    ("On-Site Marketing & Branding", "dlv_branding_onsite", False, [
        "Swag bag item inclusion (CMS-approved, delivered by deadline)",
        "Daily shout-outs during announcements",
        "Branded rotating-screen slide with custom message + QR code",
        "1× full-page ad in conference program (by CMC deadline)",
        "Logo + link on conference website",
        "Tier 2 branding hierarchy on all signage",
    ]),
    ("CMC Platform & Social Promotion", "dlv_social_cmc", False, [
        "5× social media promotions (valid 18 mo. from term start)",
        "1× advertisement in Spoonful Newsletter (by Dec 31, 2026)",
    ]),
    ("Partnership — Joint Content Collaboration", "dlv_joint_content", False, [
        "2× joint webinars/year (+ registrant contact info, video files, blog recap)",
        "Option to convert webinar(s) to alternate activation (pre-approved)",
        "AI product / Cyber Link Exchange promo: 1 blog post w/ backlinks + 4 social posts",
        "Joint blog series: 2 collaborative blogs (1 on CMS site, 1 on Company site)",
    ]),
    ("Partnership — CMS Platform Marketing", "dlv_partner_marketing", False, [
        "12× social posts (any format) on CMS LinkedIn",
        "6× email advertisements in Spoonful Newsletter",
        "12× promotions in CMS private member community (~1×/month)",
    ]),
    ("Partnership — Recognition & Visibility", "dlv_recognition", False, [
        "Listing on CMS Partner page as Official Partner",
        "Cyber Link Exchange listed as a Perk on CMS Partner Perks page",
    ]),
    ("Events & Experiences", "dlv_events", False, [
        "Group outing planning support (CMS retains final authority)",
        "Non-exclusive Group Outing sponsor",
        "1× meeting room/space during peak conference days (seating + table)",
        "Right of first refusal on regional events & meetups",
        "Bespoke matchmaking arrangement — details TBD (additional cost)",
    ]),
    ("Discounts & Added Value", "dlv_discounts", False, [
        "15% off additional sponsorship opportunities (CMC 2026)",
        "20% off additional tickets (CMC 2026)",
        "25% off attendee giveaway tickets (CMC 2026)",
    ]),
    ("Barter — Content Workshop → CMS", "dlv_barter", False, [
        "$20k/yr of services CMS chooses (web design/maint., blogs, whitepapers, video, digital)",
        "1× video customer testimonial per Annual Term (captured & edited by CMS)",
    ]),
]


def checkbox(checked):
    t = Table([["X" if checked else ""]], colWidths=[0.17 * inch], rowHeights=[0.17 * inch])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.9, NAVY),
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#FFFFFF")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), GREEN),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t


for title, label, checked, items in SECTIONS:
    block = []
    # header row: checkbox | section name | data label
    head = Table(
        [[checkbox(checked),
          Paragraph(title, sec_name),
          Paragraph(label, sec_label)]],
        colWidths=[0.32 * inch, 4.35 * inch, 1.83 * inch],
    )
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (0, 0), 6), ("LEFTPADDING", (1, 0), (1, 0), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, ACCENT),
    ]))
    block.append(head)
    # task rows
    rows = [[Paragraph("•", item_style), Paragraph(it, item_style)] for it in items]
    tbl = Table(rows, colWidths=[0.45 * inch, 6.05 * inch])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (0, -1), 22), ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("TEXTCOLOR", (0, 0), (0, -1), ACCENT),
    ]))
    block.append(tbl)
    block.append(Spacer(1, 8))
    story.append(KeepTogether(block))

story.append(Spacer(1, 4))
story.append(HRFlowable(width="100%", thickness=0.5, color=LINE, spaceAfter=8))
story.append(Paragraph(
    "The grey monospace labels (e.g. <font face='Courier' size=7>dlv_speaking</font>) mirror the "
    "DocuSign field <b>Data Labels</b> and the Zapier Table keys; shown for testing only — remove "
    "from any client-facing version. Quantities in task lines (5×, 12×, etc.) carry into Asana task "
    "names so fulfillment counts stay visible.", small))

doc = SimpleDocTemplate(
    OUT, pagesize=letter,
    leftMargin=0.85 * inch, rightMargin=0.85 * inch,
    topMargin=0.7 * inch, bottomMargin=0.7 * inch,
    title="CMC26 — Bill of Materials",
    author="Cybersecurity Marketing Society LLC",
)


def footer(canvas, d):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GREY)
    canvas.drawString(0.85 * inch, 0.5 * inch,
                      "CyberMarketingCon — Bill of Materials — Confidential")
    canvas.drawRightString(7.65 * inch, 0.5 * inch, f"Page {d.page}")
    canvas.restoreState()


doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
