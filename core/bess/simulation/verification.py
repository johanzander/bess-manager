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
