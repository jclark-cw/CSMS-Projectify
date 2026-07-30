#!/usr/bin/env python3
"""Offline tests for the Phase-2 Asana orchestration.

No network, no credentials: a fake transport returns canned gids so we can assert
create_project issues the right calls, and a fake client exercises the engine's
live path. Real Asana calls are only reachable with a PAT + workspace gid.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from csms.asana_client import (AsanaClient, AsanaError,  # noqa: E402
                                list_workspaces, list_teams, list_users)
from csms.engine import build_project, BuildPlan, SectionPlan, TaskPlan  # noqa: E402

SAMPLE = REPO_ROOT / "samples" / "sample_acme_grouped.pdf"


class FakeTransport:
    """Records calls and returns canned gids per endpoint.

    `existing` seeds the project-name lookup (the GET) so idempotency can be tested.
    """

    def __init__(self, existing=None):
        self.calls = []
        self.existing = existing or []
        self._n = 0

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, body))
        assert headers["Authorization"].startswith("Bearer ")
        if method == "GET":
            return 200, {"data": self.existing}  # project-name lookup
        self._n += 1
        if url.endswith("/projects"):
            return 200, {"data": {"gid": "P1"}}
        if url.endswith("/sections"):
            return 200, {"data": {"gid": f"S{self._n}"}}
        if url.endswith("/tasks"):
            return 200, {"data": {"gid": f"T{self._n}"}}
        return 200, {"data": {}}


def _plan():
    return BuildPlan(source="x.pdf", sections=[
        SectionPlan(name="Speaking", group="Benefits", tasks=[
            TaskPlan(name="Keynote", notes="approve topic"),
            TaskPlan(name="Video file")]),
        SectionPlan(name="Booth", group="Benefits", tasks=[
            TaskPlan(name="10x10 space")]),
    ])


def test_create_project_orchestration():
    t = FakeTransport()
    client = AsanaClient("tok", "WS", team_gid="TEAM", transport=t)
    out = client.create_project(_plan(), "Acme project")

    assert out["project_gid"] == "P1"
    assert out["project_url"] == "https://app.asana.com/0/P1"
    assert out["created"] == {"sections": 2, "tasks": 3}

    # 1 project + 2 sections + 3 tasks
    posts = [c for c in t.calls if c[0] == "POST"]
    assert len(posts) == 6
    # project carries workspace + team
    proj = posts[0][2]["data"]
    assert proj["name"] == "Acme project" and proj["workspace"] == "WS" and proj["team"] == "TEAM"
    # a task references its section via memberships, and carries notes
    task_bodies = [c[2]["data"] for c in t.calls if c[1].endswith("/tasks")]
    assert task_bodies[0]["projects"] == ["P1"]  # anchor required by Asana
    assert task_bodies[0]["memberships"][0]["project"] == "P1"
    assert task_bodies[0]["notes"] == "approve topic"


def test_idempotent_skip_when_project_exists():
    t = FakeTransport(existing=[{"name": "Acme project", "gid": "EXIST"}])
    client = AsanaClient("tok", "WS", team_gid="TEAM", transport=t)
    out = client.create_project(_plan(), "Acme project")
    assert out["existed"] is True
    assert out["project_gid"] == "EXIST"
    assert out["created"] == {"sections": 0, "tasks": 0}
    assert not any(c[0] == "POST" for c in t.calls)  # nothing was created


def test_force_creates_despite_existing():
    t = FakeTransport(existing=[{"name": "Acme project", "gid": "EXIST"}])
    client = AsanaClient("tok", "WS", team_gid="TEAM", transport=t)
    out = client.create_project(_plan(), "Acme project", on_exists="force")
    assert out["existed"] is False
    assert out["project_gid"] == "P1"
    assert any(c[0] == "POST" and c[1].endswith("/projects") for c in t.calls)


def test_http_error_raises_asana_error():
    def boom(method, url, headers, body):
        return 401, {"errors": [{"message": "Not Authorized"}]}
    client = AsanaClient("tok", "WS", transport=boom)
    try:
        client.create_project(_plan(), "x")
        assert False, "expected AsanaError on 401"
    except AsanaError:
        pass


def test_rate_limit_retries_then_succeeds(monkeypatch=None):
    import csms.asana_client as mod
    calls = {"n": 0}

    def flaky(method, url, headers, body):
        calls["n"] += 1
        if calls["n"] == 1:
            return 429, {}
        return 200, {"data": {"gid": "P1"}}

    # don't actually sleep during the test
    orig_sleep = mod.time.sleep
    mod.time.sleep = lambda *_: None
    try:
        client = AsanaClient("tok", "WS", transport=flaky)
        gid = client._post("/projects", {"name": "x"})
        assert gid["gid"] == "P1" and calls["n"] == 2
    finally:
        mod.time.sleep = orig_sleep


def test_network_error_retries_then_succeeds():
    import csms.asana_client as mod
    calls = {"n": 0}

    def flaky(method, url, headers, body):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionResetError("[Errno 54] Connection reset by peer")
        return 200, {"data": {"gid": "P1"}}

    orig_sleep = mod.time.sleep
    mod.time.sleep = lambda *_: None
    try:
        client = AsanaClient("tok", "WS", transport=flaky)
        gid = client._post("/projects", {"name": "x"})
        assert gid["gid"] == "P1" and calls["n"] == 2
    finally:
        mod.time.sleep = orig_sleep


def test_network_error_raises_asana_error_after_retries_exhausted():
    import csms.asana_client as mod

    def always_reset(method, url, headers, body):
        raise ConnectionResetError("[Errno 54] Connection reset by peer")

    orig_sleep = mod.time.sleep
    mod.time.sleep = lambda *_: None
    try:
        client = AsanaClient("tok", "WS", transport=always_reset, max_retries=2)
        try:
            client._post("/projects", {"name": "x"})
            assert False, "expected AsanaError after retries exhausted"
        except AsanaError:
            pass
    finally:
        mod.time.sleep = orig_sleep


def test_list_workspaces_returns_data():
    def fake(method, url, headers, body):
        assert method == "GET" and "/workspaces" in url
        assert headers["Authorization"] == "Bearer tok"
        return 200, {"data": [{"gid": "WS1", "name": "Acme"}]}
    out = list_workspaces("tok", transport=fake)
    assert out == [{"gid": "WS1", "name": "Acme"}]


def test_list_workspaces_bad_token_raises():
    def fake(method, url, headers, body):
        return 401, {"errors": [{"message": "Not Authorized"}]}
    try:
        list_workspaces("badtok", transport=fake)
        assert False, "expected AsanaError on 401"
    except AsanaError:
        pass


def test_list_teams_returns_data():
    def fake(method, url, headers, body):
        assert "/organizations/WS1/teams" in url
        return 200, {"data": [{"gid": "T1", "name": "Core Team"}]}
    out = list_teams("tok", "WS1", transport=fake)
    assert out == [{"gid": "T1", "name": "Core Team"}]


def test_list_teams_swallows_error_to_empty_list():
    # A plain (non-organization) workspace 400s on /organizations/.../teams —
    # that's normal, not fatal, since team is optional everywhere it's used.
    def fake(method, url, headers, body):
        return 400, {"errors": [{"message": "not an organization"}]}
    assert list_teams("tok", "WS1", transport=fake) == []


def test_list_users_returns_data():
    def fake(method, url, headers, body):
        assert "/users?workspace=WS1" in url and "opt_fields=name,email" in url
        return 200, {"data": [{"gid": "U1", "name": "Dana", "email": "dana@x.com"}]}
    out = list_users("tok", "WS1", transport=fake)
    assert out == [{"gid": "U1", "name": "Dana", "email": "dana@x.com"}]


def test_list_users_swallows_error_to_empty_list():
    # The wizard degrades to free-text entry rather than blocking on this.
    def fake(method, url, headers, body):
        return 403, {"errors": [{"message": "nope"}]}
    assert list_users("tok", "WS1", transport=fake) == []


class FakeAsana:
    def __init__(self):
        self.plan = None

    def create_project(self, plan, name, on_exists="skip"):
        self.plan = plan
        return {"project_gid": "P9",
                "project_url": "https://app.asana.com/0/P9",
                "created": {"sections": len(plan.sections),
                            "tasks": sum(len(s.tasks) for s in plan.sections)},
                "existed": False,
                "warnings": []}


def test_engine_live_path_with_injected_client():
    if not SAMPLE.exists():
        return  # sample fixtures generated by tools/make_sample_contracts.py
    fake = FakeAsana()
    result = build_project(str(SAMPLE), dry_run=False, asana=fake)
    assert result.dry_run is False
    assert result.project_gid == "P9"
    assert result.created["sections"] == result.plan.section_count
    assert fake.plan is result.plan


def test_from_config_missing_creds_raises():
    import csms.config as cfg
    # ensure no token in env so from_config fails clearly
    cfg._ENV_LOADED = True  # skip .env load
    import os
    saved = os.environ.pop("ASANA_PAT", None)
    try:
        try:
            AsanaClient.from_config()
            assert False, "expected RuntimeError without ASANA_PAT"
        except RuntimeError:
            pass
    finally:
        if saved is not None:
            os.environ["ASANA_PAT"] = saved
        cfg._ENV_LOADED = False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS  {name}")
    print("asana orchestration OK")
