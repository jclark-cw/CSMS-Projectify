#!/usr/bin/env python3
"""Golden + structural tests for csms.parser, pinned to the real CMC26 contract.

Runs under pytest (`pytest`) or standalone (`python3 tests/test_parser.py`).
The contract PDF is git-ignored (it's a signed document); when it is absent the
PDF-dependent tests skip rather than fail, but the committed golden fixture keeps
the expected structure under version control.
"""

import sys
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from csms.parser import (  # noqa: E402
    parse_contract, to_csv_rows, validate_pdf, InvalidPDFError)
from csms.engine import (  # noqa: E402
    build_project, plan_to_dict, format_plan_text,
    BuildPlan, SectionPlan, TaskPlan)

CONTRACT_PDF = REPO_ROOT / "CW Contracts" / \
    "CMC26_+_Partnership_-_Content_Workshop_-_1-11-2026.pdf"
GOLDEN = REPO_ROOT / "tests" / "golden" / "cmc26.json"

# A structurally different (flat, no group headers) contract — guards the
# mode-dependent • handling. Git-ignored; tests skip when it is absent.
CONTRACT2_PDF = REPO_ROOT / "2nd Contract.pdf"

_HAVE_PDF = CONTRACT_PDF.exists()
_HAVE_PDF2 = CONTRACT2_PDF.exists()

try:
    import pytest
    _skip_no_pdf = pytest.mark.skipif(not _HAVE_PDF, reason="contract PDF not present")
    _skip_no_pdf2 = pytest.mark.skipif(not _HAVE_PDF2, reason="2nd contract not present")
except ImportError:  # standalone mode: no-op decorators
    def _skip_no_pdf(fn):
        return fn

    def _skip_no_pdf2(fn):
        return fn


def _parsed():
    return parse_contract(str(CONTRACT_PDF))


@_skip_no_pdf
def test_matches_golden():
    """Byte-for-byte regression net: parser output == committed golden fixture."""
    got = _parsed()
    expected = json.loads(GOLDEN.read_text())
    assert got == expected, "parser output drifted from tests/golden/cmc26.json"


@_skip_no_pdf
def test_section_count_and_no_empty_sections():
    data = _parsed()
    assert len(data) == 12
    empties = [e["section"] for e in data if not e["tasks"]]
    assert empties == [], f"unexpected empty sections: {empties}"


@_skip_no_pdf
def test_annual_extras_is_one_section_of_tasks():
    """Annual Extras perks (• bullets) collapse into one section, not 7 empties."""
    data = _parsed()
    extras = [e for e in data if e["section"] == "Annual Extras"]
    assert len(extras) == 1
    assert len(extras[0]["tasks"]) == 8
    # most perks carry their description as a note
    assert sum(1 for t in extras[0]["tasks"] if t["notes"]) >= 6


@_skip_no_pdf
def test_in_addition_and_barter_merged():
    """The wrapped heading 'IN ADDITION … AS BARTER:' is a single section."""
    data = _parsed()
    barter = [e for e in data if "BARTER" in e["section"]]
    assert len(barter) == 1
    assert "IN ADDITION" in barter[0]["section"]
    assert len(barter[0]["tasks"]) == 8


@_skip_no_pdf
def test_triangle_details_become_task_notes():
    """The ▪ line under the Speaking session becomes a note, not a dropped line."""
    data = _parsed()
    speaking = next(e for e in data if e["section"].startswith("Speaking"))
    first = speaking["tasks"][0]
    assert "submitted annually" in first["notes"]


@_skip_no_pdf
def test_task_shape_and_csv_columns():
    data = _parsed()
    for e in data:
        for t in e["tasks"]:
            assert set(t.keys()) == {"name", "notes"}
    rows = to_csv_rows(data)
    assert rows and set(rows[0].keys()) == {
        "group", "section_name", "task_name", "task_notes"}


@_skip_no_pdf2
def test_flat_contract_promotes_bullets_to_sections():
    """Flat contract (no group headers): • items with o-children become Sections,
    deliverables start at the 'shall include all of the following' intro, the payment
    block is excluded, and no empty sections remain."""
    data = parse_contract(str(CONTRACT2_PDF))
    sections = [e["section"] for e in data]
    assert len(data) >= 4
    assert all(e["tasks"] for e in data), "flat contract should have no empty sections"
    # • headers promoted to sections (would be leaf tasks under the grouped rule)
    assert any(s.startswith("15-Minute Tech Talk") for s in sections)
    assert any(s.startswith("Joint Webinar") for s in sections)
    # payment block must not leak in as a section
    assert not any("REMIT" in s.upper() for s in sections)


def test_validate_pdf_rejects_non_pdf(tmp_path=None):
    """Magic-byte + size guard at the untrusted-input boundary (no real PDF needed)."""
    import tempfile
    import os
    # missing file
    try:
        validate_pdf(str(REPO_ROOT / "tests" / "does_not_exist.pdf"))
        assert False, "expected InvalidPDFError for missing file"
    except InvalidPDFError:
        pass
    # exists but not a PDF (wrong magic bytes)
    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        os.write(fd, b"not a pdf at all")
        os.close(fd)
        try:
            validate_pdf(path)
            assert False, "expected InvalidPDFError for bad magic bytes"
        except InvalidPDFError:
            pass
    finally:
        os.unlink(path)


@_skip_no_pdf
def test_validate_pdf_accepts_real_contract():
    validate_pdf(str(CONTRACT_PDF))  # should not raise


# ── Engine (Phase 1) ─────────────────────────────────────────────────────────

@_skip_no_pdf
def test_build_project_dry_run_matches_parser():
    result = build_project(str(CONTRACT_PDF), dry_run=True)
    assert result.dry_run is True
    assert result.project_gid is None  # nothing created
    parsed = parse_contract(str(CONTRACT_PDF))
    assert result.plan.section_count == len(parsed)
    assert result.plan.task_count == sum(len(e["tasks"]) for e in parsed)


def test_build_project_live_requires_creds():
    """Live mode with no client and no configured creds fails clearly (not silently)."""
    sample = REPO_ROOT / "samples" / "sample_acme_grouped.pdf"
    if not sample.exists():
        return
    import os
    import csms.config as cfg
    cfg._ENV_LOADED = True  # skip .env load
    saved = os.environ.pop("ASANA_PAT", None)
    try:
        build_project(str(sample), dry_run=False)
        assert False, "live build without creds should raise"
    except RuntimeError:
        pass
    finally:
        if saved is not None:
            os.environ["ASANA_PAT"] = saved
        cfg._ENV_LOADED = False


def test_plan_to_dict_and_text_render():
    """Pure data — runs without the contract PDF."""
    plan = BuildPlan(source="x.pdf", sections=[
        SectionPlan(name="Speaking", group="Benefits",
                    tasks=[TaskPlan(name="Keynote", notes="approve topic"),
                           TaskPlan(name="Video file")])])
    d = plan_to_dict(plan)
    assert d["section_count"] == 1 and d["task_count"] == 2 and d["note_count"] == 1
    assert d["sections"][0]["tasks"][0]["notes"] == "approve topic"
    txt = format_plan_text(plan)
    for needle in ("Speaking", "Keynote", "Video file", "approve topic", "Dry run"):
        assert needle in txt


def _run_standalone():
    if not _HAVE_PDF:
        print(f"SKIP: contract PDF not found at {CONTRACT_PDF}")
        return 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
