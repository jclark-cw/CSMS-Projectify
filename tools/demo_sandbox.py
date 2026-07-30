#!/usr/bin/env python3
"""Projectify DEMO mode — the full app, wired so it CANNOT touch a real Asana board.

For walkthroughs, screen shares and review calls. Everything is the real code
(same Flask app, same routes, same engine, same parser) except three seams:

  1. Credentials come from an in-memory store, not the OS keychain — so the
     demo neither reads nor writes the presenter's real stored connection.
  2. The Asana member lookup is stubbed, so the assignee pickers show a cast of
     example people instead of 401-ing.
  3. The Asana client is a fake that records what it *would* have created and
     returns a realistic result — so "Create in Asana" can be clicked live,
     including the duplicate-protection path, with zero risk to a real board.

Why this exists: the hosted app (`python3 -m csms.webapp`) reads .env, which
points at the client's LIVE Asana workspace. Clicking "Create in Asana" there
creates a real project. Never demo from that.

Run:  python3 tools/demo_sandbox.py       → http://127.0.0.1:8013
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import csms.webapp as webapp_mod  # noqa: E402
from csms.webapp import create_app  # noqa: E402
from csms.credentials import CredentialStore  # noqa: E402

PORT = 8013

DEMO_MEMBERS = [
    {"gid": "1001", "name": "Gianna Whitver", "email": "gianna@example.com"},
    {"gid": "1002", "name": "Dave Algava", "email": "dave@example.com"},
    {"gid": "1003", "name": "JB Clark", "email": "jb@example.com"},
    {"gid": "1004", "name": "Events Team", "email": "events@example.com"},
]


class FakeAsanaClient:
    """Stands in for AsanaClient. Records instead of creating.

    Mirrors the real create_project contract, including name-based idempotency,
    so the "Already in Asana / Create another anyway" flow can be demoed too.
    """

    def __init__(self):
        self.created = {}   # name -> gid
        self.log = []       # what each call would have built

    def create_project(self, plan, name, on_exists="skip"):
        sections = len(plan.sections)
        tasks = sum(len(s.tasks) for s in plan.sections)

        if on_exists == "skip" and name in self.created:
            gid = self.created[name]
            print(f"  [demo] '{name}' already exists -> skipped (no duplicate)")
            return {
                "project_gid": gid,
                "project_url": f"https://app.asana.com/0/DEMO-{gid}",
                "created": {"sections": 0, "tasks": 0},
                "existed": True,
                "warnings": ["DEMO MODE — nothing was written to Asana"],
            }

        gid = f"{9000 + len(self.log)}"
        self.created[name] = gid
        self.log.append({"name": name, "sections": sections, "tasks": tasks})
        print(f"  [demo] would create '{name}': {sections} sections, {tasks} tasks")
        for s in plan.sections:
            print(f"         · {s.name} ({len(s.tasks)} tasks)")
            for t in s.tasks:
                bits = [t.name]
                if getattr(t, "assignee", None):
                    bits.append(f"assignee={t.assignee}")
                if getattr(t, "due_on", None):
                    bits.append(f"due={t.due_on}")
                print(f"             - {' | '.join(bits)}")
        return {
            "project_gid": gid,
            "project_url": f"https://app.asana.com/0/DEMO-{gid}",
            "created": {"sections": sections, "tasks": tasks},
            "existed": False,
            "warnings": ["DEMO MODE — nothing was written to Asana"],
        }


class MemoryBackend:
    """In-memory stand-in for the OS keychain (same API as `keyring`)."""

    def __init__(self):
        self._data = {}

    def get_password(self, service, key):
        return self._data.get((service, key))

    def set_password(self, service, key, value):
        self._data[(service, key)] = value

    def delete_password(self, service, key):
        self._data.pop((service, key), None)


class DemoCredentialStore(CredentialStore):
    """Credentials live only in memory, and always hand back the fake client."""

    def __init__(self, fake_client):
        super().__init__(backend=MemoryBackend())
        self._fake = fake_client

    def build_client(self):
        return self._fake


def build_demo_app(*, connected: bool = True):
    """connected=False starts at the first-run wizard (to demo onboarding)."""
    fake = FakeAsanaClient()
    webapp_mod.list_users = lambda token, workspace_gid, transport=None: DEMO_MEMBERS

    app = create_app(desktop=True)

    @app.get("/samples/<path:name>")
    def _samples(name):
        """Serve the synthetic sample contracts (demo builds only) so they can be
        loaded without a file dialog — handy for screen shares and UI checks."""
        from flask import send_from_directory, abort
        if not name.endswith(".pdf"):
            abort(404)
        return send_from_directory(REPO_ROOT / "samples", name)

    store = DemoCredentialStore(fake)
    if connected:
        store.set_pat("DEMO-TOKEN-NOT-REAL")
        store.set_workspace_gid("DEMO_WORKSPACE")
    app.config["CRED_STORE"] = store
    app.config["PLAYBOOK_PATH"] = Path(tempfile.mkdtemp()) / "playbook.json"
    return app, fake


def main():
    connected = "--first-run" not in sys.argv
    app, _ = build_demo_app(connected=connected)
    start = "first-run setup wizard" if not connected else "main upload page"
    print("=" * 68)
    print(" Projectify — DEMO MODE")
    print(" Nothing here can reach a real Asana board. Safe to click anything.")
    print(f" Starting on: the {start}")
    print(f" Open: http://127.0.0.1:{PORT}/")
    print("   /          upload a contract -> preview -> create")
    print("   /setup     first-run Asana connection wizard")
    print("   /playbook  default tasks, assignees, due dates")
    print(" Sample contracts to drag in: samples/*.pdf")
    print("=" * 68)
    app.run(host="127.0.0.1", port=PORT)


if __name__ == "__main__":
    main()
