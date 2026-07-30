#!/usr/bin/env python3
"""Thin CLI shim — the parser now lives in the `csms` package (csms/parser.py).

Kept so existing commands still work:
    python3 parse_contract.py <contract.pdf> [--json out.json] [--csv out.csv]
Prefer `python3 -m csms <contract.pdf>` going forward.
"""

from csms.cli import main

if __name__ == "__main__":
    main()
