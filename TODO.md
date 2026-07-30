# CSMS — To-do / deferred

Tracking work parked for later. Status of the built system is in README.md / CSMS_App_Plan.md.

## Playbook
- [x] Wire the playbook into the desktop app (2026-07-27): built a `/playbook` setup
  wizard (`csms/playbook_store.py` + routes in `csms/webapp.py`) — kickoff tasks,
  section assignees, due-date offsets, all editable in the UI (no hand-edited YAML
  needed for the desktop client). Saves to a per-OS app-data JSON file (survives
  reinstalls, not inside the frozen bundle). `/api/build` auto-loads it in desktop
  mode; main page gained a "Signing date" field. `playbook.example.yaml` / CLI
  `--playbook` flag still exist for JB's own CLI use, untouched.
- [x] Requirement captured: every new project includes a **"Verify contract / project details"** task — the wizard auto-seeds this on first load if nothing's saved yet.
- [x] **Editable preview (2026-07-29):** per-contract assignees/due dates are now adjusted
  in the preview (on the real parsed sections) rather than pre-configured. The wizard sets
  DEFAULTS only; Step 2 "per-section exceptions" was removed from it. `plan_from_dict()` +
  `build_from_plan()` in engine.py build the edited plan verbatim instead of re-parsing.
  *Note: `by_section` is still honoured by `csms/playbook.py` for hand-written playbooks,
  since the CLI and DocuSign poll have no UI to edit in.*
- [ ] CSMS still needs to actually fill in the wizard with their real assignee emails/offsets (or JB does it during onboarding) — building it doesn't populate it.
- [ ] Live-test assignment + due dates against the board using a real Asana-member email (example.com addresses won't resolve).

## DocuSign auto-trigger
- [x] DocuSign JWT auth + REST working **live in the demo/sandbox** (`csms poll` runs clean).
- [x] End-to-end test: pushed a sample contract through DocuSign demo, completed it, ran `csms poll` → real auto-build into Asana (2026-07-27, project https://app.asana.com/0/1216924620417515).
- [ ] **Go-Live to production**: ~20 successful demo API calls, then promote the Integration Key; swap `.env` to production BASE_URI / OAUTH_HOST / Account ID / User ID.
- [ ] (Optional) Set `DOCUSIGN_FOLDER_ID` to scope to the sponsorship folder.
- [ ] Choose the trigger mechanism: scheduled poll (launchd/cron) vs Connect webhook. *Both call the same `poll_once()`.*
- STATUS (2026-07-27): not scheduled anywhere (no launchd/cron installed) — CSMS chose the desktop-app route below instead, at least for now.

## Client desktop app delivery (CSMS chose this route, 2026-07-27)
CSMS wants their own copy of the desktop app, manual button-push only — no DocuSign
auto-trigger. They've accepted the unsigned-app / "unidentified developer" warning risk
for now, so code-signing is NOT a blocker to ship. Need **both a Mac and a PC build**.
- [x] First-run setup wizard (`csms/credentials.py` + `/setup` route in `csms/webapp.py`):
  client pastes their own Asana PAT, picks their workspace/team from their real Asana
  account, stored in the OS keychain via `keyring` — never in `.env`, never bundled.
  `csms.desktop` now gates on this (`create_app(desktop=True)`); hosted `csms.webapp`
  unaffected (still `.env`-based). Tests: tests/test_credentials.py,
  tests/test_webapp.py wizard tests, tests/test_asana.py list_workspaces/list_teams.
- [x] Playbook config is now a wizard, not hand-edited YAML (see Playbook section above).
- [ ] **PyInstaller freeze — Mac build** (.app + .dmg).
- [ ] **PyInstaller freeze — PC build** (.exe + Inno Setup/NSIS installer).
- [ ] Clean-machine test both builds (no Python installed).
- [ ] Code-signing: deferred/skipped per client's explicit go-ahead — revisit if it
  becomes a problem for them (Apple Developer ID ~$99/yr, Windows Authenticode ~$100–400/yr).
