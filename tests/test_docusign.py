#!/usr/bin/env python3
"""Offline tests for the DocuSign auto-trigger scaffold (no network, no creds).

Fake transport for the client, a temp-file state store, and fakes for the poll loop.
The trigger mechanism (poll vs webhook) is undecided; this covers the shared logic.
"""

import io
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from csms.docusign import DocuSignClient, DocuSignError  # noqa: E402
from csms.state import ProcessedStore  # noqa: E402
from csms.poll import poll_once  # noqa: E402


class FakeTransport:
    """Returns canned (status, bytes) per DocuSign endpoint."""

    def __init__(self):
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url))
        assert headers["Authorization"].startswith("Bearer ")
        if "/documents/combined" in url:
            return 200, b"%PDF-1.4 fake signed envelope"
        if "/envelopes?" in url:
            return 200, json.dumps({"envelopes": [
                {"envelopeId": "E1", "status": "completed", "emailSubject": "Acme Sponsorship"},
                {"envelopeId": "E2", "status": "completed", "emailSubject": "Globex Sponsorship"},
            ]}).encode()
        if url.rstrip("/").endswith("/envelopes/E1"):
            return 200, json.dumps({"emailSubject": "Acme Sponsorship"}).encode()
        return 404, b"{}"


def _client():
    return DocuSignClient("ACC", "tok", transport=FakeTransport())


def test_list_completed_envelopes():
    envs = _client().list_completed_envelopes("2026-06-01")
    assert [e["envelopeId"] for e in envs] == ["E1", "E2"]


def test_download_combined_pdf_returns_bytes():
    pdf = _client().download_combined_pdf("E1")
    assert pdf.startswith(b"%PDF-")


def test_http_error_raises():
    t = FakeTransport()
    t.__call__ = lambda *a, **k: (403, b'{"message":"no"}')
    client = DocuSignClient("ACC", "tok", transport=lambda *a: (403, b'{"x":1}'))
    try:
        client.list_completed_envelopes("2026-06-01")
        assert False, "expected DocuSignError on 403"
    except DocuSignError:
        pass


def test_processed_store_roundtrip():
    d = Path(tempfile.mkdtemp())
    store = ProcessedStore(d / "processed.json")
    assert not store.has("E1")
    store.add("E1", project_gid="P1", processed_at="2026-06-30")
    assert store.has("E1") and store.get("E1")["project_gid"] == "P1"
    # persisted + reloadable
    store2 = ProcessedStore(d / "processed.json")
    assert store2.has("E1") and store2.get("E1")["project_gid"] == "P1"


class FakeDocuSign:
    def __init__(self):
        self.downloaded = []

    def list_completed_envelopes(self, since_iso, folder_id=None):
        return [
            {"envelopeId": "E1", "emailSubject": "Acme Sponsorship"},
            {"envelopeId": "E2", "emailSubject": "Globex Sponsorship"},
        ]

    def download_combined_pdf(self, envelope_id):
        self.downloaded.append(envelope_id)
        return b"%PDF-1.4 fake"


def test_poll_once_skips_processed_and_records_new():
    d = Path(tempfile.mkdtemp())
    store = ProcessedStore(d / "processed.json")
    store.add("E1", project_gid="OLD")  # already done

    built = []

    def fake_build(pdf, env):
        built.append(env["emailSubject"])
        return {"project_gid": "NEW-" + env["emailSubject"].split()[0]}

    ds = FakeDocuSign()
    out = poll_once(ds, "2026-06-01", store=store, build=fake_build)

    # only E2 was new → only it gets built/downloaded/recorded
    assert ds.downloaded == ["E2"]
    assert built == ["Globex Sponsorship"]
    assert [r["envelope_id"] for r in out] == ["E2"]
    assert store.has("E2") and store.get("E2")["project_gid"] == "NEW-Globex"
    # re-running is a no-op (E2 now recorded)
    assert poll_once(ds, "2026-06-01", store=store, build=fake_build) == []


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS  {name}")
    print("docusign scaffold OK")
