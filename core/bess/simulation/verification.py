"""Verification harnesses: plan-faithfulness (R == P) and A/B economic gate."""

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.settings import BatterySettings
from core.bess.simulation.inverter_simulator import (
    ControlCommand,
    derive_control_command,
    simulate,
)
from core.bess.terminal_value import (
    curve_from_knee,
    knee_kwh_from_trailing_darkness,
    pv_covers_load,
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
            pd.decision.strategic_intent,
            pd.decision.battery_action / dt,
            settings,
            intra_period_discharge_allowed=pd.decision.intra_period_discharge_allowed,
        )
        for i, pd in enumerate(result.period_data)
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

    Both figures are credited for usable energy left in the battery at horizon end
    using the same terminal valuation production optimizes against
    (`core/bess/terminal_value.py`), otherwise a run that legitimately stores more
    bonus solar than the forecast run — real value carried past the horizon, not
    waste — looks like a loss purely from the horizon cutoff. Sharing the formula
    rather than mirroring it is load-bearing: a hand-cloned copy here would let
    this harness judge plans by a different objective than the one that produced
    them.
    """
    # This harness optimizes and executes one horizon against itself, so it
    # has no forecast for the day after its own boundary -- the precondition
    # `knee_kwh_from_forecast` states. It therefore uses the same documented
    # stand-in the pinned corpus does: the dark stretch immediately *before*
    # the boundary, walked backward. Passing `home`/`forecast_solar` forward
    # from period 0 would scan the wrong end of the array and return a knee of
    # zero on any horizon starting in daylight.
    terminal_curve = curve_from_knee(
        buy_price,
        sell_price,
        knee_kwh_from_trailing_darkness(home, forecast_solar, settings),
        pv_refills=any(
            pv_covers_load(consumption, solar)
            for consumption, solar in zip(home, forecast_solar, strict=True)
        ),
        battery_settings=settings,
    )
    result = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home,
        solar_production=forecast_solar,
        initial_soe=initial_soe,
        battery_settings=settings,
        period_duration_hours=dt,
        terminal_curve=terminal_curve,
    )
    commands = [
        derive_control_command(
            pd.decision.strategic_intent,
            pd.decision.battery_action / dt,
            settings,
            intra_period_discharge_allowed=pd.decision.intra_period_discharge_allowed,
        )
        for i, pd in enumerate(result.period_data)
    ]
    sim = simulate(
        commands, actual_solar, home, buy_price, sell_price, initial_soe, settings, dt
    )

    planned_usable = max(
        0.0, result.period_data[-1].energy.battery_soe_end - settings.min_soe_kwh
    )
    realized_usable = max(
        0.0, sim.period_data[-1].energy.battery_soe_end - settings.min_soe_kwh
    )
    planned_cost = result.economic_summary.battery_solar_cost - terminal_curve.value(
        planned_usable
    )
    realized_cost = sim.realized_cost - terminal_curve.value(realized_usable)
    return planned_cost, realized_cost
