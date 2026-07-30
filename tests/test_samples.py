#!/usr/bin/env python3
"""Parse the committed synthetic sample contracts.

Unlike the real-contract tests, these fixtures are checked in (fake data), so this
runs in CI with no PII. Regenerate with: python3 tools/make_sample_contracts.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from csms.parser import parse_contract  # noqa: E402

SAMPLES = REPO_ROOT / "samples"

# name -> (sections, tasks)
EXPECT = {
    "sample_acme_grouped.pdf": (4, 7),
    "sample_globex_flat.pdf": (2, 5),
    "sample_initech_grouped.pdf": (3, 5),
}


def test_samples_present():
    missing = [n for n in EXPECT if not (SAMPLES / n).exists()]
    assert not missing, f"missing samples {missing} — run tools/make_sample_contracts.py"


def test_samples_parse_to_expected_shape():
    for name, (sections, tasks) in EXPECT.items():
        path = SAMPLES / name
        if not path.exists():
            continue
        data = parse_contract(str(path))
        assert len(data) == sections, f"{name}: {len(data)} sections != {sections}"
        got_tasks = sum(len(e["tasks"]) for e in data)
        assert got_tasks == tasks, f"{name}: {got_tasks} tasks != {tasks}"
        assert all(e["tasks"] for e in data), f"{name}: has an empty section"


if __name__ == "__main__":
    test_samples_present()
    test_samples_parse_to_expected_shape()
    print("samples OK")
