#!/usr/bin/env python3
"""csms.engine — the core build_project() engine.

One engine, many front-ends: the desktop app, the web UI, and the CLI all call
build_project(). It parses a contract PDF into a BuildPlan and, unless this is a
dry run, creates the Asana project from that plan.

Phase 1 ships the dry-run path (parse → plan → preview), which needs no credentials
and works offline. Live Asana creation arrives in Phase 2 via an injected client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .parser import parse_contract, validate_pdf


# ── Plan data model ──────────────────────────────────────────────────────────

@dataclass
class TaskPlan:
    name: str
    notes: str = ""
    assignee: Optional[str] = None   # Asana user email or gid
    due_on: Optional[str] = None     # YYYY-MM-DD


@dataclass
class SectionPlan:
    name: str
    group: str
    tasks: list  # list[TaskPlan]


@dataclass
class BuildPlan:
    """What we would create in Asana — the parsed contract, structured."""
    source: str
    sections: list  # list[SectionPlan]

    @property
    def section_count(self) -> int:
        return len(self.sections)

    @property
    def task_count(self) -> int:
        return sum(len(s.tasks) for s in self.sections)

    @property
    def note_count(self) -> int:
        return sum(1 for s in self.sections for t in s.tasks if t.notes)


@dataclass
class BuildResult:
    plan: BuildPlan
    dry_run: bool
    project_gid: Optional[str] = None    # set by live mode (Phase 2)
    project_url: Optional[str] = None
    created: dict = field(default_factory=dict)   # counts of created objects
    existed: bool = False                # True if an existing project was reused
    warnings: list = field(default_factory=list)


# ── Engine ───────────────────────────────────────────────────────────────────

def _to_plan(source: str, parsed: list) -> BuildPlan:
    sections = [
        SectionPlan(
            name=entry["section"],
            group=entry.get("group", ""),
            tasks=[TaskPlan(name=t["name"], notes=t.get("notes", ""))
                   for t in entry["tasks"]],
        )
        for entry in parsed
    ]
    return BuildPlan(source=source, sections=sections)


def _default_project_name(source: str) -> str:
    name = Path(source).stem.replace("_", " ").strip()
    return name or "Contract project"


def build_project(source: str, dry_run: bool = True, asana=None,
                  project_name: Optional[str] = None, force: bool = False,
                  playbook: Optional[dict] = None, signed_date=None,
                  event_date=None, max_pdf_mb: float = 25.0) -> BuildResult:
    """Parse `source` (a contract PDF) into a plan and optionally build it in Asana.

    dry_run=True (default) returns the plan without touching Asana — offline-safe.
    dry_run=False creates the project: pass an `asana` client, or one is built from
    config (AsanaClient.from_config), which raises a clear error if creds are missing.
    Idempotent by project name unless force=True (then a duplicate is created).
    A `playbook` dict (with `signed_date`/`event_date`) overlays default tasks,
    assignees, and cascading due dates.
    """
    validate_pdf(source, max_mb=max_pdf_mb)
    parsed = parse_contract(source)
    plan = _to_plan(source, parsed)

    if playbook:
        from .playbook import apply_playbook
        plan = apply_playbook(plan, playbook, signed_date=signed_date,
                              event_date=event_date)

    if dry_run:
        return BuildResult(plan=plan, dry_run=True)

    if asana is None:
        from .asana_client import AsanaClient
        asana = AsanaClient.from_config()

    name = project_name or _default_project_name(source)
    result = asana.create_project(plan, name, on_exists="force" if force else "skip")
    return BuildResult(
        plan=plan,
        dry_run=False,
        project_gid=result.get("project_gid"),
        project_url=result.get("project_url"),
        created=result.get("created", {}),
        existed=result.get("existed", False),
        warnings=result.get("warnings", []),
    )


# ── Rendering ────────────────────────────────────────────────────────────────

def plan_to_dict(plan: BuildPlan) -> dict:
    """Serialize a BuildPlan to plain dict/JSON (for the app preview / --json)."""
    return {
        "source": plan.source,
        "section_count": plan.section_count,
        "task_count": plan.task_count,
        "note_count": plan.note_count,
        "sections": [
            {
                "group": s.group,
                "section": s.name,
                "tasks": [
                    {"name": t.name, "notes": t.notes,
                     "assignee": t.assignee, "due_on": t.due_on}
                    for t in s.tasks
                ],
            }
            for s in plan.sections
        ],
    }


def plan_from_dict(data: dict) -> BuildPlan:
    """Rebuild a BuildPlan from plan_to_dict() output.

    This is what lets the preview be *editable*: the app shows the parsed plan,
    the operator adjusts assignees and due dates on screen, and the edited plan
    is sent back to be built verbatim — rather than the server re-parsing the PDF
    and silently discarding those edits.

    Only name/notes/assignee/due_on are honoured; anything else is ignored, and
    tasks without a name are dropped (an empty task can't be created in Asana).
    """
    sections = []
    for s in data.get("sections", []):
        tasks = []
        for t in s.get("tasks", []):
            name = (t.get("name") or "").strip()
            if not name:
                continue
            tasks.append(TaskPlan(
                name=name,
                notes=t.get("notes") or "",
                assignee=(t.get("assignee") or None),
                due_on=(t.get("due_on") or None),
            ))
        section_name = (s.get("section") or "").strip()
        if not section_name or not tasks:
            continue  # Asana rejects unnamed sections; empty ones add nothing
        sections.append(SectionPlan(name=section_name,
                                    group=s.get("group") or "", tasks=tasks))
    return BuildPlan(source=data.get("source", "edited plan"), sections=sections)


def build_from_plan(plan: BuildPlan, asana=None, project_name: str = None,
                    force: bool = False) -> BuildResult:
    """Create an Asana project from an already-built (possibly edited) plan.

    Skips parsing entirely — the plan is the source of truth. Same idempotency
    and result shape as build_project's live path.
    """
    if asana is None:
        from .asana_client import AsanaClient
        asana = AsanaClient.from_config()
    name = project_name or _default_project_name(plan.source)
    result = asana.create_project(plan, name, on_exists="force" if force else "skip")
    return BuildResult(
        plan=plan,
        dry_run=False,
        project_gid=result.get("project_gid"),
        project_url=result.get("project_url"),
        created=result.get("created", {}),
        existed=result.get("existed", False),
        warnings=result.get("warnings", []),
    )


def format_plan_text(plan: BuildPlan) -> str:
    """Human-readable dry-run preview for the terminal."""
    out = [
        f"Dry run — plan for {plan.source}",
        f"{plan.section_count} sections · {plan.task_count} tasks · "
        f"{plan.note_count} notes",
        "",
    ]
    current_group = object()  # sentinel so the first group header always prints
    for s in plan.sections:
        if s.group != current_group:
            current_group = s.group
            if s.group:
                out.append(f"━━ {s.group} ━━")
        out.append(f"§ {s.name}  ({len(s.tasks)} tasks)")
        for t in s.tasks:
            meta = []
            if t.assignee:
                meta.append(f"@{t.assignee}")
            if t.due_on:
                meta.append(f"due {t.due_on}")
            suffix = f"   [{', '.join(meta)}]" if meta else ""
            out.append(f"   • {t.name}{suffix}")
            if t.notes:
                out.append(f"       ↳ {t.notes.replace(chr(10), ' / ')}")
        out.append("")
    out.append("Nothing was written to Asana. Re-run with --live once Phase 2 is wired.")
    return "\n".join(out)
