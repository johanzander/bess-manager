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

from core.bess.dp_battery_algorithm import _prefer_curtailed_charge_absorb
from core.bess.tests.helpers import run_scenario_realized
from core.bess.tests.unit.test_scenarios import load_test_scenario

# Candidate tuple: (value, power, next_soe, new_cost_basis, reward, grid_imported)
HOLD = (10.0, 0.0, 12.0, 0.035, 0.0, 0.0)  # SOLAR_EXPORT bypass: SOE flat
ABSORB = (10.0, 0.0, 12.6, 0.035, 0.0, 0.0)  # IDLE: passively absorbs surplus
CHARGE_IMPORT = (9.999, 5.0, 13.25, 0.05, -0.1, 0.65)  # full rate, pulls grid
DISCHARGE = (9.99, -1.0, 11.7, 0.035, 0.2, 0.0)


def test_exact_tie_swaps_hold_to_highest_soe_absorb():
    candidates = [ABSORB, HOLD, CHARGE_IMPORT, DISCHARGE]
    # HOLD won the argmax on float noise; ABSORB is exactly tied -> swap.
    assert _prefer_curtailed_charge_absorb(candidates, 1, epsilon=0.01) == 0


def test_never_swaps_into_grid_importing_charge():
    # CHARGE_IMPORT stores the most but pays the buy price for it -- the
    # morning failure mode (#269 comment: Meter 1 + charge 100% pulling
    # ~0.9 kW grid import during Storage). Never preferred over surplus-only.
    candidates = [HOLD, CHARGE_IMPORT]
    assert _prefer_curtailed_charge_absorb(candidates, 0, epsilon=0.01) == 0


def test_decisive_hold_margin_is_never_swapped():
    low_absorb = (9.98, 0.0, 12.6, 0.035, 0.0, 0.0)
    candidates = [HOLD, low_absorb]
    # 0.02 behind with epsilon 0.01: the hold is deliberate arbitrage.
    assert _prefer_curtailed_charge_absorb(candidates, 0, epsilon=0.01) == 0


def test_discharge_winner_is_untouched():
    # A #466 load-covering swap (or genuine discharge argmax) must survive.
    candidates = [ABSORB, DISCHARGE]
    assert _prefer_curtailed_charge_absorb(candidates, 1, epsilon=0.01) == 1


def test_zero_epsilon_is_a_no_op():
    candidates = [ABSORB, HOLD]
    assert _prefer_curtailed_charge_absorb(candidates, 1, epsilon=0.0) == 1


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

    # R == P: the charge-early plan must execute faithfully through the
    # inverter simulator, not just claim a number. Assert against the
    # corpus-wide pin (single source of truth) rather than a bare
    # tolerance -- this fixture's gap (+0.0490) sits within 0.001 of the
    # generic 0.05 budget, so a bare `< 0.05` would fail with a
    # misleading "diverged beyond tolerance" message on any tiny drift
    # the pin table is designed to track explicitly.
    from core.bess.tests.integration.test_plan_faithfulness import (
        GAP_PIN_TOLERANCE_SEK,
        PLAN_EXECUTION_GAP_SEK,
    )

    gap = realized_cost - planned_cost
    pinned = PLAN_EXECUTION_GAP_SEK[SCENARIO]
    assert abs(gap - pinned) <= GAP_PIN_TOLERANCE_SEK, (
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
