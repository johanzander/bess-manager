#!/usr/bin/env python3
"""Record each pinned scenario's production terminal value into its fixture.

Every scenario in `core/bess/tests/unit/data/` used to fall through to
`optimize_battery_schedule`'s `terminal_value_per_kwh=0.0` default, so the
branch that builds the DP's terminal row never executed and `V[horizon]` stayed
all zeros. The entire pinned corpus was therefore blind to the terminal value in
both directions -- it could neither regress nor validate it (TODO.md, found
while investigating #345).

This script closes that by computing each fixture's terminal value the way
production does -- `core/bess/terminal_value.py` applied to that fixture's own
prices -- and writing it into the fixture as an explicit
`terminal_value_per_kwh` key. Explicit rather than inferred at load time, for
the same reason `export_curtailment_active` is recorded explicitly: a reader of
the fixture can see what the scenario runs at, and the value replays
identically even if the helper changes.

Cap scoping (#422): production scopes the arbitrage-consistency cap to sell
prices on the terminal boundary's own calendar day. Fixtures carry no
timestamps, so the equivalent window here is the last `24 / period_duration`
periods -- verified to reproduce `regression_frank_debug_before`'s
independently-pinned 0.143013413 exactly, where the unscoped array gives
0.195488259 (the pre-#422 value). `buy_prices` stays the full remaining horizon,
matching production.

Re-running is safe and idempotent. Because a terminal value changes what the DP
plans, re-running invalidates the pinned economics: regenerate in this order.

    .venv/bin/python scripts/capture_scenario_terminal_values.py
    .venv/bin/python scripts/capture_selector_goldens.py
    .venv/bin/python scripts/capture_vpp_baseline.py --add-new

Usage: .venv/bin/python scripts/capture_scenario_terminal_values.py [--check]

    --check  exit non-zero if any fixture's recorded value is missing or stale,
             without writing. Intended for local verification, not CI.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.bess.tests.helpers import scenario_terminal_value  # noqa: E402

DATA_DIR = REPO_ROOT / "core/bess/tests/unit/data"

# Rounded so the fixture stays readable and diffable; far finer than the
# 0.001 SEK tolerance the scenario assertions use.
PRECISION = 9


def main() -> None:
    check_only = "--check" in sys.argv
    stale: list[str] = []

    for path in sorted(DATA_DIR.glob("*.json")):
        scenario = json.loads(path.read_text())
        computed = round(scenario_terminal_value(scenario), PRECISION)
        recorded = scenario.get("terminal_value_per_kwh")

        if recorded is not None and abs(recorded - computed) < 10**-PRECISION:
            print(f"  ok    {path.name}: {recorded}")
            continue

        stale.append(path.name)
        if check_only:
            print(f"  STALE {path.name}: recorded={recorded} computed={computed}")
            continue

        scenario["terminal_value_per_kwh"] = computed
        path.write_text(json.dumps(scenario, indent=2) + "\n")
        print(f"  write {path.name}: {recorded} -> {computed}")

    if check_only and stale:
        print(f"\n{len(stale)} fixture(s) missing or stale. Re-run without --check.")
        sys.exit(1)
    print(f"\n{len(stale)} fixture(s) updated.")


if __name__ == "__main__":
    main()
