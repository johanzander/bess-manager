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

from core.bess.terminal_value import (  # noqa: E402
    calculate_terminal_value_per_kwh,
)
from core.bess.tests.helpers import _scenario_inputs  # noqa: E402

DATA_DIR = REPO_ROOT / "core/bess/tests/unit/data"

# Rounded so the fixture stays readable and diffable; far finer than the
# 0.001 SEK tolerance the scenario assertions use.
PRECISION = 9


def terminal_value_for(scenario: dict) -> float:
    """Production terminal value for one scenario, with #422 cap scoping."""
    inputs = _scenario_inputs(scenario)
    buy_price = inputs["buy_price"]
    sell_price = inputs["sell_price"]
    periods_per_day = round(24 / inputs["period_duration_hours"])

    # PRECONDITION, unenforceable here: the horizon ends on a day boundary.
    # Production groups the cap window by calendar date; this slice matches it
    # only under that assumption. It holds for the whole corpus today -- every
    # fixture is either shorter than a day, or "partial first day + whole
    # terminal day" -- and `regression_frank_debug_before`'s independently
    # pinned 0.143013413 is the evidence, since the slice reproduces it exactly
    # while the unscoped array gives the pre-#422 0.195488259.
    #
    # It cannot be asserted from fixture data: with no timestamps, a horizon of
    # k + periods_per_day is indistinguishable from one ending mid-day for any
    # k, so no arithmetic on the length separates the two (in particular
    # `n % periods_per_day == 0` is NOT the precondition -- it is false for
    # every correct multi-day fixture in the corpus, 118 % 96 = 22 among them).
    # A fixture ending mid-day would therefore get a cap window straddling two
    # days, silently. The durable fix is upstream: once a run records its own
    # terminal value in `input_data` (#602 follow-up), a bundle-derived fixture
    # should carry the real value and this script should leave it alone, which
    # is already the behaviour for any fixture that has one recorded.
    cap_sell_price = sell_price[-periods_per_day:]
    return round(
        calculate_terminal_value_per_kwh(
            buy_price, cap_sell_price, inputs["battery_settings"]
        ),
        PRECISION,
    )


def main() -> None:
    check_only = "--check" in sys.argv
    stale: list[str] = []

    for path in sorted(DATA_DIR.glob("*.json")):
        scenario = json.loads(path.read_text())
        computed = terminal_value_for(scenario)
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
