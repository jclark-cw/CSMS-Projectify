#!/usr/bin/env python3
"""csms.webapp — the "Projectify" web UI / API (Flask), over the engine.

One codebase, three futures: run locally (`python3 -m csms.webapp`), wrap with
PyWebview into a desktop/click-install (`csms.desktop`), or deploy as a single-tenant
hosted URL. The /api routes double as the Zapier/DocuSign-callable API.

Flow: upload a contract PDF → preview the plan → optionally create it in Asana. The
file stays in the browser (no re-upload needed); each request writes a short-lived
temp file that is deleted immediately — contracts are never persisted. Live creation
is idempotent by project name (re-create is skipped unless forced).
"""

from __future__ import annotations

import json
import os
import tempfile

from flask import (Flask, request, render_template_string, jsonify,
                    redirect, url_for)

from .engine import build_project, plan_to_dict, plan_from_dict, build_from_plan
from .parser import InvalidPDFError
from .asana_client import AsanaError, list_workspaces, list_teams, list_users
from .credentials import CredentialStore
from . import playbook_store

MAX_MB = 25


def _build_from_upload(file, **kwargs):
    """Run the engine over an uploaded file via a short-lived temp file (deleted)."""
    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        file.save(path)
        os.close(fd)
        return build_project(path, max_pdf_mb=MAX_MB, **kwargs)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _friendly_asana_error(exc, desktop: bool) -> str:
    """Turn a raw Asana failure into something a non-technical operator can act on.

    Only warns about a partial project when a write could actually have happened —
    a failed pre-flight lookup (GET) leaves nothing behind, and telling someone to
    go hunt for a stuck project that cannot exist is worse than saying nothing.
    """
    if getattr(exc, "is_auth_error", False):
        msg = ("Asana wouldn't accept the connection. The access token may have "
               "been revoked or expired, or it may not have access to this workspace.")
        return msg + (" Reconnect Asana from the setup screen, then try again."
                      if desktop else " Check the ASANA_PAT in your .env.")
    msg = str(exc)
    if getattr(exc, "may_have_written", True):
        msg += (" — a project may have been partially created in Asana before this "
                "failed; check the workspace before re-running to avoid a duplicate.")
    return msg


def create_app(desktop: bool = False) -> Flask:
    """Build the Flask app.

    desktop=True is used only by csms.desktop: it gates the first-run setup
    wizard (client enters their own Asana token, stored in the OS keychain via
    csms.credentials) and makes /api/build use those stored credentials
    instead of .env. The hosted web app (desktop=False, the default) is
    unchanged — it keeps using AsanaClient.from_config() as before.
    """
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = int(MAX_MB * 1024 * 1024)
    app.config["DESKTOP"] = desktop
    app.config["CRED_STORE"] = CredentialStore() if desktop else None
    app.config["PLAYBOOK_PATH"] = None  # None = playbook_store's default app-data path
    app.jinja_env.globals["desktop"] = desktop

    @app.get("/")
    def index():
        store = app.config["CRED_STORE"]
        if desktop and not store.has_credentials():
            return redirect(url_for("setup"))
        return render_template_string(PAGE, plan=None, error=None, filename=None)

    @app.get("/setup")
    def setup():
        return render_template_string(SETUP_PAGE, error=None)

    @app.post("/api/setup/workspaces")
    def api_setup_workspaces():
        token = (request.get_json(silent=True) or {}).get("token", "").strip()
        if not token:
            return jsonify(error="paste your Asana Personal Access Token"), 400
        try:
            workspaces = list_workspaces(token)
        except AsanaError as e:
            return jsonify(error=f"couldn't connect with that token: {e}"), 400
        return jsonify(workspaces=[{"gid": w["gid"], "name": w["name"]} for w in workspaces])

    @app.post("/api/setup/teams")
    def api_setup_teams():
        body = request.get_json(silent=True) or {}
        token = body.get("token", "").strip()
        workspace_gid = body.get("workspace_gid", "").strip()
        if not token or not workspace_gid:
            return jsonify(error="missing token or workspace_gid"), 400
        teams = list_teams(token, workspace_gid)
        return jsonify(teams=[{"gid": t["gid"], "name": t["name"]} for t in teams])

    @app.post("/api/setup/save")
    def api_setup_save():
        body = request.get_json(silent=True) or {}
        token = body.get("token", "").strip()
        workspace_gid = body.get("workspace_gid", "").strip()
        team_gid = (body.get("team_gid") or "").strip() or None
        if not token or not workspace_gid:
            return jsonify(error="missing token or workspace_gid"), 400
        store = app.config["CRED_STORE"]
        store.set_pat(token)
        store.set_workspace_gid(workspace_gid)
        store.set_team_gid(team_gid)
        return jsonify(ok=True)

    @app.post("/api/setup/clear")
    def api_setup_clear():
        app.config["CRED_STORE"].clear()
        return jsonify(ok=True)

    @app.get("/playbook")
    def playbook_page():
        return render_template_string(PLAYBOOK_PAGE, error=None)

    @app.get("/api/playbook")
    def api_playbook_get():
        return jsonify(playbook_store.load_playbook(app.config["PLAYBOOK_PATH"]))

    @app.get("/api/playbook/users")
    def api_playbook_users():
        """Workspace members, for the assignee pickers. [] if unavailable —
        the wizard falls back to free-text entry rather than blocking.

        `reason` tells the UI *why* the list is empty so it can say so, instead
        of silently degrading to text boxes that look like a broken dropdown.
        """
        store = app.config["CRED_STORE"]
        if store is None or not store.has_credentials():
            return jsonify(users=[], reason="not_connected")
        users = list_users(store.get_pat(), store.get_workspace_gid())
        if not users:
            return jsonify(users=[], reason="lookup_failed")
        # Asana returns the literal name "Private User" (and no email) for members
        # whose profile this token can't see. Several of them are indistinguishable
        # in a dropdown, so they're not offerable choices.
        selectable = [u for u in users
                      if (u.get("name") or "").strip().lower() != "private user"]
        if not selectable:
            return jsonify(users=[], reason="no_visible_members")
        return jsonify(users=[{"gid": u.get("gid"), "name": u.get("name"),
                               "email": u.get("email")} for u in selectable], reason=None)

    @app.post("/api/playbook/preview-sections")
    def api_playbook_preview_sections():
        """Dry-run parse an uploaded sample contract to list its real section names,
        so the wizard's assignee/due-date rows can target actual names, not guesses."""
        file = request.files.get("contract")
        if not file or not file.filename:
            return jsonify(error="no file provided (field 'contract')"), 400
        try:
            result = _build_from_upload(file, dry_run=True)
        except InvalidPDFError as e:
            return jsonify(error=str(e)), 400
        except Exception as e:  # never let an unhandled error fall to Flask's HTML 500
            app.logger.exception("api_playbook_preview_sections failed")
            return jsonify(error=f"Preview failed: {e}"), 500
        names = sorted({s.name for s in result.plan.sections})
        return jsonify(sections=names)

    @app.post("/api/playbook/save")
    def api_playbook_save():
        data = request.get_json(silent=True) or {}
        if not isinstance(data.get("default_sections", []), list):
            return jsonify(error="default_sections must be a list"), 400
        if not isinstance(data.get("assignees", {}), dict):
            return jsonify(error="assignees must be an object"), 400
        if not isinstance(data.get("due_dates", {}), dict):
            return jsonify(error="due_dates must be an object"), 400
        playbook_store.save_playbook(data, app.config["PLAYBOOK_PATH"])
        return jsonify(ok=True)

    @app.post("/preview")
    def preview():
        # Server-rendered fallback for no-JS; the app normally uses /api/preview.
        file = request.files.get("contract")
        if not file or not file.filename:
            return render_template_string(
                PAGE, plan=None, error="Choose a contract PDF to preview.",
                filename=None), 400
        try:
            result = _build_from_upload(file, dry_run=True)
        except InvalidPDFError as e:
            return render_template_string(
                PAGE, plan=None, error=str(e), filename=file.filename), 400
        return render_template_string(
            PAGE, plan=result.plan, error=None, filename=file.filename)

    @app.post("/api/preview")
    def api_preview():
        """Parse the contract and return the plan the operator will edit.

        In desktop mode the saved playbook is applied here (not at build time),
        so the preview already shows the assignees and due dates the defaults
        produce — which is what makes them adjustable before anything is created.
        """
        file = request.files.get("contract")
        if not file or not file.filename:
            return jsonify(error="no file provided (field 'contract')"), 400
        playbook = None
        signed_date = (request.form.get("signed_date") or "").strip() or None
        if desktop:
            playbook = playbook_store.load_playbook(app.config["PLAYBOOK_PATH"]) or None
        try:
            result = _build_from_upload(file, dry_run=True, playbook=playbook,
                                        signed_date=signed_date)
        except InvalidPDFError as e:
            return jsonify(error=str(e)), 400
        except Exception as e:  # never let an unhandled error fall to Flask's HTML 500
            app.logger.exception("api_preview failed")
            return jsonify(error=f"Preview failed: {e}"), 500
        return jsonify(plan_to_dict(result.plan))

    @app.post("/api/build")
    def api_build():
        """Live: create the Asana project. Idempotent by name.

        Hosted mode (desktop=False): creds from .env, as before. Desktop mode:
        creds from the OS keychain (set up via the /setup wizard) — never .env —
        and the saved playbook (default tasks/assignees/due dates, set up via the
        /playbook wizard) is applied automatically if one has been saved.
        """
        name = (request.form.get("name") or "").strip() or None
        force = request.form.get("force", "").lower() in ("1", "true", "yes", "on")
        edited_plan = request.form.get("plan")   # JSON from the edited preview
        file = request.files.get("contract")
        if not edited_plan and (not file or not file.filename):
            return jsonify(error="no file provided (field 'contract')"), 400
        asana = None
        playbook = None
        signed_date = (request.form.get("signed_date") or "").strip() or None
        if desktop:
            asana = app.config["CRED_STORE"].build_client()
            if asana is None:
                return jsonify(error="Asana isn't connected yet — finish setup first."), 400
            playbook = playbook_store.load_playbook(app.config["PLAYBOOK_PATH"]) or None
        try:
            if edited_plan:
                # The operator adjusted assignees/due dates in the preview — build
                # exactly that. Re-parsing here would throw their edits away.
                plan = plan_from_dict(json.loads(edited_plan))
                if not plan.sections:
                    return jsonify(error="Nothing to create — the plan is empty."), 400
                result = build_from_plan(plan, asana=asana, project_name=name, force=force)
            else:
                result = _build_from_upload(file, dry_run=False, playbook=playbook,
                                            signed_date=signed_date,
                                            project_name=name, force=force, asana=asana)
        except ValueError as e:  # malformed plan JSON
            return jsonify(error=f"Couldn't read the edited plan: {e}"), 400
        except InvalidPDFError as e:
            return jsonify(error=str(e)), 400
        except AsanaError as e:  # must precede RuntimeError — AsanaError subclasses it
            return jsonify(error=_friendly_asana_error(e, desktop),
                           needs_reconnect=bool(e.is_auth_error and desktop)), 502
        except RuntimeError as e:  # missing creds / other config failure
            return jsonify(error=str(e)), 502
        except Exception as e:  # never let an unhandled error fall to Flask's HTML 500
            app.logger.exception("api_build failed")
            return jsonify(error=f"Build failed: {e}"), 500
        return jsonify(existed=result.existed, project_url=result.project_url,
                       created=result.created, warnings=result.warnings)

    @app.errorhandler(413)
    def too_large(_e):
        return render_template_string(
            PAGE, plan=None, error=f"File too large (max {MAX_MB} MB).",
            filename=None), 413

    return app


# Brand tokens taken from cybersecuritymarketingsociety.com's own design system
# (their Webflow custom properties), so the tool reads as CSMS's rather than generic.
#
# FONTS: Poppins/Instrument Sans are NAMED but deliberately NOT fetched from a CDN.
# The desktop app must work offline, and a cybersecurity client shouldn't have their
# app phoning a font host on every launch. They render in the brand faces when
# installed locally and fall back to the system stack otherwise.
#
# Shared by all three pages — a single source of truth. These used to be duplicated
# per page, which is how the SETUP page lost its `.ok.hide` rule and showed a
# "Connected" banner on load.
BASE_CSS = """
  :root {
    --ink:#010003;            /* swatch--dark-1 */
    --muted:#5f5f6b;
    --placeholder:#9a99a6;    /* lighter than --muted, so hint text in a field
                                 never reads as a filled-in value */
    --line:#3532331a;         /* theme---border */
    --accent:#563aff;         /* swatch--brand */
    --accent-hover:#6435e7;   /* swatch--purple (their button hover) */
    --accent-bg:#f7f5ff;      /* swatch--purple-light-2 */
    --accent-border:#ece2ff;  /* swatch--purple-light */
    --bg:#f9fafb;             /* theme---background */
    --card:#ffffff;
    --err:#aa2808;            /* swatch--orange-dark */
    --errbg:#fff3f0;          /* swatch--orange-light */
    --ok:#016341;             /* swatch--green-dark-1 */
    --okbg:#e3fff4;           /* swatch--green-light-2 */
    --warnbg:#fffbea;         /* tint of swatch--yellow #ffdb04 */
    --warnline:#f0d43a;
    --radius:1rem;            /* radius--main */
    --radius-sm:.5rem;        /* radius--small */
    --radius-btn:.875rem;     /* radius--small-main */
    --font-body:"Instrument Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    --font-head:Poppins,"Instrument Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  }
  * { box-sizing:border-box; }
  body { margin:0; font:16px/1.55 var(--font-body); color:var(--ink); background:var(--bg); }
  h1, h2, h3 { font-family:var(--font-head); letter-spacing:0; }
  h1 { font-size:1.55rem; font-weight:600; margin:0 0 .25rem; }
  a { color:var(--accent); }
  :focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  .wrap { max-width:760px; margin:0 auto; padding:2.5rem 1.25rem 4rem; }
  .sub { color:var(--muted); margin:0 0 2rem; }
  .btn { border:0; border-radius:var(--radius-btn); background:var(--accent); color:#fff;
         padding:.7rem 1.4rem; font-size:1rem; font-weight:600; font-family:var(--font-body);
         cursor:pointer; transition:background .15s,border-color .15s,color .15s; }
  .btn:hover { background:var(--accent-hover); }
  .btn:disabled { background:#c9c6d6; cursor:not-allowed; }
  .btn.secondary { background:var(--card); color:var(--ink); border:1px solid var(--line); }
  .btn.secondary:hover { background:var(--card); border-color:var(--accent); color:var(--accent); }
  .err { background:var(--errbg); color:var(--err); border:1px solid #f2d9d1;
         border-radius:var(--radius-sm); padding:.75rem 1rem; margin:1.25rem 0; }
  .ok { background:var(--okbg); color:var(--ok); border:1px solid #bfe9d8;
        border-radius:var(--radius-sm); padding:.85rem 1rem; margin-top:1rem; }
  .ok a { color:var(--ok); font-weight:600; }
  .panel { margin-top:2rem; padding:1.5rem; border:1px solid var(--line);
           border-radius:var(--radius); background:var(--card); }
  .panel label { display:block; font-size:.85rem; color:var(--muted); margin:0 0 .35rem; }
  .panel input[type=text], .panel input[type=date] { width:100%; padding:.6rem .7rem;
    border:1px solid var(--line); border-radius:var(--radius-sm); font-size:1rem;
    font-family:var(--font-body); }
  .panel .row { display:flex; gap:.75rem; align-items:center; margin-top:1rem; flex-wrap:wrap; }
  /* opacity:1 because Firefox dims placeholders by default, which would make
     this lighter again on top of the colour we're already choosing. */
  ::placeholder { color:var(--placeholder); opacity:1; }
  .hide { display:none; }
  .muted { color:var(--muted); font-size:.88rem; }
"""


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Projectify — Contract → Asana</title>
<style>""" + BASE_CSS + """
  /* NB: this is a <label>, which defaults to display:inline — with block-level
     children that fragments the dashed border and breaks the padding. Must be
     a block/flex container. */
  .drop { display:flex; flex-direction:column; align-items:center; gap:.75rem;
          width:100%; border:1.5px dashed var(--accent-border); border-radius:var(--radius);
          background:var(--card); padding:2.25rem 1.5rem; text-align:center;
          cursor:pointer; transition:border-color .15s,background .15s; }
  .drop:hover { border-color:var(--accent); background:var(--accent-bg); }
  .drop:focus-within { outline:2px solid var(--accent); outline-offset:2px; }
  .drop.over { border-color:var(--accent); background:var(--accent-bg); }
  .drop input[type=file] { display:none; }
  .drop-title { font-weight:500; font-family:var(--font-head); }
  .pick { display:inline-block; cursor:pointer; border:1px solid var(--line);
          border-radius:var(--radius-sm); padding:.55rem 1rem; background:var(--bg);
          font-weight:500; font-size:.92rem; transition:border-color .15s,color .15s; }
  .drop:hover .pick { border-color:var(--accent); color:var(--accent); }
  .fname { margin:0; color:var(--muted); font-size:.9rem; }
  .fname:empty { display:none; }  /* no stray gap before a file is chosen */
  .summary { display:flex; gap:.6rem; flex-wrap:wrap; margin:2rem 0 1rem; }
  .stat { background:var(--card); border:1px solid var(--line);
          border-radius:var(--radius-sm); padding:.7rem 1.1rem; }
  .stat b { display:block; font-size:1.4rem; font-weight:600; font-family:var(--font-head);
            color:var(--accent); }
  .stat span { color:var(--muted); font-size:.82rem; }
  .group { color:var(--muted); font-size:.8rem; text-transform:uppercase; letter-spacing:.04em; margin:1.6rem 0 .5rem; }
  .sec { background:var(--card); border:1px solid var(--line);
         border-radius:var(--radius); padding:1.1rem 1.3rem; margin:.6rem 0; }
  .sec h3 { margin:0 0 .6rem; font-size:1.02rem; font-weight:600; }
  .sec h3 small { color:var(--muted); font-weight:400; }
  .task { display:flex; gap:.75rem; align-items:flex-start; justify-content:space-between;
          padding:.5rem 0; border-top:1px solid var(--line); }
  .task:first-of-type { border-top:0; }
  .taskmain { min-width:0; flex:1; }
  .taskctl { display:flex; gap:.4rem; flex:0 0 auto; }
  .taskctl select, .taskctl input[type=date], .secbulk select, .secbulk input[type=date] {
    padding:.35rem .5rem; border:1px solid var(--line); border-radius:var(--radius-sm);
    font-size:.85rem; font-family:var(--font-body); background:var(--card); max-width:170px; }
  .secbulk { font-size:.8rem; margin:0 0 .6rem; display:flex; gap:.4rem; align-items:center;
             flex-wrap:wrap; }
  .note { color:var(--muted); font-size:.9rem; margin:.15rem 0 0 0; }
  .signrow { display:flex; gap:.6rem; align-items:center; flex-wrap:wrap; margin-top:1.1rem; }
  .signrow label { font-size:.9rem; }
  .signrow input[type=date] { padding:.5rem .6rem; border:1px solid var(--line);
    border-radius:var(--radius-sm); font-size:.95rem; font-family:var(--font-body); }
  @media (max-width:620px) {
    .task { flex-direction:column; gap:.4rem; }
    .taskctl { width:100%; }
    .taskctl select, .taskctl input[type=date] { flex:1; max-width:none; }
  }
</style>
</head>
<body>
<div class="wrap">
  <h1>Projectify</h1>
  <p class="sub">Drop a signed contract PDF, preview the Asana project, then create it.
  {% if desktop %}<a href="#" id="changeConn" style="margin-left:.5rem;">Change Asana connection</a>
  · <a href="/playbook">Default tasks &amp; due dates</a>{% endif %}</p>
  {% if desktop %}
  <div id="disconnectPanel" class="panel hide">
    Disconnect this app from Asana? You'll need to reconnect before creating projects.
    <div class="row">
      <button class="btn" id="disconnectYes" type="button">Disconnect</button>
      <button class="btn secondary" id="disconnectNo" type="button">Cancel</button>
    </div>
  </div>
  <script>
    // Deliberately NOT confirm(): native JS dialogs are unavailable in some
    // webview hosts, where confirm() returns false and the action silently
    // does nothing. In-page confirmation works everywhere.
    (function () {
      var panel = document.getElementById('disconnectPanel');
      document.getElementById('changeConn').addEventListener('click', function(ev){
        ev.preventDefault();
        panel.classList.remove('hide');
      });
      document.getElementById('disconnectNo').addEventListener('click', function(){
        panel.classList.add('hide');
      });
      document.getElementById('disconnectYes').addEventListener('click', function(){
        fetch('/api/setup/clear', {method:'POST'})
          .then(function(){ window.location.href = '/setup'; });
      });
    })();
  </script>
  {% endif %}

  <form id="form" method="post" action="/preview" enctype="multipart/form-data">
    <label class="drop" id="drop">
      <input type="file" name="contract" id="file" accept="application/pdf" required>
      <div class="drop-title">Drag a signed contract PDF here</div>
      <span class="pick">or choose a file</span>
      <p class="fname" id="fname">{% if filename %}Selected: {{ filename }}{% endif %}</p>
    </label>
    {% if desktop %}
    <div class="signrow">
      <label for="signedDate">Contract signed on</label>
      <input type="date" id="signedDate">
      <span class="muted">Due dates are calculated from this.</span>
    </div>
    {% endif %}
    <div style="margin-top:1.1rem;"><button class="btn" id="previewBtn" type="submit">Preview project</button></div>
  </form>

  <div id="error" class="err hide"></div>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}

  <div id="results"></div>

  <div id="createPanel" class="panel hide">
    <label for="pname">Asana project name</label>
    <input type="text" id="pname" placeholder="Project name">
    <div class="row">
      <button class="btn" id="createBtn" type="button">Create in Asana</button>
      <span class="muted">Creates a real project in the connected Asana workspace.</span>
    </div>
    <div id="outcome"></div>
  </div>

  {% if plan %}
    <div class="summary">
      <div class="stat"><b>{{ plan.section_count }}</b><span>sections</span></div>
      <div class="stat"><b>{{ plan.task_count }}</b><span>tasks</span></div>
      <div class="stat"><b>{{ plan.note_count }}</b><span>notes</span></div>
    </div>
    {% set ns = namespace(group=None) %}
    {% for s in plan.sections %}
      {% if s.group and s.group != ns.group %}{% set ns.group = s.group %}<div class="group">{{ s.group }}</div>{% endif %}
      <div class="sec"><h3>{{ s.name }} <small>· {{ s.tasks|length }} tasks</small></h3>
        {% for t in s.tasks %}<div class="task">{{ t.name }}{% if t.notes %}<div class="note">{{ t.notes }}</div>{% endif %}</div>{% endfor %}
      </div>
    {% endfor %}
  {% endif %}
</div>

<script>
(function () {
  var selectedFile = null;
  var PLAN = null;      // the previewed plan; edits are applied on top of this
  var MEMBERS = [];     // workspace members, for the assignee pickers
  var fileInput = document.getElementById('file'),
      drop = document.getElementById('drop'),
      fname = document.getElementById('fname'),
      form = document.getElementById('form'),
      previewBtn = document.getElementById('previewBtn'),
      errorBox = document.getElementById('error'),
      results = document.getElementById('results'),
      createPanel = document.getElementById('createPanel'),
      pname = document.getElementById('pname'),
      signedDate = document.getElementById('signedDate'),
      createBtn = document.getElementById('createBtn'),
      outcome = document.getElementById('outcome');

  function esc(s){ var d=document.createElement('div'); d.textContent=s==null?'':s; return d.innerHTML; }
  function showErr(m){ errorBox.textContent=m; errorBox.classList.remove('hide'); }
  function clearErr(){ errorBox.classList.add('hide'); errorBox.textContent=''; }

  function setFile(f){
    selectedFile = f;
    fname.textContent = f ? 'Selected: ' + f.name : '';
    if (f) pname.value = f.name.replace(/\\.pdf$/i,'').replace(/_/g,' ').trim();
    if (signedDate && !signedDate.value) signedDate.value = new Date().toISOString().slice(0, 10);
    results.innerHTML=''; createPanel.classList.add('hide'); outcome.innerHTML=''; clearErr();
  }

  // Load workspace members up front so the preview's assignee pickers are ready.
  fetch('/api/playbook/users').then(function(r){ return r.json(); })
    .then(function(j){ MEMBERS = j.users || []; }).catch(function(){ MEMBERS = []; });

  fileInput.addEventListener('change', function(){ if (fileInput.files.length) setFile(fileInput.files[0]); });
  ['dragover','dragenter'].forEach(function(e){ drop.addEventListener(e, function(ev){ ev.preventDefault(); drop.classList.add('over'); }); });
  ['dragleave','drop'].forEach(function(e){ drop.addEventListener(e, function(ev){ ev.preventDefault(); drop.classList.remove('over'); }); });
  drop.addEventListener('drop', function(ev){ if (ev.dataTransfer.files.length){ fileInput.files = ev.dataTransfer.files; setFile(ev.dataTransfer.files[0]); } });

  form.addEventListener('submit', function(ev){
    if (!selectedFile) return;            // let the no-JS form post if somehow no file in JS
    ev.preventDefault();
    clearErr(); results.innerHTML='Parsing…'; createPanel.classList.add('hide');
    var fd = new FormData(); fd.append('contract', selectedFile);
    if (signedDate && signedDate.value) fd.append('signed_date', signedDate.value);
    fetch('/api/preview', {method:'POST', body:fd})
      .then(function(r){ return r.json().then(function(j){ return {ok:r.ok, j:j}; }); })
      .then(function(res){
        if (!res.ok || res.j.error){ results.innerHTML=''; showErr(res.j.error || 'Preview failed.'); return; }
        renderPlan(res.j); createPanel.classList.remove('hide'); outcome.innerHTML='';
      })
      .catch(function(){ results.innerHTML=''; showErr('Could not reach the server.'); });
  });

  // The preview is editable: the plan shown here — including any per-task changes
  // made below — is exactly what gets built. Nothing is re-parsed at create time.
  function assigneeSelect(value){
    if (!MEMBERS.length){
      return '<input type="text" class="t-assignee" value="'+esc(value||'')+'" placeholder="email">';
    }
    var opts = '<option value="">(unassigned)</option>'
      + '<option value="me"'+(value === 'me' ? ' selected' : '')+'>Me</option>';
    var matched = (value === 'me');
    MEMBERS.forEach(function(m){
      var sel = (value && (value === m.gid || value === m.email)) ? ' selected' : '';
      if (sel) matched = true;
      opts += '<option value="'+esc(m.gid)+'"'+sel+'>'+esc(m.name || m.email || m.gid)+'</option>';
    });
    if (value && !matched){
      opts += '<option value="'+esc(value)+'" selected>'+esc(value)+'</option>';
    }
    return '<select class="t-assignee">'+opts+'</select>';
  }

  function renderPlan(p){
    PLAN = p;
    var html = '<div class="summary">'
      + '<div class="stat"><b>'+p.section_count+'</b><span>sections</span></div>'
      + '<div class="stat"><b>'+p.task_count+'</b><span>tasks</span></div>'
      + '<div class="stat"><b>'+p.note_count+'</b><span>notes</span></div></div>'
      + '<p class="muted" style="margin:0 0 1rem;">Adjust anything below before creating it — '
      + 'these are the defaults from <a href="/playbook">Default tasks &amp; due dates</a>.</p>';
    var lastGroup = null;
    p.sections.forEach(function(s, si){
      if (s.group && s.group !== lastGroup){ lastGroup = s.group; html += '<div class="group">'+esc(s.group)+'</div>'; }
      html += '<div class="sec" data-si="'+si+'">'
        + '<h3>'+esc(s.section)+' <small>· '+s.tasks.length+' tasks</small></h3>'
        + '<div class="secbulk muted">Set for the whole section: '
        + '<select class="bulk-assignee"><option value="">— assign to —</option></select> '
        + '<input type="date" class="bulk-due" title="Set every task in this section to this date">'
        + '</div>';
      s.tasks.forEach(function(t, ti){
        html += '<div class="task" data-ti="'+ti+'">'
          + '<div class="taskmain">'+esc(t.name)
          + (t.notes ? '<div class="note">'+esc(t.notes)+'</div>' : '') + '</div>'
          + '<div class="taskctl">' + assigneeSelect(t.assignee)
          + '<input type="date" class="t-due" value="'+esc(t.due_on||'')+'"></div>'
          + '</div>';
      });
      html += '</div>';
    });
    results.innerHTML = html;
    wirePlanEditing();
  }

  function wirePlanEditing(){
    // Populate the per-section bulk pickers from the same member list.
    results.querySelectorAll('.bulk-assignee').forEach(function(sel){
      if (!MEMBERS.length){ sel.parentNode.style.display = 'none'; return; }
      MEMBERS.forEach(function(m){
        var o = document.createElement('option');
        o.value = m.gid; o.textContent = m.name || m.email || m.gid;
        sel.appendChild(o);
      });
      sel.addEventListener('change', function(){
        if (!sel.value) return;
        sel.closest('.sec').querySelectorAll('.t-assignee').forEach(function(f){ f.value = sel.value; });
        sel.value = '';
      });
    });
    results.querySelectorAll('.bulk-due').forEach(function(inp){
      inp.addEventListener('change', function(){
        if (!inp.value) return;
        inp.closest('.sec').querySelectorAll('.t-due').forEach(function(f){ f.value = inp.value; });
      });
    });
  }

  // Read the on-screen edits back into the plan that will be sent to Asana.
  function collectPlan(){
    if (!PLAN) return null;
    var out = JSON.parse(JSON.stringify(PLAN));
    results.querySelectorAll('.sec').forEach(function(secEl){
      var s = out.sections[+secEl.dataset.si];
      if (!s) return;
      secEl.querySelectorAll('.task').forEach(function(taskEl){
        var t = s.tasks[+taskEl.dataset.ti];
        if (!t) return;
        var a = taskEl.querySelector('.t-assignee'), d = taskEl.querySelector('.t-due');
        t.assignee = a && a.value ? a.value : null;
        t.due_on = d && d.value ? d.value : null;
      });
    });
    return out;
  }

  createBtn.addEventListener('click', function(){ askConfirm(false); });

  // In-page confirmation rather than confirm(): native dialogs are suppressed or
  // unimplemented in some webview hosts, where confirm() returns false and the
  // Create button would silently do nothing.
  function askConfirm(force){
    if (!selectedFile) return;
    var name = pname.value.trim();
    if (!name){ showErr('Give the project a name first.'); return; }
    outcome.innerHTML = '<div class="panel" style="margin-top:1rem;">'
      + 'Create the project "'+esc(name)+'" in Asana?'
      + '<div class="row"><button class="btn" id="confirmYes" type="button">Yes, create it</button>'
      + '<button class="btn secondary" id="confirmNo" type="button">Cancel</button></div></div>';
    document.getElementById('confirmYes').addEventListener('click', function(){ doBuild(force); });
    document.getElementById('confirmNo').addEventListener('click', function(){ outcome.innerHTML = ''; });
  }

  function doBuild(force){
    if (!selectedFile) return;
    var name = pname.value.trim();
    createBtn.disabled = true; outcome.innerHTML = '<p class="muted">Creating…</p>';
    var fd = new FormData(); fd.append('contract', selectedFile); fd.append('name', name);
    if (signedDate && signedDate.value) fd.append('signed_date', signedDate.value);
    if (force) fd.append('force', 'true');
    // Send the edited plan so on-screen changes are what actually get created.
    var edited = collectPlan();
    if (edited) fd.append('plan', JSON.stringify(edited));
    fetch('/api/build', {method:'POST', body:fd})
      .then(function(r){ return r.json().then(function(j){ return {ok:r.ok, j:j}; }); })
      .then(function(res){
        createBtn.disabled = false;
        if (!res.ok || res.j.error){
          outcome.innerHTML = '<div class="err">'+esc(res.j.error || 'Create failed.')
            + (res.j.needs_reconnect ? ' <a href="/setup">Reconnect Asana</a>' : '') + '</div>';
          return;
        }
        if (res.j.existed){
          outcome.innerHTML = '<div class="ok">Already in Asana — <a href="'+esc(res.j.project_url)+'" target="_blank">open project</a>. '
            + 'Skipped to avoid a duplicate. <button class="btn secondary" id="forceBtn" type="button">Create another anyway</button></div>';
          document.getElementById('forceBtn').addEventListener('click', function(){ askConfirm(true); });
        } else {
          var c = res.j.created || {};
          outcome.innerHTML = '<div class="ok">Created — <a href="'+esc(res.j.project_url)+'" target="_blank">open project</a> '
            + '('+(c.sections||0)+' sections, '+(c.tasks||0)+' tasks).</div>';
        }
      })
      .catch(function(){ createBtn.disabled = false; outcome.innerHTML = '<div class="err">Could not reach the server.</div>'; });
  }
})();
</script>
</body>
</html>"""


SETUP_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Projectify — Connect Asana</title>
<style>
""" + BASE_CSS + """
  .wrap { max-width:520px; }
  .step { background:var(--card); border:1px solid var(--line); border-radius:var(--radius);
          padding:1.5rem; margin:0 0 1rem; }
  .step h2 { margin:0 0 .5rem; font-size:1.05rem; font-weight:600; font-family:var(--font-head); }
  .step p.hint { color:var(--muted); font-size:.85rem; margin:.25rem 0 .9rem; }
  input[type=text], input[type=password], select {
    width:100%; padding:.6rem .7rem; border:1px solid var(--line);
    border-radius:var(--radius-sm); font-size:1rem; font-family:var(--font-body); }
  .btn { margin-top:.85rem; padding:.65rem 1.2rem; }
  .err { margin:.85rem 0 0; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Connect Projectify to Asana</h1>
  <p class="sub">One-time setup. Your token is stored in this computer's secure keychain — never in a file, never sent anywhere but Asana.</p>

  <div class="step" id="step1">
    <h2>1. Asana Personal Access Token</h2>
    <p class="hint">In Asana: profile photo → Settings → Apps tab → "Build new apps" → View developer console → Personal access tokens → + Create new token. Asana shows it once, so copy it right away.</p>
    <input type="password" id="token" placeholder="Paste your token">
    <button class="btn" id="connectBtn" type="button">Connect</button>
  </div>

  <div class="step hide" id="step2">
    <h2>2. Workspace</h2>
    <p class="hint">Which Asana workspace should new projects go in?</p>
    <select id="workspace"></select>
  </div>

  <div class="step hide" id="step3">
    <h2>3. Team <span class="hint" style="display:inline">(optional)</span></h2>
    <p class="hint">If your workspace has teams, pick one — otherwise leave as-is.</p>
    <select id="team"><option value="">(no team)</option></select>
    <button class="btn" id="finishBtn" type="button">Finish setup</button>
  </div>

  <div id="error" class="err hide"></div>
  <div id="done" class="ok hide">Connected — redirecting…</div>
</div>

<script>
(function () {
  var tokenEl = document.getElementById('token'),
      connectBtn = document.getElementById('connectBtn'),
      step2 = document.getElementById('step2'), workspaceEl = document.getElementById('workspace'),
      step3 = document.getElementById('step3'), teamEl = document.getElementById('team'),
      finishBtn = document.getElementById('finishBtn'),
      errorBox = document.getElementById('error'), done = document.getElementById('done');

  function showErr(m){ errorBox.textContent = m; errorBox.classList.remove('hide'); }
  function clearErr(){ errorBox.classList.add('hide'); errorBox.textContent = ''; }

  connectBtn.addEventListener('click', function(){
    var token = tokenEl.value.trim();
    if (!token) { showErr('Paste your Asana token first.'); return; }
    clearErr(); connectBtn.disabled = true; connectBtn.textContent = 'Connecting…';
    fetch('/api/setup/workspaces', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({token: token})})
      .then(function(r){ return r.json().then(function(j){ return {ok:r.ok, j:j}; }); })
      .then(function(res){
        connectBtn.disabled = false; connectBtn.textContent = 'Connect';
        if (!res.ok || res.j.error) { showErr(res.j.error || 'Could not connect.'); return; }
        workspaceEl.innerHTML = res.j.workspaces.map(function(w){
          return '<option value="'+w.gid+'">'+w.name+'</option>'; }).join('');
        step2.classList.remove('hide'); step3.classList.remove('hide');
        loadTeams();
      })
      .catch(function(){ connectBtn.disabled = false; connectBtn.textContent = 'Connect';
        showErr('Could not reach the server.'); });
  });

  function loadTeams(){
    fetch('/api/setup/teams', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({token: tokenEl.value.trim(), workspace_gid: workspaceEl.value})})
      .then(function(r){ return r.json(); })
      .then(function(j){
        var teams = j.teams || [];
        teamEl.innerHTML = '<option value="">(no team)</option>' + teams.map(function(t){
          return '<option value="'+t.gid+'">'+t.name+'</option>'; }).join('');
      })
      .catch(function(){});
  }
  workspaceEl.addEventListener('change', loadTeams);

  finishBtn.addEventListener('click', function(){
    clearErr(); finishBtn.disabled = true; finishBtn.textContent = 'Saving…';
    fetch('/api/setup/save', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({token: tokenEl.value.trim(), workspace_gid: workspaceEl.value, team_gid: teamEl.value})})
      .then(function(r){ return r.json().then(function(j){ return {ok:r.ok, j:j}; }); })
      .then(function(res){
        if (!res.ok || res.j.error) { finishBtn.disabled = false; finishBtn.textContent = 'Finish setup';
          showErr(res.j.error || 'Could not save.'); return; }
        done.classList.remove('hide');
        setTimeout(function(){ window.location.href = '/'; }, 800);
      })
      .catch(function(){ finishBtn.disabled = false; finishBtn.textContent = 'Finish setup';
        showErr('Could not reach the server.'); });
  });
})();
</script>
</body>
</html>"""


PLAYBOOK_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Projectify — Default tasks &amp; due dates</title>
<style>
""" + BASE_CSS + """
  .wrap { padding-bottom:5rem; }
  .card { background:var(--card); border:1px solid var(--line);
          border-radius:var(--radius); padding:1.5rem; margin:0 0 1.5rem; }
  .card h2 { margin:0 0 .3rem; font-size:1.05rem; font-weight:600; }
  .card p.hint { color:var(--muted); font-size:.85rem; margin:.15rem 0 1rem; }
  .card h3.substep { margin:1.6rem 0 .4rem; font-size:.92rem; font-weight:600;
                     font-family:var(--font-head); color:var(--accent); }
  .card h3.substep:first-of-type { margin-top:1rem; }
  .examples { color:var(--muted); font-size:.85rem; margin:.15rem 0 1rem; padding-left:1.15rem; }
  .examples li { margin:.2rem 0; }
  .warn { background:var(--warnbg); border:1px solid var(--warnline);
          border-radius:var(--radius-sm); padding:.75rem 1rem; margin:0 0 1.5rem; font-size:.88rem; }
  .row { display:grid; grid-template-columns:1fr 1fr 90px 34px; gap:.5rem; margin-bottom:.5rem; align-items:center; }
  .row.task-row { grid-template-columns:1fr 1fr 1fr 90px 34px; }
  .row input[type=text], .row input[type=number], .row input[type=email], .row select {
    width:100%; padding:.5rem .6rem; border:1px solid var(--line); border-radius:var(--radius-sm);
    font-size:.92rem; background:var(--card); font-family:var(--font-body); }
  .row .rm { border:0; background:none; color:var(--err); cursor:pointer; font-size:1.1rem; padding:.3rem; }
  .cell { min-width:0; }
  .celllabel { display:none; font-size:.72rem; color:var(--muted); margin-bottom:.15rem; }
  code { background:var(--accent-bg); border:1px solid var(--accent-border); border-radius:4px;
         padding:.05rem .3rem; font-size:.85em; color:var(--accent); }
  .colhead { display:grid; grid-template-columns:1fr 1fr 90px 34px; gap:.5rem; margin-bottom:.35rem; }
  .colhead.task-head { grid-template-columns:1fr 1fr 1fr 90px 34px; }
  .colhead span { color:var(--muted); font-size:.75rem; text-transform:uppercase; letter-spacing:.03em; }
  .addBtn { border:1px solid var(--line); background:var(--bg); border-radius:var(--radius-sm);
            padding:.4rem .8rem; font-size:.85rem; cursor:pointer; margin-top:.4rem;
            font-family:var(--font-body); transition:border-color .15s,color .15s; }
  .addBtn:hover { border-color:var(--accent); color:var(--accent); }
  .btn { padding:.65rem 1.2rem; }
  .err, .ok { margin:.85rem 0; }
  .chips { display:flex; flex-wrap:wrap; gap:.4rem; margin-top:.6rem; }
  .chip { border:1px dashed var(--accent-border); background:var(--accent-bg); border-radius:20px;
          padding:.3rem .7rem; font-size:.82rem; cursor:pointer; color:var(--accent);
          font-family:var(--font-body); transition:border-color .15s; }
  .chip:hover { border-color:var(--accent); }
  .field label { display:block; font-size:.85rem; color:var(--muted); margin:0 0 .3rem; }
  .field input, .field select { width:180px; padding:.5rem .6rem; border:1px solid var(--line);
    border-radius:var(--radius-sm); font-size:.92rem; background:var(--card);
    font-family:var(--font-body); }
  .twofield { display:flex; gap:1.5rem; flex-wrap:wrap; margin-bottom:.75rem; }
  /* Narrow windows: the column grid gets unusably tight, so stack each row into
     a card and lean on the placeholders instead of the column headers. */
  @media (max-width:620px) {
    .colhead, .colhead.task-head { display:none; }
    .celllabel { display:block; }
    .row, .row.task-row { grid-template-columns:1fr; gap:.4rem; border:1px solid var(--line);
      border-radius:10px; padding:.7rem; margin-bottom:.75rem; }
    .row .rm { justify-self:end; }
    .field input, .field select { width:100%; }
    .twofield { gap:.9rem; }
    .field { flex:1 1 100%; }
  }
</style>
</head>
<body>
<div class="wrap">
  <h1>Default tasks &amp; due dates</h1>
  <p class="sub"><a href="/">‹ Back to Projectify</a> — these rules apply to every project you create from now on.</p>

  <div id="membersNote" class="warn hide"></div>

  <div class="card">
    <h2>Kickoff tasks</h2>
    <p class="hint">Your own standard tasks, added to the top of every new project before the contract's deliverables.</p>

    <div class="twofield">
      <div class="field"><label>Auto-assign all kickoff tasks to</label><span id="kickoffAssigneeWrap"><input type="email" id="kickoffAssignee" placeholder="ops@example.com"></span></div>
    </div>
    <p class="hint">Used for any kickoff task you don't assign individually below. Leave it unassigned to decide per task.</p>

    <div class="colhead task-head"><span>Task name</span><span>Notes (optional)</span><span>Assign to</span><span>Due — days after signing</span><span></span></div>
    <div id="taskRows"></div>
    <button class="addBtn" id="addTask" type="button">+ Add task</button>
    <p class="hint" style="margin:.9rem 0 0;"><strong>Due</strong> is a number of days after the contract is signed — <code>0</code> means signing day, <code>3</code> means three days later. Leave it blank for no due date. <strong>Assign to</strong> overrides the auto-assign above for that one task.</p>
  </div>

  <div class="card">
    <h2>The contract's own tasks</h2>
    <p class="hint">Every deliverable in the signed contract becomes a task automatically. These rules decide <strong>who they go to</strong> and <strong>when they're due</strong>.</p>

    <h3 class="substep">Step 1 — Defaults for every task</h3>
    <div class="twofield">
      <div class="field"><label>Assign to</label><span id="defaultAssigneeWrap"><input type="email" id="defaultAssignee" placeholder="ops@example.com"></span></div>
      <div class="field"><label>Due this many days after signing</label><input type="number" id="defaultDueDays" value="30"></div>
      <div class="field"><label>Stagger tasks by</label><input type="number" id="cascadeDays" value="7"></div>
    </div>
    <p class="hint">With these settings, a section's first task is due 30 days after signing, the next 37, the next 44, and so on — so a long section doesn't dump everything on one day. Set the stagger to 0 to give every task the same due date.</p>

    <p class="hint" style="margin-top:1.2rem;">Need something different for one part of a
    particular contract? You don't set that up here — every contract's sections are different.
    Preview the contract on the main screen and adjust the assignees and dates there, on the
    actual sections it finds, before creating the project.</p>
  </div>

  <div id="error" class="err hide"></div>
  <div id="done" class="ok hide">Saved.</div>
  <button class="btn" id="saveBtn" type="button">Save</button>
</div>

<script>
(function () {
  var taskRows = document.getElementById('taskRows'),
      errorBox = document.getElementById('error'), done = document.getElementById('done'),
      saveBtn = document.getElementById('saveBtn'),
      USERS = [];

  function showErr(m){ errorBox.textContent = m; errorBox.classList.remove('hide'); }
  function clearErr(){ errorBox.classList.add('hide'); errorBox.textContent = ''; }
  function esc(s){ var d=document.createElement('div'); d.textContent=s==null?'':s; return d.innerHTML; }

  // Assignee field: a picker of real workspace members when we could load them
  // (values are user gids, which Asana always accepts), falling back to free-text
  // email entry if the list is unavailable. Typed emails still pass through, so
  // hand-written playbooks keep working.
  function assigneeFieldHtml(attrs, value){
    value = value || '';
    if (!USERS.length){
      return '<input type="email" '+attrs+' value="'+esc(value)+'" placeholder="optional">';
    }
    var opts = '<option value="">(unassigned)</option>'
      // Asana resolves "me" to whoever owns the connected token.
      + '<option value="me"'+(value === 'me' ? ' selected' : '')+'>Me (this Asana account)</option>';
    var matched = (value === 'me');
    USERS.forEach(function(u){
      var sel = (value && (value === u.gid || value === u.email)) ? ' selected' : '';
      if (sel) matched = true;
      opts += '<option value="'+esc(u.gid)+'"'+sel+'>'+esc(u.name || u.email || u.gid)+'</option>';
    });
    if (value && !matched){
      opts += '<option value="'+esc(value)+'" selected>'+esc(value)+' — not in this workspace</option>';
    }
    return '<select '+attrs+'>'+opts+'</select>';
  }

  // Each field is wrapped in a .cell carrying its own label. The label is hidden
  // while the column headers are visible, and shown once they collapse on narrow
  // windows — otherwise the stacked fields would be completely unlabelled.
  function cell(label, field){
    return '<div class="cell"><span class="celllabel">'+label+'</span>'+field+'</div>';
  }

  function taskRowHtml(t){
    t = t || {name:'', notes:'', assignee:'', days:''};
    return '<div class="row task-row">'
      + cell('Task name', '<input type="text" class="t-name" value="'+esc(t.name)+'" placeholder="e.g. Schedule kickoff call">')
      + cell('Notes (optional)', '<input type="text" class="t-notes" value="'+esc(t.notes)+'" placeholder="Extra detail for whoever does it">')
      + cell('Assign to', assigneeFieldHtml('class="t-assignee"', t.assignee))
      + cell('Due — days after signing', '<input type="number" class="t-days" value="'+esc(t.days)+'" placeholder="blank = none">')
      + '<button class="rm" type="button" title="Remove this task">×</button></div>';
  }

  function addTaskRow(t){
    var div = document.createElement('div'); div.innerHTML = taskRowHtml(t);
    var el = div.firstChild;
    el.querySelector('.rm').addEventListener('click', function(){ el.remove(); });
    taskRows.appendChild(el);
  }

  document.getElementById('addTask').addEventListener('click', function(){ addTaskRow(); });

  function collect(){
    var tasks = [];
    taskRows.querySelectorAll('.row').forEach(function(row){
      var name = row.querySelector('.t-name').value.trim();
      if (!name) return;
      var days = row.querySelector('.t-days').value;
      tasks.push({
        name: name,
        notes: row.querySelector('.t-notes').value.trim(),
        assignee: row.querySelector('.t-assignee').value.trim() || null,
        due: days === '' ? null : {anchor: 'signed', offset_days: parseInt(days, 10)}
      });
    });

    var defaultAssignee = document.getElementById('defaultAssignee').value.trim();
    var kickoffAssignee = document.getElementById('kickoffAssignee').value.trim();
    var defaultDueDays = document.getElementById('defaultDueDays').value;
    var cascadeDays = document.getElementById('cascadeDays').value;

    // by_section is intentionally empty from this wizard — per-contract exceptions
    // are made in the preview now. The engine still honours by_section if a
    // hand-written playbook.yaml sets it (the CLI and DocuSign poll have no UI).
    return {
      default_sections: tasks.length ? [{name: 'Kickoff & Onboarding', tasks: tasks}] : [],
      assignees: {default: defaultAssignee || null, kickoff: kickoffAssignee || null,
                  by_section: {}},
      due_dates: {
        default: defaultDueDays === '' ? null : {anchor: 'signed', offset_days: parseInt(defaultDueDays, 10)},
        cascade_days: cascadeDays === '' ? 0 : parseInt(cascadeDays, 10),
        by_section: {}
      }
    };
  }

  function load(){
    // Members must load BEFORE any row renders, so assignee fields can be
    // pickers rather than text boxes.
    fetch('/api/playbook/users')
      .then(function(r){ return r.json(); })
      .then(function(j){ USERS = j.users || []; noteMembers(j.reason); })
      .catch(function(){ USERS = []; noteMembers('lookup_failed'); })
      .then(function(){ return fetch('/api/playbook').then(function(r){ return r.json(); }); })
      .then(function(pb){ render(pb || {}); })
      .catch(function(){ render({}); });
  }

  // Without this the picker silently degrades to a text box, which just looks
  // like a broken dropdown.
  function noteMembers(reason){
    var note = document.getElementById('membersNote');
    if (!reason){ note.classList.add('hide'); return; }
    if (reason === 'not_connected'){
      note.innerHTML = 'Asana isn\\'t connected yet, so you\\'ll need to type assignee email '
        + 'addresses by hand. <a href="/setup">Connect Asana</a> to pick people from a list instead.';
    } else if (reason === 'no_visible_members'){
      note.innerHTML = 'None of your Asana workspace members have profiles visible to this '
        + 'token, so assignee fields are plain text — type full email addresses.';
    } else {
      note.innerHTML = 'Couldn\\'t load your Asana workspace members, so assignee fields are '
        + 'plain text — type full email addresses. Everything else here works normally.';
    }
    note.classList.remove('hide');
  }

  function render(pb){
    var seeded = false;
    (pb.default_sections || []).forEach(function(ds){
      (ds.tasks || []).forEach(function(t){
        addTaskRow({name: t.name, notes: t.notes || '', assignee: t.assignee || '',
          days: t.due ? t.due.offset_days : ''});
        seeded = true;
      });
    });
    if (!seeded){
      // First run: seed the one required default task (see playbook.example.yaml).
      addTaskRow({name: 'Verify contract / project details',
        notes: 'Confirm the parsed sections/tasks match the signed contract before work begins.',
        assignee: '', days: 1});
    }
    var assignees = pb.assignees || {};
    var due = pb.due_dates || {};
    if (USERS.length){
      document.getElementById('defaultAssigneeWrap').innerHTML =
        assigneeFieldHtml('id="defaultAssignee"', assignees.default || '');
      document.getElementById('kickoffAssigneeWrap').innerHTML =
        assigneeFieldHtml('id="kickoffAssignee"', assignees.kickoff || '');
    } else {
      document.getElementById('defaultAssignee').value = assignees.default || '';
      document.getElementById('kickoffAssignee').value = assignees.kickoff || '';
    }
    document.getElementById('defaultDueDays').value = due.default ? due.default.offset_days : 30;
    document.getElementById('cascadeDays').value = due.cascade_days != null ? due.cascade_days : 7;
  }

  saveBtn.addEventListener('click', function(){
    clearErr(); done.classList.add('hide');
    saveBtn.disabled = true; saveBtn.textContent = 'Saving…';
    fetch('/api/playbook/save', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(collect())})
      .then(function(r){ return r.json().then(function(j){ return {ok:r.ok, j:j}; }); })
      .then(function(res){
        saveBtn.disabled = false; saveBtn.textContent = 'Save';
        if (!res.ok || res.j.error){ showErr(res.j.error || 'Could not save.'); return; }
        done.classList.remove('hide');
      })
      .catch(function(){ saveBtn.disabled = false; saveBtn.textContent = 'Save';
        showErr('Could not reach the server.'); });
  });

  load();
})();
</script>
</body>
</html>"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"Projectify running → http://127.0.0.1:{port}")
    create_app().run(host="127.0.0.1", port=port)
