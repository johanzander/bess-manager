"""Issue #388: the plan-faithfulness simulator's `_map_rates` is a hand-
maintained mirror of `InverterController._map_intent_to_rates` that has no
`shadow_price` parameter and never calls `intra_period_discharge_gate` --
so `run_scenario_realized`/`verify_plan_faithfulness` cannot exercise the
shadow-price intra-period discharge gate (SOLAR_EXPORT/SOLAR_STORAGE since
#187/#319, extended to LOAD_SUPPORT by #385) at all.

These tests use a real DP-optimized schedule (`optimize_battery_schedule`),
not a hand-built period/decision, so the gate branch is genuinely reachable
by the same code path `run_scenario_realized` drives -- per
docs/agents/testing.md's plan-faithfulness requirement for control/rate-
mapping changes.
"""

from core.bess.battery_system_manager import intra_period_discharge_gate
from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.simulation.inverter_simulator import (
    ControlCommand,
    derive_control_command,
    mode_to_power,
)
from core.bess.tests.helpers import (
    _scenario_inputs,
    make_battery_settings,
    run_scenario_realized,
)

N = 24
BUY_PRICE = (
    [0.8] * 6 + [1.0] * 4 + [1.6] * 3 + [2.4] * 2 + [1.6] * 3 + [1.0] * 4 + [0.8] * 2
)
HOME_CONSUMPTION = [1.5] * N
SOLAR_PRODUCTION = [0.0] * N
LOAD_SUPPORT_PERIOD = 10  # DP plans a partial (14%) LOAD_SUPPORT discharge here


def _battery(initial_soe: float) -> dict:
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


def _optimize():
    scenario = {
        "base_prices": BUY_PRICE,
        "home_consumption": HOME_CONSUMPTION,
        "solar_production": SOLAR_PRODUCTION,
        "battery": _battery(initial_soe=15.0),
    }
    inp = _scenario_inputs(scenario)
    result = optimize_battery_schedule(**inp)
    return inp, result


def test_load_support_simulator_opens_gate_on_favorable_shadow_price():
    """A real DP-optimized LOAD_SUPPORT period whose shadow price makes
    covering the full deficit now favorable (buy_price * eff_d >= shadow_price)
    must reach the production `intra_period_discharge_gate` and raise the
    discharge ceiling to 100%, exactly as `battery_system_manager.py`'s
    `_apply_period_schedule` does -- not stay capped at the DP's plan-scaled
    baseline (14% here), which is all the un-fixed simulator can produce."""
    inp, result = _optimize()
    dt = inp["period_duration_hours"]
    settings = inp["battery_settings"]
    buy_price = inp["buy_price"]

    pd = result.period_data[LOAD_SUPPORT_PERIOD]
    assert pd.decision.strategic_intent == "LOAD_SUPPORT", (
        "scenario sanity check failed -- expected a LOAD_SUPPORT period at "
        f"index {LOAD_SUPPORT_PERIOD}, got {pd.decision.strategic_intent}"
    )
    expected_gate = intra_period_discharge_gate(
        buy_price[LOAD_SUPPORT_PERIOD],
        pd.decision.shadow_price,
        settings.efficiency_discharge,
    )
    assert expected_gate == 100, (
        "scenario sanity check failed -- expected the shadow-price gate to "
        f"be favorable at period {LOAD_SUPPORT_PERIOD}"
    )

    cmd = derive_control_command(
        pd.decision.strategic_intent,
        pd.decision.battery_action / dt,
        settings,
        shadow_price=pd.decision.shadow_price,
        buy_price=buy_price[LOAD_SUPPORT_PERIOD],
    )
    assert cmd.discharge_rate_pct == 100, (
        f"simulator did not model the shadow-price gate: got "
        f"discharge_rate_pct={cmd.discharge_rate_pct}, expected 100 (production's "
        f"intra_period_discharge_gate would raise the ceiling here)"
    )


def test_run_scenario_realized_wires_shadow_price_gate_by_default():
    """`run_scenario_realized` (the helper every plan-faithfulness scenario
    test uses) must pass shadow_price/buy_price through by default -- not
    just when a test opts in by calling derive_control_command directly.

    On this scenario, opening the gate lets the battery cover the full
    period-10 deficit instead of leaving an avoidable grid import the DP's
    plan already priced in, so realized cost must land at or below the
    planned cost -- strictly below here, not just within the usual
    grid-resolution tolerance, because the gate captures value the DP's own
    15-min-average plan didn't (and couldn't) model."""
    scenario = {
        "base_prices": BUY_PRICE,
        "home_consumption": HOME_CONSUMPTION,
        "solar_production": SOLAR_PRODUCTION,
        "battery": _battery(initial_soe=15.0),
    }
    result, realized_cost = run_scenario_realized(scenario)
    planned_cost = result.economic_summary.battery_solar_cost
    assert realized_cost < planned_cost - 0.05, (
        f"R={realized_cost:.4f} not below P={planned_cost:.4f} by the expected "
        f"gate-captured margin -- run_scenario_realized is not wiring "
        f"shadow_price/buy_price into derive_control_command"
    )


def test_solar_export_gate_open_with_zero_deficit_leaves_battery_untouched():
    """#313 regression, surfaced by the gate wiring: SOLAR_EXPORT always plans
    charge_rate_pct=0 (blocks passive solar->battery charging so solar bypasses
    to grid -- #313's `mode_to_power` returns `None`, not `0.0`, to signal
    "battery held exactly unchanged" instead of "passively charge").

    Opening the shadow-price gate raises discharge_rate_pct to 100 for
    SOLAR_EXPORT too. When solar >= home (deficit == 0, the normal SOLAR_EXPORT
    case), `mode_to_power`'s `discharge_rate_pct > 0` branch must NOT shadow the
    `charge_rate_pct == 0` bypass below it -- a naive `deficit = max(0, home -
    solar) == 0.0` there returns `-0.0/dt` (a float), not `None`, which
    `simulate()` treats as passive IDLE charging: the opposite of #313's
    intent, and it silently fills the battery from solar that should have been
    exported."""
    settings = make_battery_settings()
    cmd = ControlCommand(
        "load_first", discharge_rate_pct=100, grid_charge=False, charge_rate_pct=0
    )

    power = mode_to_power(cmd, solar=5.0, home=1.0, soe=5.0, settings=settings, dt=0.25)

    assert power is None, (
        f"gate-open SOLAR_EXPORT with solar >= home must leave the battery "
        f"untouched (None), got {power!r} -- the deficit-covering branch is "
        f"shadowing the #313 charge_rate_pct==0 bypass"
    )
