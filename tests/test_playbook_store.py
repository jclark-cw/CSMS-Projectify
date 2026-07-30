#!/usr/bin/env python3
"""Tests for csms.playbook_store — the desktop app's generated playbook on disk."""

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from csms import playbook_store


def test_load_missing_file_returns_empty_dict():
    with tempfile.TemporaryDirectory() as d:
        assert playbook_store.load_playbook(Path(d) / "nope.json") == {}


def test_save_then_load_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "playbook.json"
        data = {
            "default_sections": [{"name": "Kickoff", "tasks": [
                {"name": "Verify contract", "assignee": None,
                 "due": {"anchor": "signed", "offset_days": 1}},
            ]}],
            "assignees": {"default": "ops@example.com", "by_section": {}},
            "due_dates": {"default": {"anchor": "signed", "offset_days": 30},
                         "cascade_days": 7, "by_section": {}},
        }
        playbook_store.save_playbook(data, path)
        assert playbook_store.load_playbook(path) == data


def test_default_playbook_path_is_stable_and_creates_parent_dir():
    p1 = playbook_store.default_playbook_path()
    p2 = playbook_store.default_playbook_path()
    assert p1 == p2
    assert p1.parent.exists()
    assert p1.name == "playbook.json"


def _run_standalone():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
