#!/usr/bin/env python3
"""csms.poll — the mechanism-agnostic auto-trigger loop.

poll_once() finds newly-completed envelopes, skips any already processed, downloads
each signed PDF, builds the Asana project, and records the envelope so it never runs
twice. A scheduled launchd/cron wrapper OR a Connect webhook handler both just call
poll_once() — the trigger mechanism is decided separately, this logic is shared.
"""

from __future__ import annotations

import os
import tempfile

from .engine import build_project
from .state import ProcessedStore


def build_from_pdf_bytes(pdf_bytes: bytes, name=None, **kwargs):
    """Build an Asana project from raw PDF bytes via a short-lived temp file.

    Extra kwargs (asana, force, playbook, signed_date, event_date) pass through to
    build_project — so the auto-trigger can apply the playbook with the envelope's
    signing date.
    """
    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        with open(path, "wb") as f:
            f.write(pdf_bytes)
        os.close(fd)
        return build_project(path, dry_run=False, project_name=name, **kwargs)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _gid(result):
    return getattr(result, "project_gid", None) if not isinstance(result, dict) \
        else result.get("project_gid")


def _default_build(pdf_bytes, env):
    return build_from_pdf_bytes(pdf_bytes, env.get("emailSubject") or None)


def poll_once(docusign, since_iso: str, *, store=None, folder_id=None,
              build=None) -> list:
    """Process completed envelopes once. Returns [{envelope_id, project_gid}] for new ones.

    `build(pdf_bytes, envelope)` does the work — the whole envelope is passed so the
    builder can use its subject (project name) and completion date (signing date).
    Injectable for offline testing: pass fake `docusign`, `store`, and `build`.
    """
    store = store if store is not None else ProcessedStore()
    build = build or _default_build

    processed = []
    for env in docusign.list_completed_envelopes(since_iso, folder_id):
        eid = env.get("envelopeId")
        if not eid or store.has(eid):
            continue  # never reprocess an envelope
        pdf = docusign.download_combined_pdf(eid)
        result = build(pdf, env)
        gid = _gid(result)
        store.add(eid, project_gid=gid)
        processed.append({"envelope_id": eid, "project_gid": gid})
    return processed
