"""Per-period minimum grid export: "constrain, don't raise".

The optimizer can be told a period must export at least some energy (the
Octopus Power Down export pulse, see
docs/superpowers/specs/2026-09-13-octopus-power-down-export-pulse-design.md).
It is a constraint on flows, filtered inside candidate selection exactly like
the #429 import cap: the plan exports the target where it can, exports what it
can where it cannot, and never becomes infeasible.
"""

import dataclasses
import json
from pathlib import Path

import pytest

from core.bess.action_selector import PeriodInputs, SelectionResult, select_action
from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.tests.helpers import (
    _scenario_inputs,
    make_battery_settings,
    run_scenario_realized,
)

DT = 0.25
TARGET_KWH = 0.25
DATA_DIR = Path(__file__).parent / "data"

# Stored energy is worth more than it sells for and less than it costs to
# import, so left alone the selector covers the house from the battery and
# exports nothing -- which is what makes a target observable.
STORED_ENERGY_VALUE = 1.0


def _select(
    soe: float,
    *,
    min_grid_export_kwh: float | None,
    home: float = 0.3,
    solar: float = 0.0,
) -> SelectionResult:
    settings = make_battery_settings()
    return select_action(
        soe=soe,
        t=0,
        cost_basis=0.0,
        eval_V=lambda next_soe: STORED_ENERGY_VALUE * next_soe,
        eval_value_slope=lambda _next_soe: STORED_ENERGY_VALUE,
        period_inputs=PeriodInputs(
            buy_price=[1.5],
            sell_price=[0.1],
            home_consumption=[home],
            solar_production=[solar],
            dt=DT,
            min_grid_export_kwh=min_grid_export_kwh,
        ),
        battery_settings=settings,
    )


def test_selector_exports_the_target_from_a_full_battery() -> None:
    settings = make_battery_settings()
    unconstrained = _select(settings.max_soe_kwh, min_grid_export_kwh=None)
    assert (
        unconstrained.chosen.flows.grid_exported < TARGET_KWH
    ), "fixture no longer discriminates: the unconstrained choice already exports"

    constrained = _select(settings.max_soe_kwh, min_grid_export_kwh=TARGET_KWH)

    assert constrained.chosen.flows.grid_exported >= TARGET_KWH
    assert all(c.flows.grid_exported >= TARGET_KWH for c in constrained.candidates)


def test_selector_exports_what_it_can_from_an_empty_battery() -> None:
    """At the floor with no solar nothing can export, so the target shrinks to
    the best achievable export (zero) instead of emptying the candidate set."""
    settings = make_battery_settings()

    constrained = _select(settings.min_soe_kwh, min_grid_export_kwh=TARGET_KWH)
    unconstrained = _select(settings.min_soe_kwh, min_grid_export_kwh=None)

    assert constrained.chosen.flows.grid_exported == 0.0
    assert constrained.candidates == unconstrained.candidates
    assert constrained.chosen == unconstrained.chosen


def test_a_zero_target_leaves_the_selection_untouched() -> None:
    settings = make_battery_settings()
    soe = (settings.min_soe_kwh + settings.max_soe_kwh) / 2

    assert _select(soe, min_grid_export_kwh=0.0, solar=0.6) == _select(
        soe, min_grid_export_kwh=None, solar=0.6
    )


EVENING_PERIODS = 8
TARGET_PERIOD = 4
EVENING_BUY_PRICE = 2.0
EVENING_SELL_PRICE = 0.1

# The battery holds exactly the evening's load (4 kWh above its floor) and
# export is worth far less than import: unconstrained, nothing exports. Every
# kWh the pulse sends out is bought back later at the buy price, so the
# constraint's cost shows up in the plan's own cost rather than hiding in the
# terminal value.
EVENING_SCENARIO = {
    "battery": {
        "max_soe_kwh": 10.0,
        "min_soe_kwh": 1.0,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "efficiency_charge": 1.0,
        "efficiency_discharge": 1.0,
        "cycle_cost_per_kwh": 0.0,
        "initial_soe": 5.0,
    },
    "buy_price": [EVENING_BUY_PRICE] * EVENING_PERIODS,
    "sell_price": [EVENING_SELL_PRICE] * EVENING_PERIODS,
    "home_consumption": [0.5] * EVENING_PERIODS,
    "solar_production": [0.0] * EVENING_PERIODS,
    "period_duration_hours": DT,
    "terminal_value_per_kwh": 1.0,
}


def test_optimizer_plans_the_export_target_and_pays_for_it() -> None:
    targets = [0.0] * EVENING_PERIODS
    targets[TARGET_PERIOD] = TARGET_KWH
    constrained_scenario = {
        **EVENING_SCENARIO,
        "min_grid_export_kwh_per_period": targets,
    }

    unconstrained, unconstrained_realized = run_scenario_realized(EVENING_SCENARIO)
    constrained, constrained_realized = run_scenario_realized(constrained_scenario)

    assert (
        unconstrained.period_data[TARGET_PERIOD].energy.grid_exported < TARGET_KWH
    ), "fixture no longer discriminates: the unconstrained plan already exports"

    assert constrained.period_data[TARGET_PERIOD].energy.grid_exported >= TARGET_KWH
    assert constrained_realized == pytest.approx(
        constrained.economic_summary.battery_solar_cost, abs=0.01
    ), "Plan is not faithfully executable (R != P)"
    assert unconstrained_realized == pytest.approx(
        unconstrained.economic_summary.battery_solar_cost, abs=0.01
    )
    # The pulse costs something, and no more than re-buying what it sold.
    extra_cost = (
        constrained.economic_summary.battery_solar_cost
        - unconstrained.economic_summary.battery_solar_cost
    )
    exported = constrained.period_data[TARGET_PERIOD].energy.grid_exported
    assert extra_cost > 0.0
    assert extra_cost <= exported * (EVENING_BUY_PRICE - EVENING_SELL_PRICE) + 1e-9


def test_optimizer_rejects_a_target_list_of_the_wrong_length() -> None:
    inputs = _scenario_inputs(EVENING_SCENARIO)

    with pytest.raises(ValueError, match="min_grid_export_kwh_per_period"):
        optimize_battery_schedule(
            **inputs, min_grid_export_kwh_per_period=[0.0] * (EVENING_PERIODS - 1)
        )


# One fixture that re-solves tie windows with the PWL DP, one with an inverter
# AC cap and the SOLAR_EXPORT bypass in play, one exporting solar surplus.
ZERO_TARGET_FIXTURES = [
    "realworld_2026_04_22_202249",
    "synthetic_clear_sky_ac_clipping",
    "historical_2025_06_02_high_solar_export",
]


@pytest.mark.parametrize("name", ZERO_TARGET_FIXTURES)
def test_all_zero_targets_plan_exactly_what_no_targets_plan(name: str) -> None:
    with open(DATA_DIR / f"{name}.json") as f:
        inputs = _scenario_inputs(json.load(f))
    horizon = len(inputs["buy_price"])

    baseline = optimize_battery_schedule(**inputs)
    zero_targets = optimize_battery_schedule(
        **inputs, min_grid_export_kwh_per_period=[0.0] * horizon
    )

    assert zero_targets.economic_summary is not None
    assert baseline.economic_summary is not None
    assert [dataclasses.asdict(p) for p in zero_targets.period_data] == [
        dataclasses.asdict(p) for p in baseline.period_data
    ]
    assert dataclasses.asdict(zero_targets.economic_summary) == dataclasses.asdict(
        baseline.economic_summary
    )
