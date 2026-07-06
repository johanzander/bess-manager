# core/bess/tests/integration/test_plan_faithfulness.py

import pytest

from core.bess.simulation.verification import verify_plan_faithfulness
from core.bess.tests.helpers import make_battery_settings


def _controlled_scenario():
    """A scenario whose optimal plan uses only faithfully-executable actions:
    night grid-charge at a clear low price, evening discharge-to-grid at a clear
    high price, no fractional solar-storage. dt = 1.0h for simple arithmetic."""
    n = 6
    buy = [0.5, 0.5, 2.0, 2.0, 1.0, 1.0]
    sell = [0.4, 0.4, 1.8, 1.8, 0.9, 0.9]
    solar = [0.0] * n
    home = [0.5] * n
    return buy, sell, solar, home


def test_realized_equals_planned_on_controlled_scenario():
    bs = make_battery_settings()
    buy, sell, solar, home = _controlled_scenario()
    planned_cost, realized_cost, per_period = verify_plan_faithfulness(
        buy_price=buy,
        sell_price=sell,
        solar=solar,
        home=home,
        initial_soe=3.0,
        settings=bs,
        dt=1.0,
    )
    # cent-exact: faithful control reproduces the plan
    assert round(realized_cost, 2) == round(
        planned_cost, 2
    ), f"R={realized_cost} != P={planned_cost}; per-period deltas: {per_period}"


def test_identical_command_sequences_have_zero_delta():
    from core.bess.simulation.inverter_simulator import ControlCommand
    from core.bess.simulation.verification import ab_compare

    bs = make_battery_settings()
    n = 6
    buy = [1.0] * n
    sell = [0.8] * n
    solar = [0.5] * n
    home = [0.3] * n
    base = [ControlCommand("load_first", 0, False)] * n
    delta = ab_compare(
        base, base, solar, home, buy, sell, initial_soe=5.0, settings=bs, dt=1.0
    )
    assert delta == 0.0


def test_solar_storage_mode_stores_all_surplus():
    """IDLE/SOLAR_STORAGE: load_first + no discharge stores surplus via passive charging.

    After the grid-charging-during-surplus fix, mode_to_power returns 0.0 for
    load_first + no discharge (regardless of surplus). _state_transition's IDLE branch
    then performs passive solar charging (solar fills battery, no grid draw). The old
    code returned surplus/dt which went through the STORE branch; that used to be
    equivalent (grid_to_battery was gated to 0), but after removing the surplus gate
    the STORE branch would add grid top-up — incorrect for load_first hardware.
    """
    from core.bess.simulation.inverter_simulator import (
        ControlCommand,
        mode_to_power,
        simulate,
    )

    bs = make_battery_settings(max_charge_power_kw=10.0)
    cmd = ControlCommand("load_first", discharge_rate_pct=0, grid_charge=False)

    # mode_to_power returns 0.0; _state_transition IDLE branch does the solar charging.
    assert mode_to_power(cmd, solar=5.0, home=0.5, soe=5.0, settings=bs, dt=1.0) == 0.0

    sim = simulate(
        [cmd],
        solar_production=[5.0],
        home_consumption=[0.5],
        buy_price=[1.0],
        sell_price=[1.0],
        initial_soe=5.0,
        settings=bs,
        dt=1.0,
    )
    stored = sim.period_data[0].energy.battery_soe_end - 5.0
    assert (
        stored > 4.0
    ), f"load_first should store ~all 4.5 kWh surplus via IDLE passive charging, got {stored:.2f}"


def test_forecast_robustness_more_solar_than_planned():
    """Task 7 / #145: optimize on a solar FORECAST, then execute against HIGHER
    actual solar. The binary store/export model must be forecast-robust — bonus
    solar is captured/exported, never wasted — so realized is at least as good as
    the forecast plan (lower or equal cost)."""
    from core.bess.simulation.verification import realized_under_solar_error

    bs = make_battery_settings()
    n = 6
    buy = [1.0, 1.0, 2.0, 2.0, 1.0, 1.0]
    sell = [0.8, 0.8, 1.8, 1.8, 0.9, 0.9]
    home = [0.3] * n
    forecast_solar = [1.0] * n
    actual_solar = [2.0] * n  # reality beats the forecast

    planned, realized = realized_under_solar_error(
        forecast_solar=forecast_solar,
        actual_solar=actual_solar,
        buy_price=buy,
        sell_price=sell,
        home=home,
        initial_soe=5.0,
        settings=bs,
        dt=1.0,
    )
    # more actual solar than forecast → realized cost no worse than planned (bonus
    # solar exported/stored, no phantom export booked against the forecast)
    assert (
        realized <= planned + 1e-6
    ), f"forecast not robust: realized {realized} > planned {planned}"


def test_scenarios_are_plan_faithful_realized_equals_planned():
    """Scenarios verify R (realized), not just P (plan): executing the optimizer's
    plan through the inverter simulator must reproduce the planned economics to
    within the DP's SoE-grid resolution. A larger gap is a control-fidelity
    finding (#145).

    The optimizer models power=0 as passive solar charging (matching load_first
    hardware behavior), so solar scenarios are included and must pass.
    """
    from core.bess.tests.helpers import run_scenario_realized

    scenarios = {
        "grid_charge_arbitrage": {
            "base_prices": [0.5, 0.5, 2.0, 2.0, 1.0, 1.0],
            "home_consumption": [0.5] * 6,
            "solar_production": [0.0] * 6,
            "battery": _battery(initial_soe=3.0),
        },
        "solar_day": {
            "base_prices": [0.5, 0.5, 1.0, 1.0, 0.8, 0.8],
            "home_consumption": [0.5] * 6,
            "solar_production": [1.5, 1.8, 1.9, 1.7, 0.5, 0.0],
            "battery": _battery(initial_soe=5.0),
        },
    }
    # Tolerance reflects the DP's 0.1 kWh SoE-grid resolution: the plan trajectory
    # is reconstructed continuously, but the policy LOOKUP still snaps SoE to the
    # grid, leaving a sub-öre-per-period residual on solar-storage days. The
    # structural mismodels (phantom export, store/export collisions) are gone — a
    # gap beyond this band would be a real finding.
    GRID_RESOLUTION_TOLERANCE = 0.10  # SEK, for these short scenarios
    for name, sc in scenarios.items():
        result, realized = run_scenario_realized(sc)
        planned = result.economic_summary.battery_solar_cost
        assert abs(realized - planned) <= GRID_RESOLUTION_TOLERANCE, (
            f"{name}: R={realized:.4f} != P={planned:.4f} "
            f"(gap {realized - planned:+.4f} exceeds grid-resolution tolerance)"
        )


def _battery(initial_soe):
    return {
        "max_soe_kwh": 20.0,
        "min_soe_kwh": 2.2,
        "max_charge_power_kw": 10.0,
        "max_discharge_power_kw": 10.0,
        "efficiency_charge": 0.97,
        "efficiency_discharge": 0.95,
        "cycle_cost_per_kwh": 0.40,
        "initial_soe": initial_soe,
    }


def test_load_support_self_throttles_discretization_overshoot():
    """#240 regression: load-first hardware never exports a discharge that
    overshoots home_consumption -- it self-throttles to the actual deficit,
    regardless of what a coarser discretized plan might have assumed. This
    locks in the physical behavior the #240 reward-model fix
    (core/bess/dp_battery_algorithm.py's _compute_reward) now assumes:
    before that fix, the plan credited export revenue for energy that was
    never actually exported, breaking R == P for these periods -- a case
    the existing hand-crafted plan-faithfulness scenarios were deliberately
    designed to avoid (see their own docstrings), so nothing else covers it.
    """
    from core.bess.simulation.inverter_simulator import ControlCommand, simulate

    bs = make_battery_settings()
    home = 1.15
    solar = 0.0
    cmd = ControlCommand("load_first", discharge_rate_pct=100, grid_charge=False)
    sim = simulate(
        [cmd],
        solar_production=[solar],
        home_consumption=[home],
        buy_price=[1.0],
        sell_price=[1.0],
        initial_soe=5.0,
        settings=bs,
        dt=1.0,
    )
    assert sim.period_data[0].energy.grid_exported == pytest.approx(0.0, abs=1e-9), (
        "load_first should never export -- it self-throttles to the actual "
        "home deficit, matching the #240-fixed reward model's assumption"
    )
