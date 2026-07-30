#!/usr/bin/env python3
"""csms.credentials — desktop-app secret storage via the OS keychain.

Desktop-app only (csms.desktop). The hosted web app (csms.webapp) stays on
.env-based config (see csms.config) — a shared server has no per-user OS
keychain to lean on. The client's own Asana token must never ship inside the
app or land in a plain file; this is the only place it's written, and it goes
straight to the OS-encrypted keychain (macOS Keychain / Windows Credential
Manager / Secret Service on Linux) via the `keyring` package.

`backend` is injectable (any object exposing get_password/set_password/
delete_password, matching the `keyring` module's API) so this is fully
testable offline without a real OS keychain — same pattern as the injectable
`transport` in csms.asana_client.
"""

from __future__ import annotations

SERVICE = "csms-projectify"
_KEY_PAT = "asana_pat"
_KEY_WORKSPACE = "asana_workspace_gid"
_KEY_TEAM = "asana_team_gid"


class CredentialStore:
    def __init__(self, backend=None):
        self._backend = backend

    def _b(self):
        if self._backend is None:
            import keyring
            self._backend = keyring
        return self._backend

    def get_pat(self):
        return self._b().get_password(SERVICE, _KEY_PAT)

    def set_pat(self, value: str) -> None:
        self._b().set_password(SERVICE, _KEY_PAT, value)

    def get_workspace_gid(self):
        return self._b().get_password(SERVICE, _KEY_WORKSPACE)

    def set_workspace_gid(self, value: str) -> None:
        self._b().set_password(SERVICE, _KEY_WORKSPACE, value)

    def get_team_gid(self):
        return self._b().get_password(SERVICE, _KEY_TEAM)

    def set_team_gid(self, value) -> None:
        if value:
            self._b().set_password(SERVICE, _KEY_TEAM, value)

    def has_credentials(self) -> bool:
        return bool(self.get_pat() and self.get_workspace_gid())

    def clear(self) -> None:
        """Wipe stored credentials (used by "change Asana connection")."""
        b = self._b()
        for key in (_KEY_PAT, _KEY_WORKSPACE, _KEY_TEAM):
            try:
                b.delete_password(SERVICE, key)
            except Exception:
                pass

    def build_client(self):
        """Construct an AsanaClient from stored credentials, or None if incomplete."""
        if not self.has_credentials():
            return None
        from .asana_client import AsanaClient
        return AsanaClient(self.get_pat(), self.get_workspace_gid(), self.get_team_gid())
