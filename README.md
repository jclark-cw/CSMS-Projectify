# CSMS — Contract → Asana

Self-owned replacement for the old Zapier flow. A completed sponsorship contract
PDF is parsed locally into deliverable **sections** and **tasks**, which become an
Asana project. The signed contract PDF is supplied by the user — dragged into the
app — so nothing here connects to DocuSign or any other e-signature service. One
core engine, many front-ends (desktop app, web UI, CLI). See
[CSMS_App_Plan.md](CSMS_App_Plan.md) for the full plan.

## Status

- **Phase 0 (done):** parser packaged as `csms/`, golden + structural tests, security baseline.
- **Phase 1 (done):** `build_project` engine + dry-run preview CLI (`build`).
- **Phase 2 scaffold:** `asana_client.py` + live wiring (`build --live`); stdlib HTTP, fully
  unit-tested offline. Needs an Asana PAT in `.env` to actually create a project.
- **Phase 3 prototype:** "Projectify" Flask web UI + JSON API over the dry-run engine.
- Test fixtures: `tools/make_sample_contracts.py` → `samples/*.pdf` (synthetic, committed).
- Next: idempotency (re-run safety) + wiring the live button into the web app.

## Layout

```
csms/            # the package
  parser.py      # PDF → [{group, section, tasks:[{name, notes}]}]  (offline, pure)
  engine.py      # build_project() → BuildPlan; dry-run preview; live = Phase 2
  cli.py         # python -m csms {parse,build} <pdf> ...
  config.py      # the ONLY place secrets are read (env / .env)
tests/           # golden + structural + engine tests (pytest or standalone)
  golden/        # pinned expected output
parse_contract.py  # thin back-compat shim → csms.cli (defaults to `parse`)
```

## Use

```bash
python3 -m pip install -r requirements.txt          # runtime

# Parse → JSON / CSV
python3 -m csms parse "CW Contracts/<contract>.pdf"
python3 -m csms parse "CW Contracts/<contract>.pdf" --csv out.csv

# Dry-run preview of the Asana project that would be built (offline, no creds)
python3 -m csms build "CW Contracts/<contract>.pdf"
python3 -m csms build "CW Contracts/<contract>.pdf" --json plan.json

# Live: create the project in Asana (needs .env — see .env.example)
# Idempotent by project name: re-running skips an existing project (use --force to duplicate).
python3 -m csms build "CW Contracts/<contract>.pdf" --live
python3 -m csms build "CW Contracts/<contract>.pdf" --live --name "Acme 2026" --force

# With a playbook: default tasks + assignees + cascading due dates (anchored to signing)
python3 -m csms build "<contract>.pdf" --playbook playbook.yaml --signed-date 2026-01-15

# Synthetic test contracts (no real data) for trying the app / CI
python3 tools/make_sample_contracts.py     # → samples/*.pdf
```

### Playbook (default tasks, assignees, due dates)

The parser produces contract-specific sections/tasks; a **playbook** overlays the
standard scaffolding the contract doesn't contain — default tasks on every project,
task assignees (by section + explicit), and cascading due dates anchored to the
signing date (or an optional event date). Copy `playbook.example.yaml` →
`playbook.yaml` (git-ignored) and edit. Optional: no playbook = build as before.

A bare `python3 -m csms <pdf>` (no subcommand) still works and means `parse`.

### Projectify web app (Flask)

```bash
python3 -m csms.webapp          # serves http://127.0.0.1:5000
```

Drag a contract PDF onto the page → preview the sections/tasks/notes → click
**Create in Asana** to build the project live (needs `.env`; idempotent by name, with a
confirm step and editable project name). The file stays in the browser; each request
uses a short-lived temp file that is deleted immediately — contracts are never persisted.
JSON routes: `POST /api/preview` (dry-run) and `POST /api/build` (live) — multipart field
`contract` — are the same engine in API form.

This one Flask codebase is intended to become the local click-install (via PyWebview),
a single-tenant hosted URL, and the API — without an engine rewrite.

### Projectify as a local desktop window (PyWebview)

```bash
python3 -m pip install -r requirements-desktop.txt
python3 -m csms.desktop          # native window, no browser, no URL
```

Same UI, rendered in a native OS window instead of a browser tab — the local-app form
and the click-install precursor (freeze with PyInstaller later for a double-click app).

## Test

```bash
python3 -m pip install -r requirements-dev.txt
pytest                       # or: python3 tests/test_parser.py
```

The contract PDF is git-ignored (signed document). When absent, PDF-dependent
tests skip; the committed `tests/golden/cmc26.json` keeps the expected structure
under version control. A synthetic sample contract for CI is a good follow-up.

## Security

Signed contracts are PII + confidential and the system holds an Asana token.
Parsing is **local only** (no cloud parsers → no data egress). Secrets load
exclusively via `csms/config.py` from a git-ignored, `chmod 600` `.env`
(see `.env.example`). Full threat model + checklist in the plan's Security section.
