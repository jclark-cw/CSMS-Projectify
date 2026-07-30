#!/usr/bin/env python3
"""csms.docusign — pull completed sponsorship envelopes + their signed PDFs.

Phase 5 (auto-trigger). Stdlib HTTP (urllib, TLS verified), transport injectable so
the listing/download logic is unit-tested offline. Live auth is DocuSign JWT Grant
(unattended) — from_config() builds an access token from DOCUSIGN_* in .env; that
path needs PyJWT (lazy import, clear error if missing) and the integration key +
private key + admin consent.

The trigger *mechanism* (scheduled poll vs Connect webhook) is deliberately not
decided here — both feed csms.poll.poll_once(), which uses this client.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
import urllib.error

PROD_BASE = "https://www.docusign.net/restapi"
PROD_OAUTH = "account.docusign.com"
DEMO_OAUTH = "account-d.docusign.com"


class DocuSignError(RuntimeError):
    """Any DocuSign API / configuration failure."""


def _urllib_transport(method: str, url: str, headers: dict, body=None):
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # TLS verified by default
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class DocuSignClient:
    def __init__(self, account_id: str, access_token: str,
                 base_uri: str = PROD_BASE, *, transport=None):
        if not account_id:
            raise DocuSignError("missing DocuSign account id")
        if not access_token:
            raise DocuSignError("missing DocuSign access token")
        self.account_id = account_id
        self.token = access_token
        self.base_uri = base_uri.rstrip("/")
        self._transport = transport or _urllib_transport

    @classmethod
    def from_config(cls, *, transport=None) -> "DocuSignClient":
        """Build a client from .env via a JWT-grant access token (needs PyJWT)."""
        from .config import get
        account_id = get("DOCUSIGN_ACCOUNT_ID", required=True)
        base_uri = get("DOCUSIGN_BASE_URI", default=PROD_BASE)
        oauth_host = get("DOCUSIGN_OAUTH_HOST",
                         default=DEMO_OAUTH if "demo" in base_uri else PROD_OAUTH)
        token = _jwt_access_token(
            integration_key=get("DOCUSIGN_INTEGRATION_KEY", required=True),
            user_id=get("DOCUSIGN_USER_ID", required=True),
            private_key_path=get("DOCUSIGN_PRIVATE_KEY_PATH", required=True),
            oauth_host=oauth_host,
            transport=transport,
        )
        return cls(account_id, token, base_uri=base_uri, transport=transport)

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def _url(self, path: str) -> str:
        return f"{self.base_uri}/v2.1/accounts/{self.account_id}{path}"

    def _get(self, path: str, accept: str = "application/json"):
        headers = {"Authorization": f"Bearer {self.token}", "Accept": accept}
        status, raw = self._transport("GET", self._url(path), headers, None)
        if status >= 400:
            raise DocuSignError(f"DocuSign GET {path} -> {status}: {raw[:300]!r}")
        return raw

    # ── Envelopes ──────────────────────────────────────────────────────────────

    def list_completed_envelopes(self, since_iso: str, folder_id: str = None) -> list:
        """Completed envelopes since `since_iso` (ISO date/time). Optionally scope to a
        folder (e.g. the sponsorship folder).

        Note: the API's `status=completed` query filter proved unreliable (it dropped a
        genuinely-completed envelope), so we fetch since `from_date` and filter on
        status in code. The from_date scoping keeps the result set bounded.
        """
        q = {"from_date": since_iso}
        if folder_id:
            q["folder_ids"] = folder_id
        path = "/envelopes?" + urllib.parse.urlencode(q)
        envelopes = json.loads(self._get(path)).get("envelopes", [])
        return [e for e in envelopes if e.get("status") == "completed"]

    def download_combined_pdf(self, envelope_id: str) -> bytes:
        """The full signed envelope as one PDF (what the parser consumes)."""
        return self._get(f"/envelopes/{envelope_id}/documents/combined",
                         accept="application/pdf")

    def envelope_subject(self, envelope_id: str) -> str:
        env = json.loads(self._get(f"/envelopes/{envelope_id}"))
        return env.get("emailSubject", "")


def _jwt_access_token(integration_key, user_id, private_key_path, oauth_host,
                      *, scopes="signature impersonation", transport=None):
    """Exchange a JWT assertion for a DocuSign access token (JWT Grant).

    Lazy-imports PyJWT so the offline scaffold/tests never need it. Live use needs:
    `pip install -r requirements-docusign.txt` plus a one-time admin consent grant.
    """
    try:
        import jwt  # PyJWT
    except ImportError as e:
        raise DocuSignError(
            "DocuSign JWT auth needs PyJWT — install requirements-docusign.txt"
        ) from e
    import time
    from pathlib import Path

    key = Path(private_key_path).read_text()
    now = int(time.time())
    assertion = jwt.encode(
        {"iss": integration_key, "sub": user_id, "aud": oauth_host,
         "iat": now, "exp": now + 3600, "scope": scopes},
        key, algorithm="RS256")

    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }).encode()
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    tx = transport or _urllib_transport
    status, raw = tx("POST", f"https://{oauth_host}/oauth/token", headers, body)
    if status >= 400:
        raise DocuSignError(
            f"DocuSign JWT grant failed ({status}). If 'consent_required', grant "
            f"admin consent once, then retry. {raw[:300]!r}")
    return json.loads(raw)["access_token"]
