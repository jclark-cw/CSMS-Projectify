#!/usr/bin/env python3
"""
csms.parser — Extract deliverable sections and tasks from a sponsorship contract PDF.

Finds deliverable content by detecting bold group headers, then maps:
  • Bold ● (disc) bullets and standalone bold lines → Asana Sections
  • Courier 'o' bullets, • (perk) bullets, and non-bold ● bullets → Asana Tasks
  • Sub-sub-bullet items (▪) → Task Notes on the preceding task

Pure, offline PDF parsing — no network, no rendering, no JS execution.
Public API: parse_contract(pdf_path) -> list[dict], to_csv_rows(sections) -> list[dict].
"""

from pathlib import Path

import pdfplumber


# Font name fragments that indicate bold text
_BOLD_MARKERS = ("bold", "boldmt", "bolditalic", "black", "heavy")

# Text patterns that signal the end of deliverable content
STOP_PATTERNS = (
    "payment schedule",
    "payment terms",
    "section 1.",
    "section 2.",
    "terms and conditions",
    "representations and warranties",
    "indemnification",
    "limitation of liability",
    "governing law",
    "entire agreement",
    "in witness whereof",
    "force majeure",
    "will remit",          # "COMPANY WILL REMIT … PAYMENT" — payment block
    "amount payable",
)

# Strong, specific phrases that introduce a deliverables block. Kept narrow on
# purpose: generic category words ("annual extras", "sponsorship benefits") appear
# as noise in package-summary lists and cause false starts. These phrases let the
# parser engage on flat contracts that have no large bold group header.
START_PATTERNS = (
    "shall include all of the following",
    "include all of the following",
    "shall include the following",
    "package shall include",
)


def _is_bold(fontname: str) -> bool:
    fn = fontname.lower()
    return any(m in fn for m in _BOLD_MARKERS)


def _group_into_lines(words: list, y_tolerance: float = 4.0) -> list:
    """Cluster words into visual lines by y-coordinate proximity.

    Bullet markers (e.g. Courier 'o') often sit 2-3pt below their text in PDF
    coordinates even though they appear on the same visual line.  After grouping
    we re-sort each line by x0 so the bullet glyph (leftmost) is always first.
    """
    if not words:
        return []
    # Primary sort: top then x so we can assign lines in reading order
    words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines, current = [], [words[0]]
    current_y = words[0]["top"]
    for w in words[1:]:
        if abs(w["top"] - current_y) <= y_tolerance:
            current.append(w)
        else:
            # Re-sort within the line by x0 so bullets precede their text
            lines.append(sorted(current, key=lambda w: w["x0"]))
            current = [w]
            current_y = w["top"]
    lines.append(sorted(current, key=lambda w: w["x0"]))
    return lines


def _bold_lead(content_words: list) -> str:
    """Extract the leading run of bold words before the first non-bold word."""
    run = []
    for w in content_words:
        if _is_bold(w["fontname"]):
            run.append(w["text"])
        else:
            break
    return " ".join(run).rstrip(":- ").strip()


def _is_mostly_upper(text: str) -> bool:
    """True when >70 % of alpha chars are uppercase (contract title noise)."""
    alpha = [c for c in text if c.isalpha()]
    return bool(alpha) and sum(c.isupper() for c in alpha) / len(alpha) > 0.70


def _classify_line(words: list) -> tuple:
    """
    Return (role, cleaned_text, x_indent).

    Roles:
      group_header  — large bold h2-level heading introducing a deliverable group
      section       — bold ● (disc) bullet header; becomes an Asana Section
      section_line  — standalone bold line (no bullet); a Section, mergeable when the
                      previous section is still empty (handles wrapped headings)
      item          — • (SymbolMT) leaf perk; becomes a Task, split name:notes on ':'
      task          — Courier 'o' bullet or non-bold ● bullet; becomes an Asana Task
      detail        — item after a ▪ marker; becomes Task Notes on the previous task
      paragraph     — regular text; used for line-continuation joins
      ignore        — page numbers, DocuSign stamps, empty
    """
    if not words:
        return "ignore", "", 0.0

    # Ignore lines that are pure Calibri/Arial (page numbers, DocuSign stamps)
    meaningful = [w for w in words
                  if "calibri" not in w["fontname"].lower()
                  and "arial" not in w["fontname"].lower()]
    if not meaningful:
        return "ignore", "", 0.0

    first = words[0]
    first_text = first["text"].strip()
    first_font = first["fontname"].lower()

    is_o_bullet = "courier" in first_font and first_text == "o"
    is_triangle = first_text == "▪"
    # The contract uses two distinct bullet glyphs at different levels:
    #   • (SymbolMT)  → a leaf perk  → Task   (e.g. Annual Extras items)
    #   ● (Calibri)   → a category   → Section when bold, Task when plain
    is_perk_bullet = first_text == "•" or "symbol" in first_font
    is_disc_bullet = first_text in ("●", "○", "◦")
    is_symbol_bullet = is_perk_bullet or is_disc_bullet

    bullet_chars = {"o", "•", "●", "○", "◦", "▪"}
    content_words = [w for w in words if w["text"] not in bullet_chars]
    if not content_words:
        return "ignore", "", 0.0

    x_indent = content_words[0]["x0"]
    text = " ".join(w["text"] for w in content_words).strip()

    max_size = max(w["size"] for w in content_words)
    bold_count = sum(1 for w in content_words if _is_bold(w["fontname"]))
    bold_ratio = bold_count / len(content_words)

    # ── Group header ─────────────────────────────────────────────────────────
    # Large bold text; skip all-caps titles (contract headings, not deliverables)
    if max_size >= 13 and bold_ratio > 0.4:
        if _is_mostly_upper(text):
            return "paragraph", text, x_indent  # noise: contract title
        return "group_header", text, x_indent

    # ── Task: Courier 'o' bullet ─────────────────────────────────────────────
    if is_o_bullet:
        return "task", text, x_indent

    # ── Detail: ▪ marker → Task Notes ────────────────────────────────────────
    if is_triangle:
        return "detail", text, x_indent

    # ── Perk: • leaf bullet → Task (name:notes split on ':' in the caller) ────
    # (e.g. "• Group Outing Planning Support: ..." in Annual Extras)
    if is_perk_bullet:
        return "item", text, x_indent

    # ── Section: ● disc bullet with bold content ("● Booth and Expo Benefits") ─
    if is_disc_bullet and bold_ratio > 0.4:
        return "section", text, x_indent

    # ● disc bullet with a bold lead label (rare) → Section label
    if is_disc_bullet and _is_bold(content_words[0]["fontname"]):
        label = _bold_lead(content_words)
        if label:
            return "section", label, x_indent

    # ● disc bullet, non-bold → Task (e.g. Barter "$20k...", "video testimonial")
    if is_disc_bullet:
        return "task", text, x_indent

    # ── Section line: standalone bold line, no bullet ────────────────────────
    # (e.g. "Speaking and Presentation Opportunities"). Mergeable wrapped heading.
    if not is_symbol_bullet and not is_o_bullet and not is_triangle and bold_ratio > 0.4:
        return "section_line", text, x_indent

    return "paragraph", text, x_indent


class InvalidPDFError(ValueError):
    """Raised when an input file fails basic PDF validation."""


def validate_pdf(pdf_path: str, max_mb: float = 25.0) -> None:
    """Guard the untrusted-input boundary before handing a file to pdfplumber.

    Cheap defenses against malformed/oversized uploads: confirm the file exists,
    is within a sane size, and starts with the %PDF magic bytes. (A parse-time
    timeout against decompression bombs is deferred to the ingestion layer —
    the upload app / engine — where it can be enforced per request.)
    """
    p = Path(pdf_path)
    if not p.is_file():
        raise InvalidPDFError(f"not a file: {pdf_path}")
    size_mb = p.stat().st_size / (1024 * 1024)
    if size_mb > max_mb:
        raise InvalidPDFError(f"file too large: {size_mb:.1f} MB > {max_mb} MB limit")
    with p.open("rb") as f:
        if f.read(5) != b"%PDF-":
            raise InvalidPDFError("missing %PDF- header — not a PDF")


def _item_has_task_children(classified: list, i: int) -> bool:
    """Does the • item at index i have 'o' task children before the next item/section?

    Used only in flat contracts (no group headers) to tell a deliverable *header*
    (e.g. "• 15-Minute Tech Talk" followed by o-bullets) from a leaf perk
    (e.g. "• 3 complimentary tickets" followed by prose). Skips continuation
    paragraphs and ▪ details; the first structural role decides.
    """
    for role, _, _ in classified[i + 1:]:
        if role in ("paragraph", "detail", "ignore"):
            continue
        return role == "task"
    return False


def parse_contract(pdf_path: str, max_pages: int = 100,
                   max_words: int = 200_000) -> list:
    """
    Parse a sponsorship contract PDF and return structured deliverable data.

    Returns a list of dicts:
      {
        "group":   "Group Header (e.g. Annual Extras)",
        "section": "Section Name (e.g. Booth and Expo Benefits)",
        "tasks":   [{"name": "Task 1", "notes": "..."}, ...],
      }

    max_pages/max_words bound the work a single file can cause. validate_pdf's
    size check is not enough on its own: a small, highly-compressed PDF can still
    expand into an enormous word count and pin CPU here. Real contracts are a few
    pages and a few thousand words, so these limits are far above legitimate input
    and exist only to make a pathological file fail fast instead of hanging.
    """
    results = []
    current_group = None
    current_section = None
    current_tasks = []   # each task is {"name": str, "notes": str}
    in_deliverables = False
    # Track task indent (to join wrapped continuation lines) and whether the most
    # recent text landed on a task's name or its notes.
    last_task_indent = None
    last_target = "name"             # "name" | "notes"

    def flush():
        nonlocal current_section, current_tasks, last_task_indent, last_target
        # Drop empty sections — e.g. a flat contract's "…SHALL INCLUDE ALL OF THE
        # FOLLOWING:" intro line, or a wrapped heading whose first half merged away.
        if current_section is not None and current_tasks:
            results.append({
                "group":   current_group or "",
                "section": current_section,
                "tasks":   list(current_tasks),
            })
        current_section = None
        current_tasks = []
        last_task_indent = None
        last_target = "name"

    with pdfplumber.open(pdf_path) as pdf:
        if len(pdf.pages) > max_pages:
            raise InvalidPDFError(
                f"too many pages: {len(pdf.pages)} > {max_pages} limit")
        classified = []
        word_count = 0
        for page in pdf.pages:
            words = page.extract_words(extra_attrs=["fontname", "size"])
            # Checked per page, not per document: the point is to bail out partway
            # through a pathological file, not to discover after parsing all of it.
            word_count += len(words)
            if word_count > max_words:
                raise InvalidPDFError(
                    f"too much text: over {max_words} words — not a contract")
            for line_words in _group_into_lines(words):
                classified.append(_classify_line(line_words))

    # Grouped contracts begin at a large bold group header; flat contracts have
    # none, so fall back to a strong "shall include all of the following" intro.
    # Deciding once, up front, stops a grouped contract's summary preamble (which
    # can contain that same phrase) from triggering an early, wrong start.
    has_group_header = any(role == "group_header" for role, _, _ in classified)

    for idx, (role, text, indent) in enumerate(classified):
        text_lower = text.lower()

        # Stop when we reach legal boilerplate
        if in_deliverables and any(p in text_lower for p in STOP_PATTERNS):
            flush()
            in_deliverables = False
            continue

        # Start collecting at the document's chosen entry signal.
        if not in_deliverables:
            if has_group_header:
                started = role == "group_header"
            else:
                started = any(p in text_lower for p in START_PATTERNS)
            if started:
                in_deliverables = True
            else:
                continue

        if role == "group_header":
            flush()
            current_group = text

        elif role == "section":
            flush()
            current_section = text

        elif role == "section_line":
            # A standalone bold line. If the current section is still empty,
            # this is a wrapped continuation of that heading (e.g. "IN ADDITION,
            # … WILL PROVIDE THE FOLLOWING TO" + "CMS ANNUALLY AS BARTER:") → merge.
            if current_section is not None and not current_tasks:
                current_section += " " + text
            else:
                flush()
                current_section = text

        elif role == "item":
            if not has_group_header and _item_has_task_children(classified, idx):
                # Flat contract: a • that owns 'o' sub-tasks is a deliverable
                # header → Section (e.g. "• 15-Minute Tech Talk" + its o-bullets).
                flush()
                current_section = text.rstrip(": ")
            else:
                # Leaf perk → Task. In grouped contracts • is always a leaf; in flat
                # contracts a childless • (e.g. "• 3 complimentary tickets") is too.
                # Items can sit directly under a group with no section of their own
                # (Annual Extras), so fall back to the group name.
                if current_section is None:
                    current_section = current_group or text
                name, _, rest = text.partition(":")
                current_tasks.append({"name": name.strip(), "notes": rest.strip()})
                last_task_indent = indent
                last_target = "notes"  # following description lines are notes

        elif role == "task":
            # Tasks normally follow a section; fall back to the group name if a
            # task appears with no section yet (e.g. a bare 'o' under a group).
            if current_section is None:
                current_section = current_group or text
            current_tasks.append({"name": text, "notes": ""})
            last_task_indent = indent
            last_target = "name"

        elif role == "detail":
            # ▪ sub-details become Task Notes on the most recent task.
            if current_tasks:
                existing = current_tasks[-1]["notes"]
                current_tasks[-1]["notes"] = (
                    existing + "\n" + text if existing else text
                )
                last_task_indent = indent
                last_target = "notes"

        elif role == "paragraph":
            # Join wrapped continuation lines onto the most recent task's name
            # or notes (whichever the last item was). Continuation lines share
            # the task's indent (≥ last_task_indent); top-level intro text sits
            # at the left margin and is skipped.
            if (current_tasks
                    and last_task_indent is not None
                    and indent >= last_task_indent - 5):
                if last_target == "notes":
                    current_tasks[-1]["notes"] += " " + text
                else:
                    current_tasks[-1]["name"] += " " + text

        # role == "ignore": skip

    flush()
    return results


def to_csv_rows(sections: list) -> list:
    """Flatten the parsed structure into one row per task."""
    rows = []
    for entry in sections:
        for task in entry["tasks"]:
            rows.append({
                "group":        entry["group"],
                "section_name": entry["section"],
                "task_name":    task["name"],
                "task_notes":   task["notes"],
            })
        if not entry["tasks"]:
            rows.append({
                "group":        entry["group"],
                "section_name": entry["section"],
                "task_name":    "",
                "task_notes":   "",
            })
    return rows
