#!/usr/bin/env python3
"""Capture (or re-capture) the action-selector bit-parity goldens.

Writes one JSON per fixture in `core/bess/tests/unit/data/` into
`core/bess/tests/unit/data/golden/`, holding the emitted `actions`, the
`soe_trajectory` and `economic_summary.battery_solar_cost` produced by
`optimize_battery_schedule` on that fixture.

The goldens exist so a *refactor* can prove it changed nothing
(`core/bess/tests/unit/test_action_selector_parity.py`). They are written
with `json.dump`, whose float repr round-trips exactly, so the comparison
is bit-identical rather than approximate.

Golden lifecycle: a phase that deliberately changes behavior
(`docs/superpowers/plans/2026-08-09-optimizer-target-architecture.md`,
Phase 2 onward) re-runs this script as part of its measured-delta step and
states the regeneration in its PR body. The parity test itself is never
deleted or skipped -- a phase that cannot regenerate goldens has not
measured its delta.

Usage: .venv/bin/python scripts/capture_selector_goldens.py
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.bess.tests.unit.golden_capture import (  # noqa: E402
    GOLDEN_DIR,
    capture_fixture,
    fixture_names,
)


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for name in fixture_names():
        golden = capture_fixture(name)
        (GOLDEN_DIR / f"{name}.json").write_text(json.dumps(golden, indent=1) + "\n")
        print(f"captured {name}: {len(golden['actions'])} periods")


if __name__ == "__main__":
    main()
