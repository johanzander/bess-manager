"""Tests for the removed discharge profitability floor and the #240
flow-accounting fix, per docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md.
"""

import pytest

from core.bess.dp_battery_algorithm import _compute_reward
from core.bess.tests.helpers import make_battery_settings


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
