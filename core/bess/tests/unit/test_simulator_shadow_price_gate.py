"""Issue #388: the plan-faithfulness simulator's `_map_rates` is a hand-
maintained mirror of `InverterController._map_intent_to_rates` that has no
`shadow_price` parameter and never calls `intra_period_discharge_gate` --
so `run_scenario_realized`/`verify_plan_faithfulness` cannot exercise the
shadow-price intra-period discharge gate (SOLAR_EXPORT/SOLAR_STORAGE since
#187/#319) at all.

Production applies the gate to LOAD_SUPPORT as well (#384/#385, reverted by
#393, re-landed by #520 -- see test_load_support_discharge_gate.py). This
simulator deliberately does NOT mirror that, and these tests pin the
divergence rather than the production behaviour: the gate is a sub-period
ceiling, and a 15-min point-forecast simulator has no sub-period excess load
to cover, so mirroring it here would model only the gate's cost and never its
benefit. See `inverter_simulator._map_rates` for the measured size of that
one-sided cost.

These tests use a real DP-optimized schedule (`optimize_battery_schedule`),
not a hand-built period/decision, so the gate branch is genuinely reachable
by the same code path `run_scenario_realized` drives -- per
docs/agents/testing.md's plan-faithfulness requirement for control/rate-
mapping changes.
"""

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.execution_model import intra_period_discharge_gate
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


def test_load_support_simulator_does_not_open_gate_on_favorable_shadow_price():
    """A real DP-optimized LOAD_SUPPORT period whose shadow price makes the
    gate condition favorable (buy_price >= shadow_price, #683) must NOT
    raise the discharge ceiling above the DP's plan-scaled baseline *in the
    simulator* -- deliberately unlike production, which does raise it (#520).
    The simulator stays plan-faithful so the corpus keeps measuring the plan,
    not the sub-period behaviour it cannot represent."""
    inp, result = _optimize()
    dt = inp["period_duration_hours"]
    settings = inp["battery_settings"]
    buy_price = inp["buy_price"]

    pd = result.period_data[LOAD_SUPPORT_PERIOD]
    assert pd.decision.strategic_intent == "LOAD_SUPPORT", (
        "scenario sanity check failed -- expected a LOAD_SUPPORT period at "
        f"index {LOAD_SUPPORT_PERIOD}, got {pd.decision.strategic_intent}"
    )
    assert (
        intra_period_discharge_gate(pd.decision.intra_period_discharge_allowed) == 100
    ), (
        "scenario sanity check failed -- expected the DP to authorize "
        f"sub-period discharge at period {LOAD_SUPPORT_PERIOD} (the point of "
        "this test is that an authorized period is still ignored for "
        "LOAD_SUPPORT)"
    )
    # #683: shadow_price is per kWh delivered, so this mirrors the DP's rule
    # exactly. The old `* efficiency_discharge` form was strictly tighter and
    # would have reported an uncomputed shadow price for a computed one.
    assert buy_price[LOAD_SUPPORT_PERIOD] >= pd.decision.shadow_price, (
        "scenario sanity check failed -- the DP's authorization here must "
        "come from a genuinely favorable buy-vs-hold comparison, not from an "
        "uncomputed shadow price (#526)"
    )

    cmd = derive_control_command(
        pd.decision.strategic_intent,
        pd.decision.battery_action / dt,
        settings,
        intra_period_discharge_allowed=pd.decision.intra_period_discharge_allowed,
    )
    baseline = min(
        100,
        max(
            0,
            round(
                abs(pd.decision.battery_action / dt)
                / settings.max_discharge_power_kw
                * 100
            ),
        ),
    )
    assert cmd.discharge_rate_pct == baseline, (
        f"LOAD_SUPPORT must stay at its plan-scaled baseline ({baseline}%) "
        f"regardless of shadow_price, got discharge_rate_pct="
        f"{cmd.discharge_rate_pct} -- the gate is deliberately not mirrored "
        "into the simulator for LOAD_SUPPORT (#520)"
    )


def test_run_scenario_realized_stays_plan_faithful_for_load_support():
    """`run_scenario_realized` (the helper every plan-faithfulness scenario
    test uses) must pass shadow_price/buy_price through by default -- not
    just when a test opts in by calling derive_control_command directly --
    but for LOAD_SUPPORT that must be a no-op in the simulator (#520): the
    gate is not consulted here, so realized cost tracks the plan within the
    usual grid-resolution tolerance, not below it."""
    scenario = {
        "base_prices": BUY_PRICE,
        "home_consumption": HOME_CONSUMPTION,
        "solar_production": SOLAR_PRODUCTION,
        "battery": _battery(initial_soe=15.0),
    }
    result, realized_cost = run_scenario_realized(scenario)
    planned_cost = result.economic_summary.battery_solar_cost
    assert abs(realized_cost - planned_cost) < 0.05, (
        f"R={realized_cost:.4f} vs P={planned_cost:.4f} diverged beyond the "
        "usual grid-resolution tolerance -- LOAD_SUPPORT stays plan-faithful "
        "in the simulator, which does not mirror the gate (#520)"
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
