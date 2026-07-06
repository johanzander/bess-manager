"""Tests for the removed discharge profitability floor and the #240
flow-accounting fix, per docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md.
"""

import pytest

from core.bess.dp_battery_algorithm import _compute_reward, _create_idle_schedule, optimize_battery_schedule
from core.bess.tests.helpers import make_battery_settings
from core.bess.tests.unit.test_scenarios import build_scenario_inputs, get_all_scenario_files


def test_discharge_no_longer_blocked_by_cost_basis_floor():
    """The old cost_basis profitability floor (removed) used to veto a
    discharge outright by returning -inf whenever its value didn't clear a
    historical average cost -- even though IDLE, competing in the same
    max() in _run_dynamic_programming, already makes that comparison
    correctly via the forward-looking value function. _compute_reward must
    now always return a finite reward for a physically valid discharge."""
    settings = make_battery_settings()
    power = -1.0
    next_soe = 5.0 - (abs(power) * 1.0 / settings.efficiency_discharge)
    reward, _ = _compute_reward(
        power=power,
        soe=5.0,
        next_soe=next_soe,
        period=0,
        home_consumption=0.5,
        battery_settings=settings,
        dt=1.0,
        buy_price=[0.6],
        sell_price=[0.5],
        solar_production=0.0,
        cost_basis=2.0,  # old floor would have blocked this: 2.0 >> ~0.57
    )
    assert reward != float(
        "-inf"
    ), "discharge was vetoed by a profitability floor that no longer exists"


def test_small_discharge_overshoot_not_credited_as_export():
    """#240: load-first hardware self-throttles -- a discharge that
    overshoots home_consumption by less than the BATTERY_EXPORT
    classification threshold (0.1 kWh) never actually reaches the grid, so
    it must not be credited as export revenue."""
    settings = make_battery_settings()
    dt = 1.0
    home_consumption = 1.0
    power = -1.05  # discharges 1.05 kWh -- 0.05 kWh over consumption
    next_soe = 5.0 - (abs(power) * dt / settings.efficiency_discharge)
    reward, _ = _compute_reward(
        power=power,
        soe=5.0,
        next_soe=next_soe,
        period=0,
        home_consumption=home_consumption,
        battery_settings=settings,
        dt=dt,
        buy_price=[1.0],
        sell_price=[1.0],
        solar_production=0.0,
        cost_basis=0.1,
    )
    # No import (fully covered) and no export credit for the 0.05 kWh
    # overshoot: net cost should be exactly zero, not a phantom profit.
    assert reward == pytest.approx(
        0.0, abs=1e-9
    ), f"expected zero net cost (no import, no phantom export credit), got {reward}"


def test_large_discharge_overshoot_still_credited_as_export():
    """A discharge that overshoots home_consumption by 0.1 kWh or more is a
    genuine deliberate export (BATTERY_EXPORT), not self-throttled
    load-following -- it must still be credited as export revenue."""
    settings = make_battery_settings()
    dt = 1.0
    home_consumption = 1.0
    power = -2.0  # discharges 2.0 kWh -- 1.0 kWh over consumption
    next_soe = 5.0 - (abs(power) * dt / settings.efficiency_discharge)
    reward, _ = _compute_reward(
        power=power,
        soe=5.0,
        next_soe=next_soe,
        period=0,
        home_consumption=home_consumption,
        battery_settings=settings,
        dt=dt,
        buy_price=[1.0],
        sell_price=[0.8],
        solar_production=0.0,
        cost_basis=0.1,
    )
    # 1.0 kWh exported at sell_price=0.8, no import, no wear on discharge.
    assert reward == pytest.approx(0.8, abs=1e-9)


def test_run_dynamic_programming_returns_one_value():
    """policy is no longer used by any caller once Step 2 recomputes actions
    directly from V -- _run_dynamic_programming returns V only."""
    from core.bess.dp_battery_algorithm import _run_dynamic_programming

    settings = make_battery_settings()
    result = _run_dynamic_programming(
        horizon=3,
        buy_price=[1.0, 1.0, 1.0],
        sell_price=[0.8, 0.8, 0.8],
        home_consumption=[0.5, 0.5, 0.5],
        battery_settings=settings,
        dt=1.0,
        solar_production=[0.0, 0.0, 0.0],
        initial_soe=5.0,
    )
    import numpy as np

    assert isinstance(
        result, np.ndarray
    ), f"expected a bare V array, got {type(result)}"


def test_optimizer_ignores_min_action_profit_threshold():
    """The whole-day rejection gate is gone -- setting an absurdly high
    min_action_profit_threshold must no longer force an all-IDLE fallback
    when the DP found a genuinely better schedule."""
    from core.bess.dp_battery_algorithm import optimize_battery_schedule

    settings = make_battery_settings(min_action_profit_threshold=1_000_000.0)
    buy_price = [0.3, 0.3, 3.0, 3.0] * 6
    sell_price = [0.25, 0.25, 2.8, 2.8] * 6
    home_consumption = [1.0] * 24
    solar_production = [0.0] * 24

    result = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=5.0,
        battery_settings=settings,
        period_duration_hours=1.0,
    )
    # A real arbitrage opportunity (0.3 -> 3.0 spread) should be captured
    # despite the absurd threshold -- the old gate would have rejected this
    # to an all-IDLE schedule.
    assert result.economic_summary.grid_to_battery_solar_savings > 0.0, (
        "optimizer fell back to all-IDLE despite a genuine arbitrage "
        "opportunity -- min_action_profit_threshold should have no effect"
    )


def test_small_export_only_discharge_classified_as_battery_export():
    """A discharge with zero home-deficit coverage and a small (but
    meaningfully nonzero) export must be classified BATTERY_EXPORT, not
    LOAD_SUPPORT -- LOAD_SUPPORT maps to load_first, which physically cannot
    export at all (core/bess/simulation/inverter_simulator.py's mode_to_power
    caps load_first delivery at max(0, home-solar), i.e. zero when solar
    already covers home). Mislabeling this as LOAD_SUPPORT makes the plan
    unrealizable: real/simulated hardware delivers zero instead of the
    planned export, and that zero triggers passive solar charging instead
    (_state_transition's IDLE branch), a much larger, unplanned action.
    Regression for the R == P failures traced on
    realworld_2026_04_27_211212 period 42 during Task 8's fixture
    regeneration."""
    from core.bess.decision_intelligence import classify_strategic_intent
    from core.bess.models import EnergyData

    energy_data = EnergyData(
        solar_production=3.5,
        home_consumption=0.2,
        battery_charged=0.0,
        battery_discharged=0.05,
        grid_imported=0.0,
        grid_exported=3.35,
        battery_soe_start=7.68,
        battery_soe_end=7.63,
    )
    intent = classify_strategic_intent(power=-0.2, energy_data=energy_data)
    assert intent == "BATTERY_EXPORT", (
        f"expected BATTERY_EXPORT for a 100%-export discharge, got {intent}"
    )


pytestmark = pytest.mark.slow


@pytest.mark.parametrize("scenario_name", get_all_scenario_files())
def test_dp_output_never_worse_than_all_idle_schedule(scenario_name):
    """The numerical safety net in optimize_battery_schedule always returns
    whichever of (DP schedule, all-IDLE schedule) is cheaper -- so the
    optimizer's returned cost must never exceed the all-IDLE baseline,
    across every pinned fixture. This is the property the whole redesign
    rests on (docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md)."""
    scenario, battery_settings, buy_prices, sell_prices, dt = build_scenario_inputs(
        scenario_name
    )
    home_consumption = scenario["home_consumption"]
    solar_production = scenario["solar_production"]
    battery = scenario["battery"]
    horizon = len(buy_prices)

    result = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=battery["initial_soe"],
        battery_settings=battery_settings,
        period_duration_hours=dt,
    )
    idle_result = _create_idle_schedule(
        horizon=horizon,
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=battery["initial_soe"],
        battery_settings=battery_settings,
        dt=dt,
    )
    assert result.economic_summary.battery_solar_cost <= (
        idle_result.economic_summary.battery_solar_cost + 1e-6
    ), (
        f"{scenario_name}: DP schedule cost "
        f"{result.economic_summary.battery_solar_cost:.4f} exceeds all-IDLE "
        f"cost {idle_result.economic_summary.battery_solar_cost:.4f}"
    )
