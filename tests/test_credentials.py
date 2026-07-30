#!/usr/bin/env python3
"""Tests for csms.credentials — the desktop app's keychain-backed store.

Uses an injected in-memory fake backend (matching keyring's get/set/delete_password
API) so this runs offline with no real OS keychain and no `keyring` package needed.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from csms.credentials import CredentialStore


class FakeKeyringBackend:
    def __init__(self):
        self._data = {}

    def get_password(self, service, key):
        return self._data.get((service, key))

    def set_password(self, service, key, value):
        self._data[(service, key)] = value

    def delete_password(self, service, key):
        del self._data[(service, key)]  # raises like real keyring if missing


def test_no_credentials_by_default():
    store = CredentialStore(backend=FakeKeyringBackend())
    assert store.has_credentials() is False
    assert store.build_client() is None


def test_set_and_get_roundtrip():
    store = CredentialStore(backend=FakeKeyringBackend())
    store.set_pat("tok123")
    store.set_workspace_gid("WS1")
    store.set_team_gid("TEAM1")
    assert store.get_pat() == "tok123"
    assert store.get_workspace_gid() == "WS1"
    assert store.get_team_gid() == "TEAM1"
    assert store.has_credentials() is True


def test_team_gid_optional():
    store = CredentialStore(backend=FakeKeyringBackend())
    store.set_pat("tok123")
    store.set_workspace_gid("WS1")
    store.set_team_gid(None)  # no team chosen — must not error
    assert store.has_credentials() is True
    assert store.get_team_gid() is None


def test_build_client_uses_stored_values():
    store = CredentialStore(backend=FakeKeyringBackend())
    store.set_pat("tok123")
    store.set_workspace_gid("WS1")
    store.set_team_gid("TEAM1")
    client = store.build_client()
    assert client.token == "tok123"
    assert client.workspace == "WS1"
    assert client.team == "TEAM1"


def test_clear_removes_everything():
    store = CredentialStore(backend=FakeKeyringBackend())
    store.set_pat("tok123")
    store.set_workspace_gid("WS1")
    store.clear()
    assert store.has_credentials() is False
    assert store.get_pat() is None


def test_clear_is_safe_when_nothing_stored():
    store = CredentialStore(backend=FakeKeyringBackend())
    store.clear()  # must not raise even though nothing was ever set


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
