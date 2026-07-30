#!/usr/bin/env python3
"""csms.cli — command-line entry point.

  python3 -m csms parse <contract.pdf> [--json out.json] [--csv out.csv]
  python3 -m csms build <contract.pdf> [--json out.json] [--live]

A bare `python3 -m csms <contract.pdf>` (no subcommand) defaults to `parse` for
back-compatibility.
"""

import sys
import json
import csv
import argparse
from pathlib import Path

from .parser import parse_contract, to_csv_rows, validate_pdf, InvalidPDFError
from .engine import build_project, plan_to_dict, format_plan_text

_SUBCOMMANDS = ("parse", "build", "poll")


def _validate_or_exit(pdf: str) -> None:
    try:
        validate_pdf(pdf)
    except InvalidPDFError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_parse(args) -> None:
    _validate_or_exit(args.pdf)
    sections = parse_contract(args.pdf)

    json_str = json.dumps(sections, indent=2)
    if args.json_out:
        Path(args.json_out).write_text(json_str)
        print(f"Wrote {len(sections)} sections → {args.json_out}", file=sys.stderr)
    else:
        print(json_str)

    if args.csv_out:
        rows = to_csv_rows(sections)
        with open(args.csv_out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["group", "section_name", "task_name", "task_notes"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {len(rows)} task rows → {args.csv_out}", file=sys.stderr)


def _cmd_build(args) -> None:
    _validate_or_exit(args.pdf)

    playbook = None
    signed_date = getattr(args, "signed_date", None)
    if getattr(args, "playbook", None):
        from .playbook import load_playbook
        from datetime import date
        playbook = load_playbook(args.playbook)
        signed_date = signed_date or date.today().isoformat()

    try:
        result = build_project(args.pdf, dry_run=not args.live,
                               project_name=getattr(args, "project_name", None),
                               force=getattr(args, "force", False),
                               playbook=playbook, signed_date=signed_date,
                               event_date=getattr(args, "event_date", None))
    except (NotImplementedError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(3)

    if not result.dry_run:
        if result.existed:
            print(f"Already exists: {result.project_url}")
            print("  skipped (use --force to create another)")
            return
        c = result.created
        print(f"Created project: {result.project_url}")
        print(f"  {c.get('sections', 0)} sections, {c.get('tasks', 0)} tasks")
        for w in result.warnings:
            print(f"  warning: {w}")
        return

    plan = result.plan
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(plan_to_dict(plan), indent=2))
        print(f"Wrote plan ({plan.section_count} sections, {plan.task_count} tasks) "
              f"→ {args.json_out}", file=sys.stderr)
    else:
        print(format_plan_text(plan))


def _cmd_poll(args) -> None:
    """Run the DocuSign poll once, now — the manual/instant trigger (same code a
    launchd/cron schedule calls). Builds projects for newly-completed envelopes."""
    from datetime import date, timedelta
    from .config import get
    from .docusign import DocuSignClient, DocuSignError
    from .poll import poll_once, build_from_pdf_bytes
    from .state import ProcessedStore

    since = args.since or (date.today() - timedelta(days=args.days)).isoformat()
    folder = args.folder or get("DOCUSIGN_FOLDER_ID")

    playbook = None
    if args.playbook:
        from .playbook import load_playbook
        playbook = load_playbook(args.playbook)

    try:
        docusign = DocuSignClient.from_config()
    except (RuntimeError, DocuSignError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(3)

    def build(pdf_bytes, env):
        name = env.get("emailSubject") or None
        signed = (env.get("completedDateTime") or "")[:10] or None
        return build_from_pdf_bytes(pdf_bytes, name, playbook=playbook,
                                    signed_date=signed)

    try:
        results = poll_once(docusign, since, store=ProcessedStore(),
                            folder_id=folder, build=build)
    except (RuntimeError, DocuSignError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(3)

    if not results:
        print(f"No new completed envelopes since {since}.")
        return
    print(f"Built {len(results)} project(s):")
    for r in results:
        print(f"  envelope {r['envelope_id']} → https://app.asana.com/0/{r['project_gid']}")


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="csms", description="Contract → Asana automation")
    sub = ap.add_subparsers(dest="command")

    p_parse = sub.add_parser("parse", help="Parse a contract PDF to JSON/CSV")
    p_parse.add_argument("pdf", help="Path to the contract PDF")
    p_parse.add_argument("--json", dest="json_out", metavar="FILE",
                         help="Write JSON output to FILE (default: stdout)")
    p_parse.add_argument("--csv", dest="csv_out", metavar="FILE",
                         help="Write CSV output to FILE")
    p_parse.set_defaults(func=_cmd_parse)

    p_build = sub.add_parser(
        "build", help="Build an Asana project from a contract (dry-run by default)")
    p_build.add_argument("pdf", help="Path to the contract PDF")
    p_build.add_argument("--json", dest="json_out", metavar="FILE",
                         help="Write the plan as JSON to FILE")
    p_build.add_argument("--live", action="store_true",
                         help="Create the project in Asana (needs .env)")
    p_build.add_argument("--name", dest="project_name", metavar="NAME",
                         help="Project name (default: derived from the PDF filename)")
    p_build.add_argument("--force", action="store_true",
                         help="Create even if a project with that name already exists")
    p_build.add_argument("--playbook", metavar="FILE",
                         help="Playbook (YAML/JSON): default tasks, assignees, due dates")
    p_build.add_argument("--signed-date", dest="signed_date", metavar="YYYY-MM-DD",
                         help="Contract signing date (anchors due dates; default: today)")
    p_build.add_argument("--event-date", dest="event_date", metavar="YYYY-MM-DD",
                         help="Deliverable/event date (for event-anchored due dates)")
    p_build.set_defaults(func=_cmd_build)

    p_poll = sub.add_parser(
        "poll", help="Run the DocuSign poll once now (manual/instant trigger)")
    p_poll.add_argument("--since", metavar="YYYY-MM-DD",
                        help="Only envelopes completed on/after this date (default: --days ago)")
    p_poll.add_argument("--days", type=int, default=1,
                        help="Look back this many days when --since is omitted (default: 1)")
    p_poll.add_argument("--folder", help="DocuSign folder id (default: DOCUSIGN_FOLDER_ID)")
    p_poll.add_argument("--playbook", metavar="FILE",
                        help="Apply a playbook (signing date taken from each envelope)")
    p_poll.set_defaults(func=_cmd_poll)

    return ap


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Back-compat: a bare "<pdf>" (no subcommand) behaves like "parse <pdf>".
    if argv and argv[0] not in _SUBCOMMANDS and not argv[0].startswith("-"):
        argv = ["parse"] + argv

    ap = build_arg_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
