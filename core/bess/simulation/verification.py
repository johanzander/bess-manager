"""Verification harnesses: plan-faithfulness (R == P) and A/B economic gate."""

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.settings import BatterySettings
from core.bess.simulation.inverter_simulator import (
    ControlCommand,
    derive_control_command,
    simulate,
)


def verify_plan_faithfulness(
    buy_price,
    sell_price,
    solar,
    home,
    initial_soe,
    settings: BatterySettings,
    dt: float,
):
    """Run optimizer -> derive commands -> simulate -> compare. Returns
    (planned_cost, realized_cost, per_period_deltas)."""
    result = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home,
        solar_production=solar,
        initial_soe=initial_soe,
        battery_settings=settings,
        period_duration_hours=dt,
    )
    commands = [
        derive_control_command(
            pd.decision.strategic_intent, pd.decision.battery_action / dt, settings
        )
        for pd in result.period_data
    ]
    sim = simulate(
        commands, solar, home, buy_price, sell_price, initial_soe, settings, dt
    )
    planned_cost = result.economic_summary.battery_solar_cost
    realized_cost = sim.realized_cost
    per_period_deltas = [
        round(
            sim.period_data[i].economic.hourly_cost
            - result.period_data[i].economic.hourly_cost,
            4,
        )
        for i in range(len(result.period_data))
    ]
    return planned_cost, realized_cost, per_period_deltas


def ab_compare(
    baseline_commands: list[ControlCommand],
    modified_commands: list[ControlCommand],
    solar,
    home,
    buy_price,
    sell_price,
    initial_soe: float,
    settings: BatterySettings,
    dt: float,
) -> float:
    """Realized-savings delta (modified - baseline) under identical conditions.
    Both run through the same simulator, so simulator error cancels: assert exactly."""
    base = simulate(
        baseline_commands, solar, home, buy_price, sell_price, initial_soe, settings, dt
    )
    mod = simulate(
        modified_commands, solar, home, buy_price, sell_price, initial_soe, settings, dt
    )
    # cost delta; savings delta is the negation. Positive cost delta = modified costs more.
    return mod.realized_cost - base.realized_cost


def realized_under_solar_error(
    forecast_solar,
    actual_solar,
    buy_price,
    sell_price,
    home,
    initial_soe: float,
    settings: BatterySettings,
    dt: float,
) -> tuple[float, float]:
    """Forecast-robustness harness: optimize on the *forecast* solar, then execute
    the derived commands against the *actual* solar.

    Returns ``(planned_cost_on_forecast, realized_cost_on_actual)``. With the binary
    store/export model, bonus solar (actual > forecast) is captured or exported with
    no phantom export booked, so realized should never be worse than the
    forecast plan would have been on the actual day. This is the simulator-verified
    answer to "is the schedule robust to solar forecast error?".
    """
    result = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home,
        solar_production=forecast_solar,
        initial_soe=initial_soe,
        battery_settings=settings,
        period_duration_hours=dt,
    )
    commands = [
        derive_control_command(
            pd.decision.strategic_intent, pd.decision.battery_action / dt, settings
        )
        for pd in result.period_data
    ]
    sim = simulate(
        commands, actual_solar, home, buy_price, sell_price, initial_soe, settings, dt
    )
    return result.economic_summary.battery_solar_cost, sim.realized_cost
