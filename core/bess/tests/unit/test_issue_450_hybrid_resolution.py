"""End-to-end regression test for #450: the grid DP's SOE grid-snapping
must no longer be able to flip a near-tied window's choice, now that the
hybrid tie-detect/resolve/splice path (this branch) replaces PR #461's
full-MILP fix.

Expected cost is the fixture's current pinned `battery_solar_cost`
(-6.002124244499962), produced by the hybrid grid-DP + windowed-exact-PWL
path resolving this fixture's window (31, 40). See
`core/bess/tests/unit/data/regression_2026_08_02_043728.json`'s
`expected_results._note` and
`.superpowers/sdd/2026-08-04-hybrid-dp-pwl-tie-resolution/pwl-gap-investigation-report.md`
for how this value was established and why it, not PR #461's MILP figure
(-6.012541994, inflated by an unrelated MILP self-throttle export-credit
bug), is the correct target.

The tolerance is intentionally tight (1e-6) rather than the coarse
`round(x, 1)` used by `test_scenarios.py::test_all_scenarios`: the grid DP
alone (without the hybrid resolution) reports -5.989678408 on this same
fixture -- a ~0.0125 SEK gap from the hybrid's -6.002124244. A test that
only checked one decimal place could not distinguish "hybrid resolution
applied" from "regressed back to the DP's original grid-snap-noise bug on
this window." At abs=1e-6 a regression to the old buggy value fails hard.
"""

import pytest

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.tests.unit.test_scenarios import build_scenario_inputs


def test_450_fixture_reaches_hybrid_resolved_cost():
    scenario, battery_settings, buy_prices, sell_prices, period_duration_hours = (
        build_scenario_inputs("regression_2026_08_02_043728")
    )
    result = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=scenario["home_consumption"],
        solar_production=scenario["solar_production"],
        initial_soe=scenario["battery"]["initial_soe"],
        battery_settings=battery_settings,
        period_duration_hours=period_duration_hours,
        terminal_value_per_kwh=scenario.get("terminal_value_per_kwh", 0.0),
    )
    assert result.economic_summary.battery_solar_cost == pytest.approx(
        -6.002124244499962, abs=1e-6
    )
