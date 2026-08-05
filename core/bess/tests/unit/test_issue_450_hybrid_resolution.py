"""End-to-end regression test for #450: the grid DP's SOE grid-snapping
must no longer be able to flip a near-tied window's choice, now that the
hybrid tie-detect/resolve/splice path (this branch) replaces PR #461's
full-MILP fix.

The primary pin is `result.reward_objective_cost` -- the DP's *own*
objective, accumulated straight from each period's `_compute_reward` return
(and recomputed by `_replay_accounting_pass` after the window is spliced).
`economic_summary.battery_solar_cost` is a *report* rebuilt from
`_build_period_data`'s energy fields, which is known to drift from the
objective (see TODO.md's `_build_period_data` reporting-drift entry and
`.superpowers/sdd/2026-08-04-hybrid-dp-pwl-tie-resolution/pwl-gap-investigation-report.md`
recommendation #3, both of which say fixture pinning must use the reward
objective until that drift is fixed). On this fixture the drift happens to be
~0.0257 SEK and to point the same way, so `battery_solar_cost` is kept as a
secondary pin -- it is not wrong, just not the metric this branch's own
investigation certified for the job.

Expected values were produced by the hybrid grid-DP + windowed-exact-PWL path
resolving this fixture's window (31, 40). See
`core/bess/tests/unit/data/regression_2026_08_02_043728.json`'s
`expected_results._note` for how the reported figure was established and why
it, not PR #461's MILP figure (-6.012541994, inflated by an unrelated MILP
self-throttle export-credit bug), is the correct target.

The tolerance is intentionally tight (1e-6) rather than the coarse
`round(x, 1)` used by `test_scenarios.py::test_all_scenarios`. Both pins
discriminate against the pre-fix behaviour at that tolerance: with tie
detection disabled the grid DP alone reports `reward_objective_cost`
-5.964025036 (vs the hybrid's -5.976470872, a 0.0124 SEK gap) and
`battery_solar_cost` -5.989678408 (vs -6.002124244). A test that only checked
one decimal place could not distinguish "hybrid resolution applied" from
"regressed back to the DP's original grid-snap-noise bug on this window."
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
    # Primary: the objective the DP actually minimises.
    assert result.reward_objective_cost == pytest.approx(
        -5.976470871749743, abs=1e-6
    ), (
        "the DP's own objective regressed -- the grid DP alone scores "
        "-5.964025036 on this fixture, so a value near that means the hybrid "
        "window resolution stopped being applied"
    )
    # Secondary: the reported summary, kept from the original Task 9 pin.
    assert result.economic_summary.battery_solar_cost == pytest.approx(
        -6.002124244499962, abs=1e-6
    )
