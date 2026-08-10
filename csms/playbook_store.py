#!/usr/bin/env python3
"""csms.playbook_store — where the desktop app's playbook lives, and load/save it.

Distinct from csms.playbook (which just parses a playbook dict out of a YAML/JSON
file the CLI is pointed at): this module is for the desktop app's *generated*
playbook, built through the /playbook setup wizard instead of hand-edited YAML.

The playbook (default tasks, assignees, due-date rules) is business config, not a
secret — plain JSON on disk, not the OS keychain (contrast csms.credentials). But
it still can't live inside the frozen app bundle (read-only, replaced on every
update), so it goes in a per-OS user app-data directory that survives reinstalls.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_DIR_NAME = "Projectify"


def app_data_dir() -> Path:
    """Cross-platform per-user app-data directory (created if missing)."""
    home = Path.home()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    elif (home / "Library").exists():  # macOS
        base = home / "Library" / "Application Support"
    else:  # Linux / other
        base = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    d = base / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    _restrict(d, 0o700)
    return d


def _restrict(path: Path, mode: int) -> None:
    """Best-effort owner-only permissions.

    The playbook is not a secret, but it does carry internal staff assignments, and
    the default umask often leaves it world-readable. Harmless on a single-user Mac;
    it matters if this ever runs on a shared box. No-op on Windows, where POSIX mode
    bits don't apply — ACLs there already default to the user's profile.
    """
    if os.name == "nt":
        return
    try:
        os.chmod(path, mode)
    except OSError:
        pass  # a permissions tweak must never break saving the config


def default_playbook_path() -> Path:
    return app_data_dir() / "playbook.json"


def load_playbook(path=None) -> dict:
    """Return the saved playbook dict, or {} if none has been saved yet."""
    p = Path(path) if path else default_playbook_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8") or "{}")


def save_playbook(data: dict, path=None) -> Path:
    p = Path(path) if path else default_playbook_path()
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _restrict(p, 0o600)
    return p
