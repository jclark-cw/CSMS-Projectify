#!/usr/bin/env python3
"""Tests for the Projectify web UI / API (csms.webapp).

Runs under pytest or standalone. Skips cleanly if Flask isn't installed or the
contract PDF is absent.
"""

import io
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

CONTRACT_PDF = REPO_ROOT / "CW Contracts" / \
    "CMC26_+_Partnership_-_Content_Workshop_-_1-11-2026.pdf"
_HAVE_PDF = CONTRACT_PDF.exists()

try:
    import flask  # noqa: F401
    _HAVE_FLASK = True
except ImportError:
    _HAVE_FLASK = False

try:
    import pytest
    _skip_no_pdf = pytest.mark.skipif(not _HAVE_PDF, reason="contract PDF not present")
    pytestmark = pytest.mark.skipif(not _HAVE_FLASK, reason="Flask not installed")
except ImportError:
    def _skip_no_pdf(fn):
        return fn


def _client():
    from csms.webapp import create_app
    return create_app().test_client()


class FakeKeyringBackend:
    """In-memory keyring stand-in — see tests/test_credentials.py for the pattern."""

    def __init__(self):
        self._data = {}

    def get_password(self, service, key):
        return self._data.get((service, key))

    def set_password(self, service, key, value):
        self._data[(service, key)] = value

    def delete_password(self, service, key):
        del self._data[(service, key)]


def _desktop_app(tmp_playbook_path=None):
    """A desktop=True app with its CredentialStore backed by an in-memory fake —
    no real OS keychain, no `keyring` package needed to run these tests. Optionally
    redirects the playbook to a throwaway path so tests never touch the real
    per-user app-data playbook.json."""
    from csms.webapp import create_app
    from csms.credentials import CredentialStore
    app = create_app(desktop=True)
    app.config["CRED_STORE"] = CredentialStore(backend=FakeKeyringBackend())
    if tmp_playbook_path is not None:
        app.config["PLAYBOOK_PATH"] = tmp_playbook_path
    return app


def test_homepage():
    r = _client().get("/")
    assert r.status_code == 200 and b"Projectify" in r.data


def test_rejects_non_pdf():
    r = _client().post(
        "/preview", data={"contract": (io.BytesIO(b"nope"), "x.pdf")},
        content_type="multipart/form-data")
    assert r.status_code == 400 and b"not a PDF" in r.data


def test_no_file_is_400():
    r = _client().post("/preview", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


@_skip_no_pdf
def test_preview_renders_plan():
    with open(CONTRACT_PDF, "rb") as f:
        r = _client().post(
            "/preview", data={"contract": (f, "c.pdf")},
            content_type="multipart/form-data")
    assert r.status_code == 200
    assert b"Annual Extras" in r.data and b"submitted annually" in r.data


def test_api_build_no_file_is_400():
    r = _client().post("/api/build", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_api_build_rejects_non_pdf():
    # Validation happens before any Asana call, so this never touches the live board.
    r = _client().post(
        "/api/build", data={"contract": (io.BytesIO(b"nope"), "x.pdf")},
        content_type="multipart/form-data")
    assert r.status_code == 400


@_skip_no_pdf
def test_api_preview_returns_json():
    with open(CONTRACT_PDF, "rb") as f:
        r = _client().post(
            "/api/preview", data={"contract": (f, "c.pdf")},
            content_type="multipart/form-data")
    d = r.get_json()
    assert r.status_code == 200 and d["section_count"] == 12
    assert d["task_count"] == sum(len(s["tasks"]) for s in d["sections"])


def _hide_works_on(page_html):
    """`.hide` must actually hide. It only does if `.hide{display:none}` is present
    AND the banner classes it's combined with (.ok/.err/.panel/.warn/.step) don't
    set `display` themselves — otherwise they'd tie on specificity and win by order."""
    import re
    if ".hide { display:none; }" not in page_html:
        return False
    for cls in (".ok", ".err", ".panel", ".warn", ".step", ".card"):
        for body in re.findall(re.escape(cls) + r"\s*\{([^}]*)\}", page_html):
            if "display:" in body:
                return False
    return True


def test_hide_class_actually_hides_on_every_page():
    # Regression: the "Connected — redirecting…" banner rendered on load because the
    # SETUP page's duplicated CSS had lost its hide rule. Shared BASE_CSS now makes
    # drift impossible, but assert the behaviour on all three pages regardless.
    app = _desktop_app()
    app.config["CRED_STORE"].set_pat("tok")          # else / redirects to /setup
    app.config["CRED_STORE"].set_workspace_gid("WS1")
    client = app.test_client()
    for path in ("/", "/setup", "/playbook"):
        html = client.get(path).data.decode("utf-8")
        assert _hide_works_on(html), f"{path} would render .hide elements visible"


def test_auth_failure_is_plain_english_with_no_partial_project_warning():
    # A failed pre-flight GET cannot have written anything, so warning about a
    # stuck partial project would send the operator hunting for nothing.
    import csms.webapp as webapp_mod
    from csms.asana_client import AsanaError

    def boom(file, **kwargs):
        raise AsanaError("Asana GET /projects?workspace=WS -> 401: Not Authorized",
                         status=401, method="GET", path="/projects")

    app = _desktop_app()
    app.config["CRED_STORE"].set_pat("tok")
    app.config["CRED_STORE"].set_workspace_gid("WS1")
    orig = webapp_mod._build_from_upload
    webapp_mod._build_from_upload = boom
    try:
        r = app.test_client().post(
            "/api/build",
            data={"contract": (io.BytesIO(b"%PDF-1.4 fake"), "c.pdf"), "name": "P"},
            content_type="multipart/form-data")
    finally:
        webapp_mod._build_from_upload = orig

    body = r.get_json()
    assert r.status_code == 502
    assert "partially created" not in body["error"]
    assert "revoked or expired" in body["error"]
    assert body["needs_reconnect"] is True
    assert "401" not in body["error"]  # no raw API jargon


def test_write_failure_does_warn_about_partial_project():
    import csms.webapp as webapp_mod
    from csms.asana_client import AsanaError

    def boom(file, **kwargs):
        raise AsanaError("Asana POST /tasks -> 500: boom",
                         status=500, method="POST", path="/tasks")

    app = _desktop_app()
    app.config["CRED_STORE"].set_pat("tok")
    app.config["CRED_STORE"].set_workspace_gid("WS1")
    orig = webapp_mod._build_from_upload
    webapp_mod._build_from_upload = boom
    try:
        r = app.test_client().post(
            "/api/build",
            data={"contract": (io.BytesIO(b"%PDF-1.4 fake"), "c.pdf"), "name": "P"},
            content_type="multipart/form-data")
    finally:
        webapp_mod._build_from_upload = orig

    assert "partially created" in r.get_json()["error"]
    assert r.get_json()["needs_reconnect"] is False


def test_playbook_users_empty_without_credentials():
    r = _desktop_app().test_client().get("/api/playbook/users")
    assert r.status_code == 200 and r.get_json()["users"] == []
    # The UI needs to know WHY, or the text-box fallback looks like a broken dropdown.
    assert r.get_json()["reason"] == "not_connected"


def test_api_build_uses_edited_plan_verbatim():
    # The whole point of an editable preview: what's on screen is what gets built.
    # If the server re-parsed the PDF here, every edit would be silently discarded.
    import csms.webapp as webapp_mod

    captured = {}

    class RecordingAsana:
        def create_project(self, plan, name, on_exists="skip"):
            captured["plan"] = plan
            captured["name"] = name
            return {"project_gid": "P1", "project_url": "u",
                    "created": {"sections": 1, "tasks": 1}, "existed": False,
                    "warnings": []}

    app = _desktop_app()
    app.config["CRED_STORE"].set_pat("tok")
    app.config["CRED_STORE"].set_workspace_gid("WS1")
    app.config["CRED_STORE"].build_client = lambda: RecordingAsana()

    edited = {
        "source": "c.pdf",
        "sections": [{"group": "", "section": "Booth", "tasks": [
            {"name": "10x10 booth", "notes": "n",
             "assignee": "1234", "due_on": "2026-03-01"}]}],
    }
    r = app.test_client().post(
        "/api/build",
        data={"plan": json.dumps(edited), "name": "Edited Project"},
        content_type="multipart/form-data")

    assert r.status_code == 200
    plan = captured["plan"]
    assert captured["name"] == "Edited Project"
    assert plan.sections[0].name == "Booth"
    task = plan.sections[0].tasks[0]
    assert task.assignee == "1234"     # the edit survived
    assert task.due_on == "2026-03-01"


def test_api_build_rejects_empty_edited_plan():
    app = _desktop_app()
    app.config["CRED_STORE"].set_pat("tok")
    app.config["CRED_STORE"].set_workspace_gid("WS1")
    r = app.test_client().post(
        "/api/build",
        data={"plan": json.dumps({"sections": []}), "name": "x"},
        content_type="multipart/form-data")
    assert r.status_code == 400 and "empty" in r.get_json()["error"].lower()


def test_api_build_rejects_malformed_plan_json():
    app = _desktop_app()
    app.config["CRED_STORE"].set_pat("tok")
    app.config["CRED_STORE"].set_workspace_gid("WS1")
    r = app.test_client().post(
        "/api/build", data={"plan": "{not json", "name": "x"},
        content_type="multipart/form-data")
    assert r.status_code == 400


@_skip_no_pdf
def test_preview_includes_assignees_and_due_dates_to_edit():
    # Preview must apply the playbook, or there'd be nothing to adjust on screen.
    with tempfile.TemporaryDirectory() as d:
        pb_path = Path(d) / "playbook.json"
        pb_path.write_text(json.dumps({
            "default_sections": [],
            "assignees": {"default": "ops@x.com", "kickoff": None, "by_section": {}},
            "due_dates": {"default": {"anchor": "signed", "offset_days": 10},
                          "cascade_days": 0, "by_section": {}},
        }))
        app = _desktop_app(tmp_playbook_path=pb_path)
        with open(CONTRACT_PDF, "rb") as f:
            r = app.test_client().post(
                "/api/preview",
                data={"contract": (f, "c.pdf"), "signed_date": "2026-01-15"},
                content_type="multipart/form-data")
    d = r.get_json()
    first = d["sections"][0]["tasks"][0]
    assert first["assignee"] == "ops@x.com"
    assert first["due_on"] == "2026-01-25"   # signed + 10


def test_playbook_users_drops_private_users():
    # Asana names hidden-profile members "Private User"; several are
    # indistinguishable in a dropdown, so they aren't offerable assignees.
    import csms.webapp as webapp_mod

    roster = [
        {"gid": "1", "name": "Gianna Whitver", "email": "g@x.com"},
        {"gid": "2", "name": "Private User", "email": None},
        {"gid": "3", "name": "private user", "email": None},   # match case-insensitively
        {"gid": "4", "name": "Dave Algava", "email": "d@x.com"},
    ]
    orig = webapp_mod.list_users
    webapp_mod.list_users = lambda token, workspace_gid, transport=None: roster
    try:
        app = _desktop_app()
        app.config["CRED_STORE"].set_pat("tok")
        app.config["CRED_STORE"].set_workspace_gid("WS1")
        body = app.test_client().get("/api/playbook/users").get_json()
    finally:
        webapp_mod.list_users = orig

    assert [u["gid"] for u in body["users"]] == ["1", "4"]
    assert body["reason"] is None


def test_playbook_users_all_private_still_explains_itself():
    # Filtering to nothing must not silently degrade to text boxes.
    import csms.webapp as webapp_mod

    orig = webapp_mod.list_users
    webapp_mod.list_users = lambda token, workspace_gid, transport=None: [
        {"gid": "2", "name": "Private User", "email": None}]
    try:
        app = _desktop_app()
        app.config["CRED_STORE"].set_pat("tok")
        app.config["CRED_STORE"].set_workspace_gid("WS1")
        body = app.test_client().get("/api/playbook/users").get_json()
    finally:
        webapp_mod.list_users = orig

    assert body["users"] == []
    assert body["reason"] == "no_visible_members"


def test_playbook_users_reports_lookup_failure():
    import csms.webapp as webapp_mod

    orig = webapp_mod.list_users
    webapp_mod.list_users = lambda token, workspace_gid, transport=None: []
    try:
        app = _desktop_app()
        app.config["CRED_STORE"].set_pat("tok")
        app.config["CRED_STORE"].set_workspace_gid("WS1")
        r = app.test_client().get("/api/playbook/users")
        assert r.get_json()["reason"] == "lookup_failed"
    finally:
        webapp_mod.list_users = orig


def test_playbook_users_returns_workspace_members():
    import csms.webapp as webapp_mod

    def fake_list_users(token, workspace_gid, transport=None):
        assert token == "tok" and workspace_gid == "WS1"
        return [{"gid": "U1", "name": "Dana", "email": "dana@x.com"}]

    orig = webapp_mod.list_users
    webapp_mod.list_users = fake_list_users
    try:
        app = _desktop_app()
        app.config["CRED_STORE"].set_pat("tok")
        app.config["CRED_STORE"].set_workspace_gid("WS1")
        r = app.test_client().get("/api/playbook/users")
        assert r.status_code == 200
        assert r.get_json()["users"] == [{"gid": "U1", "name": "Dana", "email": "dana@x.com"}]
    finally:
        webapp_mod.list_users = orig


def test_playbook_fields_are_labelled_in_both_layouts():
    # The narrow-width media query hides the column headers, so each field also
    # carries its own label that appears exactly when the headers disappear.
    body = _desktop_app().test_client().get("/playbook").data.decode("utf-8")
    assert ".celllabel { display:none;" in body      # hidden while headers show
    assert ".celllabel { display:block; }" in body   # shown once headers collapse
    assert "Due — days after signing" in body        # the previously bare number box
    assert 'id="kickoffAssignee"' in body            # kickoff auto-assign field


def test_placeholders_are_light_gray_on_every_page():
    app = _desktop_app()
    app.config["CRED_STORE"].set_pat("tok")
    app.config["CRED_STORE"].set_workspace_gid("WS1")
    client = app.test_client()
    for path in ("/", "/setup", "/playbook"):
        html = client.get(path).data.decode("utf-8")
        assert "::placeholder { color:var(--placeholder); opacity:1; }" in html, path
        assert "--placeholder:#9a99a6;" in html, path


def test_upload_box_is_not_inline():
    # Regression: .drop is a <label> (display:inline by default) containing block
    # children, which fragments the dashed border and breaks padding.
    r = _client().get("/")
    assert b".drop { display:flex;" in r.data


def test_no_native_confirm_dialogs():
    # Regression: native confirm() is suppressed/unimplemented in some webview
    # hosts, where it returns false and Create-in-Asana silently does nothing.
    # Ignore // comment lines — the code deliberately explains why it avoids confirm().
    body = _client().get("/").data.decode("utf-8")
    code = "\n".join(line for line in body.splitlines()
                     if not line.strip().startswith("//"))
    assert "confirm(" not in code
    assert "alert(" not in code


def test_setup_wizard_full_flow():
    import csms.webapp as webapp_mod

    def fake_list_workspaces(token, transport=None):
        assert token == "tok123"
        return [{"gid": "WS1", "name": "Acme"}]

    def fake_list_teams(token, workspace_gid, transport=None):
        assert workspace_gid == "WS1"
        return [{"gid": "T1", "name": "Core"}]

    orig_lw, orig_lt = webapp_mod.list_workspaces, webapp_mod.list_teams
    webapp_mod.list_workspaces = fake_list_workspaces
    webapp_mod.list_teams = fake_list_teams
    try:
        app = _desktop_app()
        client = app.test_client()

        # No creds yet -> index redirects to the wizard
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 302 and "/setup" in r.headers["Location"]

        r = client.post("/api/setup/workspaces", json={"token": "tok123"})
        assert r.status_code == 200
        assert r.get_json()["workspaces"] == [{"gid": "WS1", "name": "Acme"}]

        r = client.post("/api/setup/teams",
                        json={"token": "tok123", "workspace_gid": "WS1"})
        assert r.status_code == 200
        assert r.get_json()["teams"] == [{"gid": "T1", "name": "Core"}]

        r = client.post("/api/setup/save",
                        json={"token": "tok123", "workspace_gid": "WS1", "team_gid": "T1"})
        assert r.status_code == 200 and r.get_json()["ok"] is True
        assert app.config["CRED_STORE"].has_credentials() is True

        r = client.get("/", follow_redirects=False)  # setup complete -> no more redirect
        assert r.status_code == 200

        client.post("/api/setup/clear")
        assert app.config["CRED_STORE"].has_credentials() is False
    finally:
        webapp_mod.list_workspaces = orig_lw
        webapp_mod.list_teams = orig_lt


def test_setup_workspaces_bad_token_returns_400():
    import csms.webapp as webapp_mod
    from csms.asana_client import AsanaError

    def fake_list_workspaces(token, transport=None):
        raise AsanaError("bad token")

    orig = webapp_mod.list_workspaces
    webapp_mod.list_workspaces = fake_list_workspaces
    try:
        r = _desktop_app().test_client().post("/api/setup/workspaces", json={"token": "bad"})
        assert r.status_code == 400 and "error" in r.get_json()
    finally:
        webapp_mod.list_workspaces = orig


def test_setup_workspaces_missing_token_is_400():
    r = _desktop_app().test_client().post("/api/setup/workspaces", json={})
    assert r.status_code == 400


def test_api_build_desktop_without_creds_is_400():
    r = _desktop_app().test_client().post(
        "/api/build", data={"contract": (io.BytesIO(b"nope"), "x.pdf")},
        content_type="multipart/form-data")
    assert r.status_code == 400


def test_playbook_get_defaults_to_empty():
    with tempfile.TemporaryDirectory() as d:
        app = _desktop_app(tmp_playbook_path=Path(d) / "playbook.json")
        r = app.test_client().get("/api/playbook")
        assert r.status_code == 200 and r.get_json() == {}


def test_playbook_save_then_get_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        app = _desktop_app(tmp_playbook_path=Path(d) / "playbook.json")
        client = app.test_client()
        pb = {"default_sections": [{"name": "Kickoff", "tasks": [{"name": "Say hi"}]}],
              "assignees": {"default": "ops@example.com", "by_section": {}},
              "due_dates": {"default": {"anchor": "signed", "offset_days": 30},
                            "cascade_days": 7, "by_section": {}}}
        r = client.post("/api/playbook/save", json=pb)
        assert r.status_code == 200 and r.get_json()["ok"] is True
        r = client.get("/api/playbook")
        assert r.get_json() == pb


def test_playbook_save_rejects_malformed_shape():
    with tempfile.TemporaryDirectory() as d:
        app = _desktop_app(tmp_playbook_path=Path(d) / "playbook.json")
        r = app.test_client().post("/api/playbook/save", json={"default_sections": "nope"})
        assert r.status_code == 400


@_skip_no_pdf
def test_playbook_preview_sections_returns_real_names():
    with tempfile.TemporaryDirectory() as d:
        app = _desktop_app(tmp_playbook_path=Path(d) / "playbook.json")
        with open(CONTRACT_PDF, "rb") as f:
            r = app.test_client().post(
                "/api/playbook/preview-sections",
                data={"contract": (f, "c.pdf")}, content_type="multipart/form-data")
        assert r.status_code == 200
        assert "Annual Extras" in r.get_json()["sections"]


def test_api_build_desktop_applies_saved_playbook():
    import csms.webapp as webapp_mod

    class FakeResult:
        existed = False
        project_url = "https://app.asana.com/0/FAKE"
        created = {"sections": 1, "tasks": 1}
        warnings = []

    captured = {}

    def fake_build_from_upload(file, **kwargs):
        captured.update(kwargs)
        return FakeResult()

    with tempfile.TemporaryDirectory() as d:
        pb_path = Path(d) / "playbook.json"
        pb = {"default_sections": [{"name": "Kickoff", "tasks": [{"name": "t1"}]}],
              "assignees": {"default": "ops@example.com", "by_section": {}},
              "due_dates": {"default": None, "cascade_days": 0, "by_section": {}}}
        pb_path.write_text(json.dumps(pb))

        app = _desktop_app(tmp_playbook_path=pb_path)
        app.config["CRED_STORE"].set_pat("tok")
        app.config["CRED_STORE"].set_workspace_gid("WS1")

        orig = webapp_mod._build_from_upload
        webapp_mod._build_from_upload = fake_build_from_upload
        try:
            r = app.test_client().post(
                "/api/build",
                data={"contract": (io.BytesIO(b"%PDF-1.4 fake"), "c.pdf"),
                      "name": "Test Project", "signed_date": "2026-01-15"},
                content_type="multipart/form-data")
        finally:
            webapp_mod._build_from_upload = orig

        assert r.status_code == 200
        assert captured["playbook"] == pb
        assert captured["signed_date"] == "2026-01-15"
        assert captured["asana"] is not None


def test_cross_origin_post_is_refused():
    """A hostile page in the operator's browser must not be able to drive the app.

    The local server has no auth by design, so this header check is the only thing
    standing between a malicious tab and /api/setup/save overwriting the stored
    Asana token.
    """
    c = _client()
    for path in ("/api/setup/save", "/api/build", "/api/playbook/save",
                 "/api/setup/clear"):
        r = c.post(path, headers={"Origin": "https://evil.example"})
        assert r.status_code == 403, f"{path} accepted a cross-origin POST"
        assert b"cross-origin" in r.data


def test_sandboxed_null_origin_is_refused():
    """Origin: null (sandboxed iframe, file://) is hostile, not "absent"."""
    r = _client().post("/api/build", headers={"Origin": "null"})
    assert r.status_code == 403


def test_dns_rebinding_host_is_refused():
    """A rebound domain reaches loopback carrying its own Host header."""
    r = _client().get("/", headers={"Host": "evil.example"})
    assert r.status_code == 403
    assert b"Host" in r.data


def test_same_origin_requests_still_work():
    """The guard must not break the app it protects."""
    c = _client()
    assert c.get("/", headers={"Host": "127.0.0.1:8000"}).status_code == 200
    # Same-origin POSTs do send Origin; that path has to stay open.
    r = c.post("/api/build",
               headers={"Origin": "http://127.0.0.1:8000", "Host": "127.0.0.1:8000"})
    assert r.status_code != 403


def test_ipv6_loopback_origin_is_allowed():
    """[::1]:port must not be mangled into a non-loopback host by port stripping."""
    r = _client().get("/", headers={"Host": "[::1]:8000"})
    assert r.status_code == 200


def test_allowed_hosts_opt_in_for_real_hosting():
    from csms.webapp import create_app
    c = create_app(allowed_hosts={"127.0.0.1", "projectify.internal"}).test_client()
    assert c.get("/", headers={"Host": "projectify.internal"}).status_code == 200
    assert c.get("/", headers={"Host": "evil.example"}).status_code == 403


def _run_standalone():
    if not _HAVE_FLASK:
        print("SKIP: Flask not installed")
        return 0
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        if not _HAVE_PDF and t.__name__ in (
                "test_preview_renders_plan", "test_api_preview_returns_json"):
            print(f"SKIP  {t.__name__} (no PDF)")
            continue
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
