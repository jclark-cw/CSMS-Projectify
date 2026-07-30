#!/usr/bin/env python3
"""Tests for the playbook overlay: default tasks, assignees, cascading due dates."""

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from csms.engine import BuildPlan, SectionPlan, TaskPlan  # noqa: E402
from csms.playbook import apply_playbook, load_playbook  # noqa: E402

PLAYBOOK = {
    "default_sections": [
        {"name": "Kickoff", "tasks": [
            {"name": "Welcome email", "assignee": "dana@x.com",
             "due": {"anchor": "signed", "offset_days": 2}},
            {"name": "Add to CRM", "assignee": "ops@x.com"},
        ]},
    ],
    "assignees": {
        "default": "ops@x.com",
        "by_section": {"Speaking": "dana@x.com"},
    },
    "due_dates": {
        "default": {"anchor": "signed", "offset_days": 30},
        "cascade_days": 7,
        "by_section": {"Speaking": {"anchor": "signed", "offset_days": 10}},
    },
}


def _parsed_plan():
    return BuildPlan(source="c.pdf", sections=[
        SectionPlan(name="Speaking", group="Benefits", tasks=[
            TaskPlan(name="Keynote"), TaskPlan(name="Video file")]),
        SectionPlan(name="Booth", group="Benefits", tasks=[TaskPlan(name="10x10")]),
    ])


def test_default_tasks_are_prepended():
    out = apply_playbook(_parsed_plan(), PLAYBOOK, signed_date="2026-01-15")
    assert out.sections[0].name == "Kickoff"
    assert [t.name for t in out.sections[0].tasks] == ["Welcome email", "Add to CRM"]
    # deliverable sections follow
    assert [s.name for s in out.sections[1:]] == ["Speaking", "Booth"]


def test_assignees_by_section_and_default():
    out = apply_playbook(_parsed_plan(), PLAYBOOK, signed_date="2026-01-15")
    speaking = next(s for s in out.sections if s.name == "Speaking")
    booth = next(s for s in out.sections if s.name == "Booth")
    assert all(t.assignee == "dana@x.com" for t in speaking.tasks)  # by_section
    assert all(t.assignee == "ops@x.com" for t in booth.tasks)      # default


def test_kickoff_assignee_auto_assigns_unassigned_default_tasks():
    pb = json.loads(json.dumps(PLAYBOOK))
    pb["default_sections"][0]["tasks"][1].pop("assignee")  # "Add to CRM" unassigned
    pb["assignees"]["kickoff"] = "kick@x.com"
    out = apply_playbook(_parsed_plan(), pb, signed_date="2026-01-15")
    kickoff = out.sections[0]
    # explicit per-task assignee still wins; the blank one picks up the kickoff default
    assert kickoff.tasks[0].assignee == "dana@x.com"
    assert kickoff.tasks[1].assignee == "kick@x.com"


def test_kickoff_assignee_does_not_leak_into_contract_tasks():
    # assignees.kickoff is deliberately separate from assignees.default.
    pb = json.loads(json.dumps(PLAYBOOK))
    pb["assignees"]["kickoff"] = "kick@x.com"
    out = apply_playbook(_parsed_plan(), pb, signed_date="2026-01-15")
    booth = next(s for s in out.sections if s.name == "Booth")
    assert all(t.assignee == "ops@x.com" for t in booth.tasks)


def test_no_kickoff_assignee_leaves_tasks_unassigned():
    pb = json.loads(json.dumps(PLAYBOOK))
    pb["default_sections"][0]["tasks"][1].pop("assignee")
    out = apply_playbook(_parsed_plan(), pb, signed_date="2026-01-15")
    assert out.sections[0].tasks[1].assignee is None


def test_due_dates_cascade_from_signing():
    out = apply_playbook(_parsed_plan(), PLAYBOOK, signed_date="2026-01-15")
    speaking = next(s for s in out.sections if s.name == "Speaking")
    # Speaking rule: signed + 10, cascade +7 per task → Jan 25, then Feb 1
    assert speaking.tasks[0].due_on == "2026-01-25"
    assert speaking.tasks[1].due_on == "2026-02-01"
    # default task with explicit offset 2 → Jan 17
    kickoff = out.sections[0]
    assert kickoff.tasks[0].due_on == "2026-01-17"
    assert kickoff.tasks[1].due_on is None  # no due rule on that task


def test_event_anchor_skipped_when_no_event_date():
    pb = {"due_dates": {"default": {"anchor": "event", "offset_days": -30}}}
    out = apply_playbook(_parsed_plan(), pb, signed_date="2026-01-15", event_date=None)
    for s in out.sections:
        for t in s.tasks:
            assert t.due_on is None  # event anchor with no event date → no due


def test_event_anchor_used_when_event_date_given():
    pb = {"due_dates": {"default": {"anchor": "event", "offset_days": -30}}}
    out = apply_playbook(_parsed_plan(), pb, signed_date="2026-01-15",
                         event_date="2026-06-01")
    booth = next(s for s in out.sections if s.name == "Booth")
    assert booth.tasks[0].due_on == "2026-05-02"  # 30 days before Jun 1


def test_load_playbook_json():
    d = Path(tempfile.mkdtemp())
    f = d / "pb.json"
    f.write_text(json.dumps(PLAYBOOK))
    loaded = load_playbook(f)
    assert loaded["assignees"]["default"] == "ops@x.com"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS  {name}")
    print("playbook OK")
