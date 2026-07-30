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
    return d


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
    return p
