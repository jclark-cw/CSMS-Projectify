# Projectify — review call run-book

For walking an internal developer through the DocuSign → Asana tool.
Build status lives in `README.md`; deferred work in `TODO.md`.

---

## Launching

| What | Command | Writes to Asana? |
|---|---|---|
| **Desktop app** (the deliverable) | `python3 -m csms.desktop` | **Yes — live** |
| Web version (same app, in a browser) | `python3 -m csms.webapp` → `:8000` | **Yes — live** |
| Demo mode (safe, fake Asana) | `python3 tools/demo_sandbox.py` → `:8013` | No — records only |
| CLI | `python3 -m csms build <pdf> --live --name "..."` | **Yes — live** |
| Tests | `python3 -m pytest -q` | No |

The desktop app reads credentials from the **OS keychain**; the web/CLI paths read
**`.env`**. Both currently point at the live CSMS workspace `1197198727817117`
(team `Society Core Team`). Demo mode can't reach Asana at all — use it if you
want to click freely without creating projects.

Sample contracts for demoing: `samples/*.pdf` (synthetic, safe to parse).
Prefix live test projects with `[TEST]` so they're easy to find and delete after.

---

## Suggested walkthrough order

1. **Upload page** — drag in `samples/sample_acme_grouped.pdf`, hit **Preview project**.
   Point out: nothing has touched Asana yet. The parse is fully offline.
2. **The preview** — sections and tasks pulled out of the contract itself. This is
   the whole reason we didn't use Zapier: no two contracts have the same structure,
   so there's no template to bind to.
3. **Create in Asana** — name it `[TEST] …`, set the signing date, confirm.
   Then **click it again** to show name-based idempotency (it skips instead of
   duplicating, with an explicit "Create another anyway" escape hatch).
4. **Default tasks & due dates** (`/playbook`) — kickoff tasks, auto-assign,
   per-section exceptions, waterfall due dates off the signing date.
5. **Change Asana connection** → the first-run wizard a client would see on install.
6. Optionally: `python3 -m csms poll` — the hands-off DocuSign path.

---

## Architecture, in one pass

One engine, many front doors. `build_project(source, dry_run=...)` in
`csms/engine.py` is the only thing that builds a project; every entry point is a
thin adapter over it.

```
contract PDF
   → csms/parser.py      pdfplumber; glyph+font heuristics → sections/tasks
   → csms/engine.py      BuildPlan  (dry-run stops here — offline, no creds)
   → csms/playbook.py    overlay: kickoff tasks, assignees, due dates
   → csms/asana_client.py  stdlib urllib; creates project/sections/tasks
```

Entry points: `cli.py` · `webapp.py` (Flask UI + JSON API) · `desktop.py`
(PyWebview around the same Flask app) · `poll.py` (DocuSign auto-trigger).

Worth knowing:
- **No SDKs.** Asana and DocuSign clients are stdlib `urllib`, with an injectable
  `transport`, which is why the whole orchestration is unit-tested offline.
- **The parser is the risky part.** It reads bold/glyph/font cues, so it's
  sensitive to contract formatting — see `CONTRACT_FORMATTING.md`. The editable
  preview is the permanent safety net, deliberately not a temporary one.
- **Idempotency is by project name** for the manual flow, and by **DocuSign
  envelope id** (`state/processed_envelopes.json`) for the auto flow.

---

## Security posture

- Contracts are never persisted — each upload goes to a short-lived temp file
  that's deleted in a `finally`. Parsing is fully local; no cloud parser.
- Secrets are never in the bundle: desktop uses the OS keychain via `keyring`,
  hosted uses `.env` (git-ignored, `chmod 600`). `csms/config.py` is the single
  read point and never logs values.
- DocuSign auth is JWT grant, **outbound polling only** — no public inbound
  endpoint to defend. A Connect webhook would need one; polling was chosen partly
  to avoid that.
- No remote fonts/CDN/analytics in the UI — nothing phones home on launch.
- `validate_pdf()` enforces magic-byte + size limits (25 MB) before parsing.

---

## Known gaps — the honest list

1. **Live assignment + due dates have never been verified end-to-end.** Everything
   is confirmed through the engine and the API payloads, but no real Asana task has
   been observed carrying the assignee/due date. *Best thing to prove on this call.*
2. **A build that fails partway leaves a partial project.** A re-run then sees the
   name and skips, silently leaving it incomplete; `--force` makes a full duplicate
   rather than resuming. No resume/repair path exists yet.
3. **Not packaged.** Mac and PC builds (PyInstaller + installers) aren't started.
   Code signing is deliberately deferred — the client accepted the unsigned-app
   warning.
4. **DocuSign is sandbox-only.** Proven end-to-end in demo; production needs the
   Integration Key promoted and `.env` swapped. Nothing is scheduled — no
   launchd/cron is installed, so the auto-trigger only runs when invoked by hand.
5. **Playbook is empty until someone fills it in.** The wizard exists; the real
   people and offsets haven't been entered.
6. Cosmetic: Asana members with hidden profiles show as "Private User" in the
   assignee dropdowns and can't be told apart.

---

## Questions worth putting to the developer

- Hosting shape if this ever moves off the desktop — the engine is UI/OS-agnostic
  on purpose, and the Flask layer already doubles as a callable JSON API.
- Whether name-based idempotency is good enough, or the manual flow should key on
  something sturdier (the auto flow already uses envelope id).
- Partial-failure recovery: resume-in-place vs. delete-and-retry.
- Token model for a client install: personal PAT vs. a dedicated service account.
