# CSMS "Projectify" — Build Plan

Replace the Zapier flow with a self-owned Python system: **one core engine, many triggers.**
Start with an operator-triggered upload app; bolt on full automation later with no rewrite.

> **Status note (2026-08-10):** the DocuSign auto-trigger described below was built,
> then **removed** at the client's request. The app does not connect to DocuSign or
> any other e-signature service — the user exports the completed PDF and uploads it.
> Sections describing the poll, envelope ids, JWT auth, and `state.py` are retained
> as design history only; they no longer describe shipped code. Contract *parsing*
> is unchanged.

---

## Goal

When a CyberMarketingCon sponsorship contract is signed, automatically create the
matching Asana project — sections and tasks built from the deliverables in the contract —
**without Zapier, Google Sheets, Looping, or a fragile public webhook.**

Two delivery modes, same engine underneath:
- **App / "Projectify" button** (default): upload the signed PDF → preview → confirm → built.
- ~~**Full automation** (bolt-on): a scheduled DocuSign poll pulls signed contracts and builds them with nobody touching it.~~ *(removed — see status note)*

---

## Principles

- **Portable by default.** Pure-Python deps, `pathlib` (no hardcoded absolute paths),
  Python 3.10+ syntax, secrets via env/`.env`. *(Floor raised from 3.9 on 2026-08-10:
  the pdfminer.six release fixing PYSEC-2026-1761 requires 3.10, and that library
  parses the untrusted contract.)* The engine and app run on macOS / Linux / Windows.
- **Consistent input.** Contract templates should follow the formatting standard
  (see `CONTRACT_FORMATTING.md`) so parsing leans on portable glyph+bold signals, not
  brittle font heuristics. Not enforced — the editable preview is the safety net.

## Architecture — one engine, pluggable triggers

```
                 ┌──────────────────────────────────────────┐
   TRIGGERS      │                CORE ENGINE               │     OUTPUT
                 │                                          │
 ┌─────────────┐ │  build_project(source, dry_run=False):   │  ┌──────────────┐
 │ Upload app  │─┼─▶ 1. resolve source → PDF                │─▶│ Asana project │
 │ (button)    │ │   2. parse deliverables (offline)        │  │  + sections   │
 ├─────────────┤ │   3. dry_run? return plan, write nothing │  │  + tasks      │
 │ Folder watch│─┤   4. else create project (from template) │  └──────────────┘
 ├─────────────┤ │   5. create sections + tasks (idempotent)│
 │ DocuSign    │─┤   6. return BuildResult (gids + summary) │
 │ poll (auto) │ │                                          │
 ├─────────────┤ └──────────────────────────────────────────┘
 │ Webhook     │   Every trigger is a thin adapter that calls
 │ (future)    │   the SAME build_project(). Add/remove freely.
 └─────────────┘
```

The win: parsing + Asana logic is written **once** and reused by every trigger. You can ship
the button this week and add hands-off automation later by dropping in a ~30-line trigger.

---

## File structure

```
CSMS/
├── csms/                     # the importable package
│   ├── __init__.py
│   ├── parser.py             # parse_contract.py refactored into a clean module (no behavior change)
│   ├── asana_client.py       # Asana API wrapper: create-from-template, sections, tasks, rate-limit/backoff
│   ├── docusign.py           # bolt-on: list completed envelopes, download combined PDF by envelope id
│   ├── engine.py             # build_project() — orchestrates parse → Asana; dry-run; idempotency
│   ├── config.py             # loads secrets/ids from .env (python-dotenv)
│   └── state.py              # tracks processed envelope ids / built projects (small JSON file)
├── app.py                    # Streamlit "Projectify" upload app
├── triggers/
│   ├── watch_folder.py       # watchdog folder watcher → build_project
│   └── poll_docusign.py      # scheduled DocuSign poll → build_project (full automation)
├── cli.py                    # python -m csms build <pdf> [--dry-run]
├── tests/
│   ├── golden/               # known-good parser output for existing contracts (regression net)
│   └── test_parser.py
├── deploy/
│   ├── com.csms.poll.plist   # launchd template for the DocuSign poll
│   └── com.csms.watch.plist  # launchd template for the folder watcher
├── .env.example              # documents required keys; real .env is git-ignored
├── requirements.txt
└── README.md                 # run/setup instructions
```

Existing `make_bom.py` and `CMC26_Zapier_Table.csv` stay as reference; the parser becomes the
source of truth, so the Google Sheet is no longer in the critical path.

---

## Core engine details

**`build_project(source, *, dry_run=False) -> BuildResult`**

1. **Resolve source** — accepts a local PDF path *or* a DocuSign envelope id (resolved to a PDF via `docusign.py`).
2. **Parse** — font/bullet heuristics produce `[{group, section, tasks: [{name, notes}]}]`. Fully offline. Mapping rules: bold line/bold `●` → **Section**; Courier `o` bullet and **non-bold `●` bullet** → **Task**; `▪` → **Task Notes** on the preceding task. (Generous capture by design — the preview prunes qualifier lines per contract.)
3. **Dry run** — if `dry_run=True`, return the planned structure and stop. Nothing is written. This powers the app's preview and the offline path.
4. **Create project** — a **blank Asana project** (no template; the parsed contract *is* the structure). Optionally a fixed prefix of standard tasks (intake/kickoff) common to every sponsor can be added on top — off by default.
5. **Create sections + tasks** — one section per parsed deliverable, tasks beneath. Honor Asana's ~150 req/min limit with batching + exponential backoff on 429.
6. **Idempotency** — record built envelope-id/project-name in `state.py`. Re-running the same contract updates rather than duplicates, which **structurally kills the old "duplicate first task" bug.**
7. **Return** `BuildResult` — created project URL, section/task gids, counts, and any skips/warnings.

---

## The "Projectify" app (Streamlit)

- `st.file_uploader` for the signed PDF.
- **Preview** button → runs the parser, shows a table of exactly the sections/tasks it *will* create (offline, no Asana writes).
- **Projectify** button → confirm dialog → `build_project(...)` → shows a clickable link to the new Asana project plus a created-items log.
- Clear error surface (bad PDF, Asana auth, rate limit).
- Run locally with `streamlit run app.py`. Token stays on your machine.
- Optional later: deploy to Streamlit Community Cloud + a password if an external person ever needs the URL.

**Why this over raw command line:** anyone can use it, no terminal, and the preview-before-write step is the safety net the Zapier flow never had.

---

## Bolt-on triggers (toward full automation)

| Trigger | Fires when | Hosting | Notes |
|---|---|---|---|
| **Folder watch** (`watch_folder.py`) | a signed PDF lands in a watched folder | none — `watchdog` + launchd | great if you already download the PDF |
| **DocuSign poll** (`poll_docusign.py`) | scheduled check finds a newly-completed envelope | none public — launchd/cron on your Mac | **the recommended full-automation path**; pulls the PDF itself by envelope id |
| **Connect webhook** (future) | real-time, instant on completion | always-on public endpoint + HMAC verify | documented, not built first — this is the fragility you're leaving |

**Recommended route to full automation:** DocuSign **polling** via a launchd job every few minutes.
It's hands-off, needs no public endpoint or signature verification, and reuses `build_project`
unchanged. `state.py` prevents reprocessing the same envelope. Requires DocuSign **JWT grant**
auth (unattended) — credentials only, no inbound server.

---

## Offline behavior (answering directly)

- **Offline:** PDF parsing and the full dry-run preview.
- **Needs internet:** creating the Asana project/sections/tasks. That's the only outbound call.
- **Resilience:** if the network drops mid-build, idempotency means a clean re-run when you're back — no half-built or duplicated projects.

---

## Security

A completed DocuSign contract is **PII + business-confidential** (legal names, signatures,
emails, payment amounts, and the Certificate of Completion's signer IPs/timestamps), and the
system holds a high-value **Asana API token**. "Marketing" doesn't lower the bar.

**Leaving Zapier is itself the biggest win:** today the Asana PAT is hardcoded in a Zapier Code
step and contract data flows through Zapier *and* Google Sheets — three external processors.
Local-first cuts that to **zero third-party processors**. Data minimization is the headline.

### Threat model (prioritized)

**Tier 1 — crown jewels**
- **Secrets (Asana PAT; later DocuSign JWT private key).** Risks: committed to git, leaked into
  logs, world-readable `.env`, or hardcoded like the current Zap. Mitigations: `.env` git-ignored
  + `chmod 600` (or macOS **Keychain**); never logged/printed; **least privilege** — a dedicated
  Asana *service-account* scoped to the one team, not a personal admin PAT; rotation plan;
  DocuSign integration scoped to *read envelopes only*.
- **Contract PII at rest.** Risks: unencrypted PDFs piling up in Downloads/watched folder; `/tmp`
  copies; contract text echoed into logs or a screenshotted preview; indefinite retention.
  Mitigations: FileVault; restricted folder perms; **never log contract bodies**; scrub temp
  files; a retention policy (process → encrypted store or delete); **parse locally only** —
  no cloud parser (Nanonets/Docparser/etc. would egress every signed contract).

**Tier 2 — input & provenance**
- **Untrusted PDF parsing.** pdfplumber is pure-Python (no render, no JS execution → the usual
  PDF-exploit class doesn't apply). Residual risk: decompression/"bomb" PDFs causing CPU/memory
  DoS. Mitigations: validate it's a real PDF, size limit, parse timeout, keep pdfplumber patched.
- **Authenticity** — the app builds from *whatever PDF is uploaded*; a doctored PDF could build a
  bogus project. Mitigations: for automation, pull the PDF **from the DocuSign API by envelope id**
  and verify `status == completed`; manual path relies on operator + confirm step; if a webhook is
  ever added, **verify the HMAC signature** — never trust an unauthenticated POST.

**Tier 3 — surface & supply chain**
- **Hosted app** (only if the URL option is chosen): exposed upload endpoint → needs login + TLS +
  rate limiting, token server-side. **Local-only avoids all of it** (the default).
- **Dependencies:** pin versions + lockfile; run `pip-audit`/Dependabot on pdfplumber, streamlit,
  requests, watchdog.
- **Transport:** all Asana/DocuSign calls over TLS with cert verification **on** — never disabled.

### Phase 0 security baseline (bake in from the first commit)

- [ ] `.gitignore` covers `.env`, `*.pdf`, `state/`, any `/tmp` outputs, `__pycache__`
- [ ] `.env.example` documents keys; real `.env` is git-ignored and `chmod 600`
- [ ] Secrets loaded only via `config.py` (env/Keychain) — **never** hardcoded or logged
- [ ] Dedicated Asana **service account**, scoped to the target team; least-privilege PAT
- [ ] Parser: PDF magic-byte check, max file size, parse timeout
- [ ] Logging redacts contract content + PII; logs record envelope→project mapping only
- [ ] Retention policy decided (where signed PDFs live, how long, encrypted)
- [ ] `requirements.txt` pinned + `pip-audit` in the dev loop

## Phased delivery

| Phase | Deliverable | Outcome |
|---|---|---|
| **0** | Refactor `parse_contract.py` → `csms/parser.py` + golden tests + **security baseline** (checklist below) | Same parsing, now importable, tested, and secure-by-default |
| **1** | `asana_client.py` + `engine.py` + `cli.py --dry-run` | `python -m csms build contract.pdf --dry-run` prints the plan |
| **2** | Live creation of a **blank Asana project** + sections/tasks; idempotency | Real project built; duplicate-task bug gone |
| **3** | **Projectify** app (preview + confirm) — pick framework weighing click-install (Streamlit vs PyWebview) | The deliverable: upload → preview → build |
| **4** | Folder-watch trigger + launchd | Drop a PDF → auto-build |
| **5** | DocuSign poll trigger + JWT + launchd | **Full hands-off automation** |
| **6** | Retire the 2 Zaps once parity is confirmed | Zapier off |

Phases 0–3 deliver the app. 4–5 add automation. 6 is the switch-off. Each phase is usable on its own.

---

## Inputs I'll need from you (by phase)

**For Phase 2–3 (Asana):**
- Asana **Personal Access Token** (or a service account PAT) — how do you want it stored? (`.env`, recommended.)
- **Workspace gid** and the **team gid** the new projects should live under. (No template needed — projects are created blank and filled from the parse.)

**For Phase 5 (DocuSign automation):**
- DocuSign **Integration Key / account id** and approval to set up **JWT grant** auth for unattended polling.

**Cross-cutting decisions (defaults chosen, override anytime):**
- Task wording: **pure parse** (default) vs. keep a curated library to clean up wording.
- App reach: **local-only** (default, most secure) vs. hosted URL (adds login + server-side token).

---

## Distribution — "click install" on a client machine (future, post-app)

A double-click install (no Python required) is a goal. The build is straightforward;
the real requirements/gotchas:

- **Freeze** Python + deps into one bundle — PyInstaller, py2app, or BeeWare Briefcase.
- **Native installer per OS** — macOS `.app`+`.dmg`; Windows `.exe`+Inno Setup/NSIS.
- **Code-sign + notarize** (the underestimated part) — else Gatekeeper / SmartScreen warn:
  Apple Developer ID (~$99/yr) for macOS, Authenticode cert (~$100–400/yr) for Windows.
  Needs a signing identity — usually the main *logistical* blocker.
- **First-run secrets, not bundled** — the Asana token must NOT ship inside the app
  (extractable). First-run screen → store in OS keychain via `keyring` (macOS Keychain /
  Windows Credential Manager). Confirm whose Asana the client writes to (trust boundary).
- **Updates** — auto-update (Sparkle/WinSparkle) or manual reinstall; low volume → manual is fine.
- **Test on a clean machine** with no Python before shipping.

**Decision deferred** (target OS: TBD; app framework: TBD at Phase 3). Guardrail held now:
the engine is UI- and OS-agnostic, so Phase 3 can pick Streamlit (fast to build, hard to
freeze → tends toward hosted URL / "run a command") **or** a PyWebview/Flask local web UI
(same drag-drop UX, freezes cleanly into a signed click-install) without touching the engine.
**When choosing the Phase 3 framework, weigh packageability — that is the click-install fork.**

### Deployment models (client = EXTERNAL, writes to THEIR Asana)

Because each client controls their own token *and* their own contracts, keep the client in
control of both. Ranked by fit:
- **Local click-install** — token + contracts never leave the client's machine (best data-min).
- **Single-tenant / self-hosted** — hosted web app deployed in the *client's own* cloud; zero
  install for users, data stays in their control. In-memory PDF processing + login + TLS.
- **Multi-tenant SaaS (we host everyone)** — AVOID for this audience: we'd hold many clients'
  Asana tokens + signed contracts → worst security posture + data-processor liability.

**Zapier note:** the parser can't run in a Zapier Code step (no pip → no pdfplumber; ~8s parse
exceeds the budget; PDF-extract apps drop the font data the heuristics need *and* egress
contracts). To use Zapier the parser must be a hosted API the Zap POSTs to — at which point
DocuSign can call it directly and Zapier is optional. "No install" comes from hosting, not Zapier.

**"Explore both" unlock:** build the UI as a **Flask/FastAPI + HTML app** → one codebase wraps
with PyWebview into a local click-install AND deploys as a hosted (single-tenant) web app. The
same HTTP layer is also the Zapier/DocuSign-callable API. Streamlit forks toward hosted-only.
So the plain-web-app approach keeps local + hosted + API all open from one build.

### Delivery model comparison (reference)

| Option | Install | Security | Automation | Cost | Ongoing | Verdict |
|---|---|---|---|---|---|---|
| Local — CLI | dev only | contained (local) | manual | none | self-run | built (dev/testing) |
| Local — click-install | one-time + signing | contained (local) | manual + watch | low | app updates | ★ top fit |
| Online — URL (their cloud) | none | contained (their server) | manual / auto | hosting + auth | host + updates | ★ top fit |
| Online — multi-tenant SaaS | none | exposed (our server, all clients) | manual / auto | high + liability | we host 24/7 | avoid |
| Zapier → hosted API | none | exposed (via Zapier + API) | auto | API + Zap fees | host API + Zap | trigger add-on |
| DocuSign webhook → API | none | server (host-dependent) | hands-off | endpoint + ops | host 24/7 | trigger add-on |

**The deciding column is Ongoing:** local options end our involvement after delivery (only app
updates); every hosted/API option is a standing commitment to keep a server alive — us, unless
it's deployed in the client's own cloud. Security and cost mostly track together — the most
contained options are also the cheapest to run.

## Open risks to watch

- **Parser coverage (the #1 risk)** — heuristics depend on each contract's formatting conventions (bold = section, "o" bullet = task). Validate on real contracts up front; keep the editable preview as the permanent safety net.
- **Asana rate limits** — batch + backoff for large deliverable sets.
- **DocuSign JWT setup** — one-time consent/admin step; flag early before Phase 5.
