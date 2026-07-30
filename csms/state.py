#!/usr/bin/env python3
"""csms.state — durable record of processed DocuSign envelopes (idempotency key).

For the auto-trigger, project-name idempotency isn't enough — we must never
reprocess the same envelope. This is a tiny JSON store mapping envelope id →
{project_gid, processed_at}. The state/ dir is git-ignored.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_PATH = Path("state") / "processed_envelopes.json"


class ProcessedStore:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)
        self._data = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text() or "{}")
            except ValueError:
                self._data = {}

    def has(self, envelope_id: str) -> bool:
        return envelope_id in self._data

    def add(self, envelope_id: str, project_gid: str = None, processed_at: str = None):
        self._data[envelope_id] = {
            "project_gid": project_gid,
            "processed_at": processed_at,
        }
        self._flush()

    def get(self, envelope_id: str):
        return self._data.get(envelope_id)

    def all(self) -> dict:
        return dict(self._data)

    def _flush(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.replace(self.path)  # atomic on the same filesystem
