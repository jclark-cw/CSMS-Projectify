"""csms.config — central configuration / secrets access.

Secrets (Asana PAT, DocuSign keys, …) come from the environment, optionally
populated from a git-ignored .env file. This module is the ONLY place secrets
are read. Rules:
  • Never hardcode secret values.
  • Never log or print secret values.
  • .env must be git-ignored and chmod 600.

No secrets are required yet (Phase 0 is parsing only); this establishes the
pattern so Phase 2's Asana wiring has a single, auditable entry point.
"""

import os
from pathlib import Path

_ENV_LOADED = False


def _load_dotenv(path: str = ".env") -> None:
    """Populate os.environ from a simple KEY=VALUE .env file, if present.

    Existing environment variables always win (setdefault), so real env vars
    are never clobbered by the file. Dependency-free on purpose.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    p = Path(path)
    if p.exists():
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), val)
    _ENV_LOADED = True


def get(name: str, default=None, required: bool = False):
    """Return a config value from the environment (loading .env on first use).

    Raises RuntimeError if `required` and the value is missing/empty. The error
    names only the key, never a value.
    """
    _load_dotenv()
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(
            f"Missing required config: {name} (set it in .env or the environment)"
        )
    return val
