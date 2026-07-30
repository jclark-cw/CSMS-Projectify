#!/usr/bin/env python3
"""plan_to_dict / plan_from_dict round-trip — the basis of the editable preview."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from csms.engine import (BuildPlan, SectionPlan, TaskPlan,
                         plan_to_dict, plan_from_dict, build_from_plan)


def _plan():
    return BuildPlan(source="c.pdf", sections=[
        SectionPlan(name="Booth", group="Benefits", tasks=[
            TaskPlan(name="10x10", notes="n", assignee="u1", due_on="2026-02-01"),
            TaskPlan(name="Signage"),
        ]),
    ])


def test_roundtrip_preserves_everything():
    out = plan_from_dict(plan_to_dict(_plan()))
    assert out.section_count == 1 and out.task_count == 2
    s = out.sections[0]
    assert s.name == "Booth" and s.group == "Benefits"
    assert s.tasks[0].assignee == "u1" and s.tasks[0].due_on == "2026-02-01"
    assert s.tasks[1].assignee is None and s.tasks[1].due_on is None


def test_edits_are_honoured():
    d = plan_to_dict(_plan())
    d["sections"][0]["tasks"][1]["assignee"] = "u2"
    d["sections"][0]["tasks"][1]["due_on"] = "2026-03-09"
    out = plan_from_dict(d)
    assert out.sections[0].tasks[1].assignee == "u2"
    assert out.sections[0].tasks[1].due_on == "2026-03-09"


def test_unnamed_tasks_and_empty_sections_are_dropped():
    # Asana rejects unnamed tasks/sections; deleting a row in the UI empties them.
    d = plan_to_dict(_plan())
    d["sections"][0]["tasks"] = [{"name": "  ", "notes": ""}]
    assert plan_from_dict(d).sections == []


def test_build_from_plan_skips_parsing_entirely():
    seen = {}

    class FakeAsana:
        def create_project(self, plan, name, on_exists="skip"):
            seen["name"] = name
            seen["tasks"] = plan.task_count
            return {"project_gid": "P9", "project_url": "u",
                    "created": {"sections": 1, "tasks": 2}, "existed": False,
                    "warnings": []}

    # source is not a real file — proves nothing re-reads the PDF
    res = build_from_plan(_plan(), asana=FakeAsana(), project_name="Edited")
    assert seen == {"name": "Edited", "tasks": 2}
    assert res.dry_run is False and res.project_gid == "P9"


def _run_standalone():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL  {t.__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
