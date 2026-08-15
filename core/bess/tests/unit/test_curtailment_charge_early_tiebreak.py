"""Charge-early tie-break under export curtailment (#269 follow-up).

The #269 sell-price floor makes every below-floor period's export worth
exactly 0 to the DP, so "charge the headroom now, curtail later" and
"curtail now, charge later" earn identical reward whenever the remaining
below-floor surplus exceeds the battery's headroom. The argmax then picks
between exactly-tied candidates on float noise, and the deferred-charge
pick actuates as charge-rate 0% + Meter 1 -- physically clipping PV to
house load while multi-kWh headroom sits unused (live report on #269,
8 Aug 2026 14:30: SOE 12.0/15, ~4.7 kWh below-floor surplus remaining,
plan held SOE flat for two periods before filling).

Charge-early is stochastically dominant: equal model reward, strictly
better under forecast error in either direction (captures above-forecast
PV that curtailment would clip; preserves slack toward the evening
export block if later solar underdelivers). These tests pin that the DP
absorbs below-floor surplus at the earliest physical opportunity.
"""

from core.bess.tests.helpers import run_scenario_realized
from core.bess.tests.unit.test_scenarios import load_test_scenario

# The candidate-level cases for this tie-break now live in
# `test_tie_policy.py` as rows 1 and 4 of the P2 preference table -- they
# moved with the rule itself, unchanged. What stays here is the
# end-to-end evidence against the reporter's own captured plan.


# Fixture generated from the reporter's real debug bundle
# (bess-debug-2026-08-08-143843.md) via from_debug_log.py --issue 269.
# Plan starts at 14:30 with initial_soe 12.0/15.0 kWh, curtailment
# enabled at floor 0.0, and periods 0-9 below-floor with solar surplus
# (2x0.62 + 4x0.45 + 4x0.41 ~= 4.7 kWh) against 3.0 kWh headroom.
SCENARIO = "regression_2026_08_08_143843"


def test_below_floor_surplus_is_absorbed_immediately_not_deferred():
    scenario = load_test_scenario(SCENARIO)
    result, _ = run_scenario_realized(scenario)
    periods = result.period_data

    # Period 0 (14:30): surplus 0.622 kWh, 3.0 kWh headroom. The buggy
    # plan holds SOE at exactly 12.0 here (and again at 14:45); charging
    # early absorbs the full surplus (x0.97 charge efficiency ~= 0.60).
    assert periods[0].energy.battery_soe_end >= 12.0 + 0.55, (
        f"period 0 held SOE at {periods[0].energy.battery_soe_end:.2f} "
        "with 3 kWh headroom and 0.62 kWh of below-floor surplus -- "
        "deferred charging under the curtailment floor tie"
    )

    # Absorbing every below-floor surplus kWh as it arrives fills the
    # battery during period 6 (16:00); the buggy deferred plan reaches
    # full only at period 9 (16:45), leaving zero slack against solar
    # shortfall before the evening export block.
    first_full = next(
        (i for i, pd in enumerate(periods) if pd.energy.battery_soe_end >= 14.95),
        None,
    )
    assert first_full is not None and first_full <= 6, (
        f"battery first reaches 15.0 kWh at period {first_full}; "
        "earliest physically possible is period 6"
    )


def test_charge_early_plan_is_faithful_and_costs_no_more():
    scenario = load_test_scenario(SCENARIO)
    result, realized_cost = run_scenario_realized(scenario)
    planned_cost = result.economic_summary.battery_solar_cost

    # R == P up to the one pinned residual: #497 (PR #511) removed this
    # fixture's +0.0490 phantom-export share and collapsed the corpus-wide
    # gap table to exact equality; what remains is the +0.0203 SEK #502
    # share (the inverter simulator has no model of PV export-limit
    # curtailment, so execution still pays the honest price for a period
    # BSM will actually curtail to zero at runtime -- see TODO.md's "From
    # #502" entry). Assert against that single source of truth rather than
    # a bare tolerance.
    from core.bess.tests.integration.test_plan_faithfulness import (
        KNOWN_PLAN_EXECUTION_GAP_SEK,
        PLAN_EXECUTION_TOLERANCE_SEK,
    )

    gap = realized_cost - planned_cost
    pinned = KNOWN_PLAN_EXECUTION_GAP_SEK[SCENARIO]
    assert abs(gap - pinned) <= PLAN_EXECUTION_TOLERANCE_SEK, (
        f"plan-execution gap {gap:+.4f} SEK moved off its pin {pinned:+.4f} "
        f"(R={realized_cost:.4f}, P={planned_cost:.4f}) -- re-measure and "
        "re-pin in test_plan_faithfulness.py if the movement is intended"
    )

    # The tie-break must never buy earliness with money: no grid import
    # to charge (the below-floor surplus alone fills the battery), so
    # total import stays what the house alone needs.
    for i, pd in enumerate(result.period_data[:10]):
        deficit = max(
            0.0,
            scenario["home_consumption"][i] - scenario["solar_production"][i],
        )
        assert pd.energy.grid_imported <= deficit + 1e-6, (
            f"period {i} imports {pd.energy.grid_imported:.3f} kWh to "
            "charge during a below-floor window"
        )
