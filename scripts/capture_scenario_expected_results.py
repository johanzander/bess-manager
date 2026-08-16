#!/usr/bin/env python3
"""Re-pin each scenario fixture's `expected_results` from the current optimizer.

`core/bess/tests/unit/test_scenarios.py` asserts six recorded scalars per
fixture -- four economic (at 0.001 SEK / 0.01 pp) and two throughput (at 0.001
kWh). Until now they were re-pinned by hand whenever a deliberate behaviour
change moved them, which is error-prone at 38 fixtures and offers no way to see
how far each one actually moved.

This script rewrites those scalars from a live optimizer run and prints the
delta for every fixture it changes, so a PR can state the measured movement
rather than asserting that it re-pinned correctly.

Only the keys a fixture already carries are rewritten. The six debug-log-derived
`regression_*` fixtures record economics but not throughput, and this preserves
that -- adding `total_charged`/`total_discharged` where the generator never
produced them would pin a quantity nobody verified.

This is a *deliberate re-pin*, never a way to make a red suite green. Run it
only when the behaviour change that moved the numbers is itself intended, and
state the delta in the PR body. If you cannot explain a printed delta, that is
the finding -- do not commit it.

Usage: .venv/bin/python scripts/capture_scenario_expected_results.py [--check]

    --check  print deltas and exit non-zero if any fixture is stale, without
             writing.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.bess.tests.helpers import run_scenario  # noqa: E402

DATA_DIR = REPO_ROOT / "core/bess/tests/unit/data"

COST_TOLERANCE_SEK = 0.001
PCT_TOLERANCE = 0.01
ENERGY_TOLERANCE_KWH = 0.001

# key -> (extractor, tolerance the scenario test applies)
FIELDS = {
    "base_cost": (lambda r: r.economic_summary.grid_only_cost, COST_TOLERANCE_SEK),
    "battery_solar_cost": (
        lambda r: r.economic_summary.battery_solar_cost,
        COST_TOLERANCE_SEK,
    ),
    "base_to_battery_solar_savings": (
        lambda r: r.economic_summary.grid_to_battery_solar_savings,
        COST_TOLERANCE_SEK,
    ),
    "base_to_battery_solar_savings_pct": (
        lambda r: r.economic_summary.grid_to_battery_solar_savings_pct,
        PCT_TOLERANCE,
    ),
    "total_charged": (
        lambda r: sum(pd.energy.battery_charged for pd in r.period_data),
        ENERGY_TOLERANCE_KWH,
    ),
    "total_discharged": (
        lambda r: sum(pd.energy.battery_discharged for pd in r.period_data),
        ENERGY_TOLERANCE_KWH,
    ),
}

PRECISION = 5


def main() -> None:
    check_only = "--check" in sys.argv
    changed: list[str] = []

    for path in sorted(DATA_DIR.glob("*.json")):
        scenario = json.loads(path.read_text())
        expected = scenario.get("expected_results")
        if expected is None:
            continue

        result = run_scenario(scenario)
        deltas = []
        for key, (extract, tolerance) in FIELDS.items():
            if key not in expected:
                continue
            actual = round(extract(result), PRECISION)
            if abs(actual - expected[key]) <= tolerance:
                continue
            deltas.append(f"{key} {expected[key]} -> {actual}")
            if not check_only:
                expected[key] = actual

        if not deltas:
            continue

        changed.append(path.name)
        verb = "STALE" if check_only else "repin"
        print(f"  {verb} {path.name}")
        for line in deltas:
            print(f"          {line}")
        if not check_only:
            path.write_text(json.dumps(scenario, indent=2) + "\n")

    if check_only and changed:
        print(f"\n{len(changed)} fixture(s) stale. Re-run without --check.")
        sys.exit(1)
    print(f"\n{len(changed)} fixture(s) re-pinned.")


if __name__ == "__main__":
    main()
