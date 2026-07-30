#!/usr/bin/env python3
"""csms.playbook — standard rules layered onto every parsed contract.

The parser produces contract-specific sections/tasks; the playbook adds what the
contract doesn't contain:
  • default tasks/sections on every project (kickoff, onboarding, …)
  • assignees (by section, or explicit on default tasks)
  • cascading due dates anchored to the signing date (or, later, an event date)

Dates anchor to "signed" (contract signing date) or "event" (a deliverable/event
date, optional). offset_days may be negative (e.g. 90 days *before* an event).
Within a section, due dates cascade by cascade_days so tasks spread out.

The playbook is optional — without one, projects build exactly as before.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .engine import BuildPlan, SectionPlan, TaskPlan


def load_playbook(path) -> dict:
    """Load a playbook from YAML (preferred, needs PyYAML) or JSON."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        import yaml  # PyYAML — only needed for YAML playbooks
        return yaml.safe_load(text) or {}
    return json.loads(text or "{}")


def _as_date(value):
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _due(rule: dict, signed, event, extra_days: int = 0):
    """Resolve a due-date rule to a YYYY-MM-DD string, or None if no anchor."""
    if not rule:
        return None
    anchor = signed if rule.get("anchor", "signed") == "signed" else event
    if anchor is None:
        return None
    offset = int(rule.get("offset_days", 0)) + extra_days
    return (anchor + timedelta(days=offset)).isoformat()


def apply_playbook(plan: BuildPlan, playbook: dict, *,
                   signed_date=None, event_date=None) -> BuildPlan:
    """Return a new BuildPlan with default tasks prepended and assignees + due
    dates filled in per the playbook. Inputs accept ISO strings or date objects."""
    signed = _as_date(signed_date)
    event = _as_date(event_date)
    pb = playbook or {}

    sections = []
    assignees = pb.get("assignees", {})

    # ── Default sections/tasks (added to every project, before deliverables) ──
    # assignees.kickoff auto-assigns these when a task doesn't name someone —
    # deliberately separate from assignees.default, which covers the contract's
    # own parsed tasks.
    kickoff_assignee = assignees.get("kickoff")
    for ds in pb.get("default_sections", []):
        tasks = []
        for t in ds.get("tasks", []):
            tasks.append(TaskPlan(
                name=t["name"],
                notes=t.get("notes", ""),
                assignee=t.get("assignee") or kickoff_assignee,
                due_on=_due(t.get("due"), signed, event),
            ))
        sections.append(SectionPlan(name=ds["name"], group=ds.get("group", ""),
                                    tasks=tasks))

    # ── Parsed (contract) sections: assignees + cascading due dates ──────────
    due_cfg = pb.get("due_dates", {})
    cascade = int(due_cfg.get("cascade_days", 0))
    by_section_due = due_cfg.get("by_section", {})
    by_section_assignee = assignees.get("by_section", {})

    for s in plan.sections:
        sec_assignee = by_section_assignee.get(s.name, assignees.get("default"))
        sec_rule = by_section_due.get(s.name, due_cfg.get("default"))
        new_tasks = []
        for i, t in enumerate(s.tasks):
            new_tasks.append(TaskPlan(
                name=t.name,
                notes=t.notes,
                assignee=t.assignee or sec_assignee,
                due_on=t.due_on or _due(sec_rule, signed, event, extra_days=i * cascade),
            ))
        sections.append(SectionPlan(name=s.name, group=s.group, tasks=new_tasks))

    return BuildPlan(source=plan.source, sections=sections)
