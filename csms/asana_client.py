#!/usr/bin/env python3
"""csms.asana_client — create an Asana project (blank) + sections + tasks from a plan.

Phase 2. Stdlib-only HTTP (urllib, TLS verified by default) — no new dependencies,
portable. The transport is injectable so the orchestration is fully unit-testable
offline; real calls need an Asana PAT + workspace (+ optional team) gid.

Mapping: BuildPlan → one blank project, one Section per plan section, one Task per
plan task (notes carried into the task's notes field).

TODO (idempotency): a re-run currently creates a fresh project. Phase 2.1 should
key on the project name so re-processing the same contract updates rather than
duplicates — the structural fix for the old "duplicate first task" bug.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.request
import urllib.error

API_BASE = "https://app.asana.com/api/1.0"


class AsanaError(RuntimeError):
    """Any Asana API / configuration failure.

    Carries the failing call so callers can tell an expired token from a real
    outage, and — importantly — whether a write could have happened at all.
    """

    def __init__(self, message, *, status=None, method=None, path=None):
        super().__init__(message)
        self.status = status
        self.method = method
        self.path = path

    @property
    def is_auth_error(self) -> bool:
        return self.status in (401, 403)

    @property
    def may_have_written(self) -> bool:
        """True only if the failing call was a write. A failed GET (e.g. the
        pre-flight name lookup) cannot have left a partial project behind, so
        callers must not warn about one."""
        return self.method is not None and self.method != "GET"


def _urllib_transport(method: str, url: str, headers: dict, body):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # TLS verified by default
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            payload = {}
        return e.code, payload


def list_workspaces(token: str, *, transport=None) -> list:
    """Return [{gid, name}] workspaces visible to this token.

    Used by the desktop app's first-run setup wizard, before a workspace_gid is
    known — AsanaClient itself requires one at construction, so this is a bare
    module-level probe. Raises AsanaError on an invalid/expired token.
    """
    transport = transport or _urllib_transport
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    status, payload = transport("GET", API_BASE + "/workspaces?opt_fields=name", headers, None)
    if status >= 400:
        raise AsanaError(f"Asana GET /workspaces -> {status}: {payload}")
    return payload.get("data", payload)


def list_teams(token: str, workspace_gid: str, *, transport=None) -> list:
    """Return [{gid, name}] teams in a workspace, or [] if the workspace has none.

    Plain (non-organization) Asana workspaces don't support teams at all — that's
    a normal case, not an error, so a failure here is swallowed to an empty list
    rather than raised (team is optional in AsanaClient/create_project anyway).
    """
    transport = transport or _urllib_transport
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    path = f"/organizations/{workspace_gid}/teams?opt_fields=name"
    status, payload = transport("GET", API_BASE + path, headers, None)
    if status >= 400:
        return []
    return payload.get("data", payload)


def list_users(token: str, workspace_gid: str, *, transport=None) -> list:
    """Return [{gid, name, email}] users in a workspace.

    Powers the playbook wizard's assignee pickers, so the client chooses a real
    teammate instead of typing an email that may not resolve. Returns [] on
    failure rather than raising — the wizard degrades to free-text entry.
    """
    transport = transport or _urllib_transport
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    path = f"/users?workspace={workspace_gid}&opt_fields=name,email&limit=100"
    status, payload = transport("GET", API_BASE + path, headers, None)
    if status >= 400:
        return []
    return payload.get("data", payload)


class AsanaClient:
    def __init__(self, token: str, workspace_gid: str, team_gid: str = None,
                 *, transport=None, max_retries: int = 3):
        if not token:
            raise AsanaError("missing Asana token")
        if not workspace_gid:
            raise AsanaError("missing Asana workspace gid")
        self.token = token
        self.workspace = workspace_gid
        self.team = team_gid
        self._transport = transport or _urllib_transport
        self.max_retries = max_retries

    @classmethod
    def from_config(cls) -> "AsanaClient":
        """Build a client from .env / environment (the only place secrets are read)."""
        from .config import get
        return cls(
            token=get("ASANA_PAT", required=True),
            workspace_gid=get("ASANA_WORKSPACE_GID", required=True),
            team_gid=get("ASANA_TEAM_GID"),
        )

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def _request(self, method: str, path: str, body=None):
        url = API_BASE + path
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        last_network_err = None
        for attempt in range(self.max_retries + 1):
            try:
                status, payload = self._transport(method, url, headers, body)
            except (urllib.error.URLError, OSError, socket.timeout) as e:
                # Transient network blip (e.g. connection reset mid-request) —
                # retry like a 429 rather than aborting a long multi-call build.
                last_network_err = e
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise AsanaError(
                    f"Asana {method} {path}: network error after retries: {e}",
                    method=method, path=path,
                ) from e
            if status == 429 and attempt < self.max_retries:
                time.sleep(min(2 ** attempt, 8))  # honor Asana rate limits
                continue
            if status >= 400:
                raise AsanaError(f"Asana {method} {path} -> {status}: {payload}",
                                 status=status, method=method, path=path)
            return payload.get("data", payload)
        raise AsanaError(f"Asana {method} {path}: rate limited after retries",
                         status=429, method=method, path=path) from last_network_err

    def _post(self, path: str, data: dict):
        return self._request("POST", path, {"data": data})

    # ── Lookup ───────────────────────────────────────────────────────────────

    def find_project_by_name(self, name: str):
        """Return the gid of an existing project with this exact name, else None.

        Scopes to the team when set, otherwise the whole workspace. This is the
        idempotency key for the manual flow: same contract → same name → no dupe.
        """
        if self.team:
            path = f"/teams/{self.team}/projects?opt_fields=name"
        else:
            path = f"/projects?workspace={self.workspace}&opt_fields=name"
        for p in self._request("GET", path) or []:
            if p.get("name") == name:
                return p["gid"]
        return None

    # ── Build ────────────────────────────────────────────────────────────────

    def create_project(self, plan, name: str, on_exists: str = "skip") -> dict:
        """Create a blank project and populate it from `plan`.

        Idempotent by name: if a project called `name` already exists and
        on_exists="skip" (default), nothing is created and the existing project is
        returned with existed=True. Pass on_exists="force" to create a duplicate.

        Returns {project_gid, project_url, created:{sections,tasks}, existed, warnings}.
        """
        if on_exists == "skip":
            existing = self.find_project_by_name(name)
            if existing:
                return {
                    "project_gid": existing,
                    "project_url": f"https://app.asana.com/0/{existing}",
                    "created": {"sections": 0, "tasks": 0},
                    "existed": True,
                    "warnings": [f"project '{name}' already exists — skipped "
                                 "(use force to create another)"],
                }

        proj_data = {"name": name, "workspace": self.workspace}
        if self.team:
            proj_data["team"] = self.team
        project = self._post("/projects", proj_data)
        pgid = project["gid"]

        created = {"sections": 0, "tasks": 0}
        warnings = []
        for section in plan.sections:
            sec = self._post(f"/projects/{pgid}/sections", {"name": section.name})
            sgid = sec["gid"]
            created["sections"] += 1
            for task in section.tasks:
                if not task.name.strip():
                    warnings.append("skipped a task with an empty name")
                    continue
                data = {
                    "name": task.name,
                    "notes": task.notes or "",
                    "projects": [pgid],  # Asana requires an anchor (projects/workspace/parent)
                    "memberships": [{"project": pgid, "section": sgid}],
                }
                assignee = getattr(task, "assignee", None)
                due_on = getattr(task, "due_on", None)
                if assignee:
                    data["assignee"] = assignee
                if due_on:
                    data["due_on"] = due_on
                self._post("/tasks", data)
                created["tasks"] += 1

        return {
            "project_gid": pgid,
            "project_url": f"https://app.asana.com/0/{pgid}",
            "created": created,
            "existed": False,
            "warnings": warnings,
        }
