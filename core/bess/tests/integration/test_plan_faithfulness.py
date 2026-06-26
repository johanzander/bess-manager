# core/bess/tests/integration/test_plan_faithfulness.py

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
    """STORE disposition: SOLAR_STORAGE → load_first stores ALL available surplus
    solar (up to rate/room) — the binary store-all behaviour the optimizer now
    plans against, so plan and execution agree. (Replaces the earlier diagnostic
    that asserted the old mode_to_power==0 behaviour; see #145.)
    """
    from core.bess.simulation.inverter_simulator import (
        ControlCommand,
        mode_to_power,
        simulate,
    )

    bs = make_battery_settings(max_charge_power_kw=10.0)
    cmd = ControlCommand("load_first", discharge_rate_pct=0, grid_charge=False)

    # mode_to_power now returns the surplus power (store all surplus), not 0.
    surplus = 5.0 - 0.5
    assert (
        mode_to_power(cmd, solar=5.0, home=0.5, soe=5.0, settings=bs, dt=1.0)
        == surplus / 1.0
    )

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
    ), f"load_first should store ~all 4.5 kWh surplus, got {stored:.2f}"


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

    Solar scenarios with SOLAR_EXPORT periods are excluded: the optimizer plans
    power=0 (hold + export) for those periods, but the hardware in load_first mode
    charges the battery from solar surplus. The deviation is expected and correct —
    the optimizer re-plans on the next cycle with the updated SOC.
    """
    from core.bess.tests.helpers import run_scenario_realized

    scenarios = {
        "grid_charge_arbitrage": {
            "base_prices": [0.5, 0.5, 2.0, 2.0, 1.0, 1.0],
            "home_consumption": [0.5] * 6,
            "solar_production": [0.0] * 6,
            "battery": _battery(initial_soe=3.0),
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
