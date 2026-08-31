"""Shared test utilities for battery optimization tests.

Reduces boilerplate across test files by providing:
- run_scenario(): one-liner to run optimization from a scenario dict (plan, P)
- run_scenario_realized(): also executes the plan through the inverter simulator,
  returning the *realized* economics (R) so scenarios can verify the plan is
  faithfully executable (R == P), not just that the plan claims a number.
- Behavioral assertion helpers for strategic intents and physical constraints
"""

from typing import Any

from core.bess.dp_battery_algorithm import (
    _period_flows,
    optimize_battery_schedule,
)
from core.bess.price_manager import MockSource, PriceManager
from core.bess.settings import (
    ADDITIONAL_COSTS,
    MARKUP_RATE,
    TAX_REDUCTION,
    VAT_MULTIPLIER,
    BatterySettings,
    HomeSettings,
)
from core.bess.simulation.inverter_simulator import derive_control_command, simulate
from core.bess.terminal_value import (
    TerminalValueCurve,
    curve_from_knee,
    knee_kwh_from_trailing_darkness,
    pv_covers_load,
)


def _scenario_inputs(scenario: dict):
    """Build optimizer inputs from a scenario dict. Shared by run_scenario and
    run_scenario_realized so plan (P) and realized (R) use identical inputs.

    Two price inputs are supported: a scenario with `buy_price`/`sell_price`
    keys uses those directly -- the exact final prices an optimizer run saw
    (e.g. from a debug log's input_data) -- otherwise `base_prices` is run
    through PriceManager as before, using `price_data` markup config
    (including optional spot_multiplier/export_spot_multiplier) if present.
    """
    battery = scenario["battery"]

    battery_settings = BatterySettings(
        total_capacity=battery["max_soe_kwh"],
        min_soc=(battery["min_soe_kwh"] / battery["max_soe_kwh"]) * 100.0,
        max_soc=100.0,
        max_charge_power_kw=battery["max_charge_power_kw"],
        max_discharge_power_kw=battery["max_discharge_power_kw"],
        efficiency_charge=battery["efficiency_charge"],
        efficiency_discharge=battery["efficiency_discharge"],
        cycle_cost_per_kwh=battery["cycle_cost_per_kwh"],
        inverter_max_ac_power_kw=battery.get("inverter_max_ac_power_kw", 0.0),
        inverter_ac_power_margin=battery.get("inverter_ac_power_margin", 0.0),
        export_curtailment_enabled=battery.get("export_curtailment_enabled", False),
        export_curtailment_price_floor=battery.get(
            "export_curtailment_price_floor", 0.0
        ),
    )

    if "buy_price" in scenario and "sell_price" in scenario:
        buy_price = scenario["buy_price"]
        sell_price = scenario["sell_price"]
    else:
        base_prices = scenario["base_prices"]
        price_data = scenario.get("price_data")

        if price_data:
            markup_rate = price_data["markup_rate"]
            vat_multiplier = price_data["vat_multiplier"]
            additional_costs = price_data["additional_costs"]
            tax_reduction = price_data["tax_reduction"]
            # Optional -- default to PriceManager's own default (1.0, no
            # adjustment) so existing fixtures that don't set these are
            # unaffected.
            spot_multiplier = price_data.get("spot_multiplier", 1.0)
            export_spot_multiplier = price_data.get("export_spot_multiplier", 1.0)
        else:
            markup_rate = MARKUP_RATE
            vat_multiplier = VAT_MULTIPLIER
            additional_costs = ADDITIONAL_COSTS
            tax_reduction = TAX_REDUCTION
            spot_multiplier = 1.0
            export_spot_multiplier = 1.0

        price_manager = PriceManager(
            MockSource(base_prices),
            markup_rate=markup_rate,
            vat_multiplier=vat_multiplier,
            additional_costs=additional_costs,
            tax_reduction=tax_reduction,
            area="SE4",
            spot_multiplier=spot_multiplier,
            export_spot_multiplier=export_spot_multiplier,
        )
        buy_price = price_manager.get_buy_prices(raw_prices=base_prices)
        sell_price = price_manager.get_sell_prices(raw_prices=base_prices)

    inputs = {
        "buy_price": buy_price,
        "sell_price": sell_price,
        "home_consumption": scenario["home_consumption"],
        "solar_production": scenario["solar_production"],
        "initial_soe": battery["initial_soe"],
        "initial_cost_basis": battery.get("initial_cost_basis"),
        "battery_settings": battery_settings,
        "period_duration_hours": scenario.get("period_duration_hours", 1.0),
    }
    if "terminal_value_per_kwh" in scenario:
        # Recorded as two numbers rather than a curve object so the fixture
        # stays readable and diffable, same reason #605 recorded the scalar.
        # A fixture with no knee is the pre-#602 linear row, stated explicitly.
        # All three fields are read back, not two, and `terminal_tail_rate` is
        # indexed rather than `.get`-with-default: a knee-bound scenario missing
        # it must raise here, not silently replay 0.0. That silent default is
        # what pinned the corpus to a curve production never computes -- a
        # different `battery_solar_cost` on 4 of 27 knee-bound fixtures, and
        # invisible to the staleness guard, which compared only head and knee.
        # `terminal_knee_kwh` stays a `.get`: `None` there is the documented
        # encoding of the flat regime, not a defensive default.
        knee = scenario.get("terminal_knee_kwh")
        inputs["terminal_curve"] = (
            TerminalValueCurve(
                head_rate=scenario["terminal_value_per_kwh"],
                knee_kwh=knee,
                tail_rate=scenario["terminal_tail_rate"],
            )
            if knee is not None
            else TerminalValueCurve.flat(scenario["terminal_value_per_kwh"])
        )
    # export_curtailment_active is capability-aware in production (enabled
    # AND the platform supports export-limit control, resolved in
    # battery_system_manager.py) -- fixtures record the resolved flag
    # explicitly rather than this helper inferring it from the enabled
    # setting, so a fixture from a non-curtailing platform replays the
    # same DP path it ran live.
    if battery.get("export_curtailment_active", False):
        inputs["export_curtailment_active"] = True
    if "home" in scenario:
        inputs["home_settings"] = HomeSettings(**scenario["home"])
    return inputs


def scenario_terminal_curve(scenario: dict) -> TerminalValueCurve:
    """Production terminal curve for one scenario (#602).

    Shared by `scripts/capture_scenario_terminal_values.py` (which records the
    result into the fixture) and
    `test_scenarios.py::test_recorded_terminal_values_still_match_the_production_formula`
    (which fails when a recorded value drifts from it). One definition, so the
    guard cannot pass against a stale copy of the rule it enforces.

    A fixture has no tomorrow, so the knee comes from
    `knee_kwh_from_trailing_darkness` -- see that function for the proxy and its
    limits. The rates and the regime split come from `curve_from_knee`, the same
    code production uses, so only the *quantity* is approximated here and never
    the economics.
    """
    inputs = _scenario_inputs(scenario)
    periods_per_day = round(24 / inputs["period_duration_hours"])
    settings = inputs["battery_settings"]
    consumption = inputs["home_consumption"]
    solar = inputs["solar_production"]

    return curve_from_knee(
        inputs["buy_price"],
        inputs["sell_price"][-periods_per_day:],
        knee_kwh_from_trailing_darkness(consumption, solar, settings),
        pv_refills=any(
            pv_covers_load(consumed, produced)
            for consumed, produced in zip(consumption, solar, strict=True)
        ),
        battery_settings=settings,
    )


def run_scenario(scenario: dict):
    """Run optimization from a scenario dict. Returns the OptimizationResult (plan, P)."""
    return optimize_battery_schedule(**_scenario_inputs(scenario))


def run_scenario_realized(scenario: dict) -> tuple:
    """Run the optimizer AND execute its plan through the inverter simulator.

    Returns ``(result, realized_cost)`` where ``result.economic_summary.battery_solar_cost``
    is the planned cost (P) and ``realized_cost`` is what the derived inverter
    commands actually achieve (R). For an executable plan these are equal to the
    cent; a gap is a control-fidelity finding.
    """
    inp = _scenario_inputs(scenario)
    result = optimize_battery_schedule(**inp)
    dt = inp["period_duration_hours"]
    settings = inp["battery_settings"]
    commands = [
        derive_control_command(
            pd.decision.strategic_intent,
            pd.decision.battery_action / dt,
            settings,
            intra_period_discharge_allowed=pd.decision.intra_period_discharge_allowed,
        )
        for pd in result.period_data
    ]
    sim = simulate(
        commands,
        inp["solar_production"],
        inp["home_consumption"],
        inp["buy_price"],
        inp["sell_price"],
        inp["initial_soe"],
        settings,
        dt,
    )
    return result, sim.realized_cost


def get_intent_distribution(result) -> dict[str, int]:
    """Count how many periods have each strategic intent.

    Returns e.g. {"GRID_CHARGING": 5, "IDLE": 15, "BATTERY_EXPORT": 4}
    """
    counts: dict[str, int] = {}
    for pd in result.period_data:
        intent = pd.decision.strategic_intent
        counts[intent] = counts.get(intent, 0) + 1
    return counts


def get_intents_at_hours(result, hours: list[int]) -> dict[int, str]:
    """Get strategic intent at specific hours.

    Returns e.g. {2: "GRID_CHARGING", 19: "BATTERY_EXPORT"}
    """
    return {h: result.period_data[h].decision.strategic_intent for h in hours}


def assert_intent_at_hour(result, hour: int, expected_intent: str) -> None:
    """Assert that the optimizer chose a specific intent at a given hour."""
    actual = result.period_data[hour].decision.strategic_intent
    assert (
        actual == expected_intent
    ), f"Hour {hour}: expected {expected_intent}, got {actual}"


def assert_intent_present(result, intent: str, min_count: int = 1) -> None:
    """Assert that a strategic intent appears at least min_count times."""
    dist = get_intent_distribution(result)
    actual = dist.get(intent, 0)
    assert actual >= min_count, (
        f"Expected at least {min_count} periods with {intent}, "
        f"got {actual}. Distribution: {dist}"
    )


def assert_intent_absent(result, intent: str) -> None:
    """Assert that a strategic intent does not appear at all."""
    dist = get_intent_distribution(result)
    actual = dist.get(intent, 0)
    assert (
        actual == 0
    ), f"Expected zero {intent} periods, got {actual}. Distribution: {dist}"


def assert_physical_constraints(result, battery: dict) -> None:
    """Assert all physical constraints hold across the optimization result.

    Checks:
    - SOE stays within [min_soe_kwh, max_soe_kwh]
    - Charge/discharge power respects limits
    - Every period's detailed flows are internally coherent (see
      assert_flow_coherence)
    """
    tolerance = 1e-6

    # A scenario may legitimately start below min_soe_kwh (e.g. a live sensor
    # reading under Min SOC, see dp_battery_algorithm.py's _soe_floor()
    # docstring, #233) -- the effective lower bound is the fixture's own
    # starting point in that case, not the configured floor. For every
    # fixture that starts at/above its floor (all of them until #269's
    # regression_2026_07_25_090230), this is identical to min_soe_kwh --
    # zero behavior change. Callers that don't pass "initial_soe" on the
    # battery dict fall back to min_soe_kwh, which is also a no-op.
    effective_min_soe_kwh = min(
        battery["min_soe_kwh"], battery.get("initial_soe", battery["min_soe_kwh"])
    )

    for pd in result.period_data:
        soe_start = pd.energy.battery_soe_start
        soe_end = pd.energy.battery_soe_end

        assert (
            effective_min_soe_kwh - tolerance
            <= soe_start
            <= battery["max_soe_kwh"] + tolerance
        ), (
            f"Period {pd.period}: SOE start {soe_start:.2f} outside "
            f"[{effective_min_soe_kwh}, {battery['max_soe_kwh']}]"
        )
        assert (
            effective_min_soe_kwh - tolerance
            <= soe_end
            <= battery["max_soe_kwh"] + tolerance
        ), (
            f"Period {pd.period}: SOE end {soe_end:.2f} outside "
            f"[{effective_min_soe_kwh}, {battery['max_soe_kwh']}]"
        )

        action = pd.decision.battery_action
        if action and abs(action) > 0.01:
            power_tolerance = 1e-10
            if action > 0:
                assert (
                    action <= battery["max_charge_power_kw"] + power_tolerance
                ), f"Period {pd.period}: charge {action:.2f} kW > max {battery['max_charge_power_kw']} kW"
            else:
                assert (
                    abs(action) <= battery["max_discharge_power_kw"] + power_tolerance
                ), f"Period {pd.period}: discharge {abs(action):.2f} kW > max {battery['max_discharge_power_kw']} kW"

        assert_flow_coherence(pd)


# Detailed-flow invariants for DP-PLANNED periods.
#
# They exist because the DP had accumulated a number of independently-tuned
# constants (export thresholds, noise folds, power tolerances, SOE grid steps)
# that each behaved correctly in isolation but twice drifted into disagreeing on
# a narrow band of inputs, producing periods whose reported flows did not add up
# (#350 vs #240, diagnosed and fixed in #497). Nothing in the suite checked that
# a period's numbers were self-consistent, so those only ever surfaced when a
# human read a schedule by hand.
#
# All six hold for every period of every fixture. Two of them -- exports having
# a source, and the home being supplied exactly what it consumed -- were
# violated in 182 of 1875 periods before #497 and were pinned separately while
# that debt stood; they are ordinary assertions now.
#
# IMPORTANT -- planned periods only. `_calculate_detailed_flows` deliberately
# refuses to invent a flow to reconcile independent lifetime counters, so on
# MEASURED data these balances legitimately fail: leftover `grid_imported`
# beyond what the home and battery took is dropped rather than attributed
# (models.py:142), and `battery_to_grid` is capped by `grid_exported` rather
# than forced to absorb the discharge remainder (models.py:149). Both are
# cross-sensor noise, not defects. A DP plan has no sensors and no noise, so it
# has no such excuse. Do not point this helper at historical/measured
# EnergyData -- it will fail by design.
#
def assert_flow_coherence(pd) -> None:
    """Assert one DP-planned period's detailed flows add up to its totals."""
    tolerance = 1e-6
    e = pd.energy

    assert abs(e.grid_exported - e.solar_to_grid - e.battery_to_grid) < tolerance, (
        f"Period {pd.period}: exported energy has no source -- solar_to_grid "
        f"{e.solar_to_grid:.4f} + battery_to_grid {e.battery_to_grid:.4f} != "
        f"grid_exported {e.grid_exported:.4f}"
    )
    assert (
        abs(e.solar_to_home + e.battery_to_home + e.grid_to_home - e.home_consumption)
        < tolerance
    ), (
        f"Period {pd.period}: what reached the home does not match what it "
        f"consumed -- solar_to_home {e.solar_to_home:.4f} + battery_to_home "
        f"{e.battery_to_home:.4f} + grid_to_home {e.grid_to_home:.4f} != "
        f"home_consumption {e.home_consumption:.4f}"
    )
    assert (
        abs(e.battery_to_home + e.battery_to_grid - e.battery_discharged) < tolerance
    ), (
        f"Period {pd.period}: battery discharge does not split into its "
        f"destinations -- battery_to_home {e.battery_to_home:.4f} + "
        f"battery_to_grid {e.battery_to_grid:.4f} != battery_discharged "
        f"{e.battery_discharged:.4f}"
    )
    assert (
        abs(e.solar_to_battery + e.grid_to_battery - e.battery_charged) < tolerance
    ), (
        f"Period {pd.period}: battery charge does not split into its sources -- "
        f"solar_to_battery {e.solar_to_battery:.4f} + grid_to_battery "
        f"{e.grid_to_battery:.4f} != battery_charged {e.battery_charged:.4f}"
    )
    assert abs(e.grid_to_home + e.grid_to_battery - e.grid_imported) < tolerance, (
        f"Period {pd.period}: imported energy has no destination -- grid_to_home "
        f"{e.grid_to_home:.4f} + grid_to_battery {e.grid_to_battery:.4f} != "
        f"grid_imported {e.grid_imported:.4f}"
    )

    for flow_name in (
        "solar_to_home",
        "solar_to_battery",
        "solar_to_grid",
        "grid_to_home",
        "grid_to_battery",
        "battery_to_home",
        "battery_to_grid",
    ):
        value = getattr(e, flow_name)
        assert value >= -tolerance, (
            f"Period {pd.period}: {flow_name} is negative ({value:.4f}) -- a flow "
            f"between two entities cannot run backwards"
        )


def flows_for(
    power: float,
    soe: float,
    next_soe: float,
    home_consumption: float,
    solar_production: float,
    battery_settings,
    dt: float,
    import_cap_kwh: float | None = None,
):
    """The `PeriodFlows` record for one action, for tests that call
    `_build_period_data` directly.

    `_build_period_data` takes the flows as a required argument (Phase 3, P4)
    so that reporting cannot re-derive physics the objective already priced.
    Tests exercising it therefore have to produce the record the same way
    production does -- through `_period_flows` -- rather than hand-building
    one, which would reintroduce exactly the second derivation the signature
    exists to prevent. This wrapper only fills in the AC cap.
    """
    return _period_flows(
        power=power,
        soe=soe,
        next_soe=next_soe,
        home_consumption=home_consumption,
        solar_production=solar_production,
        battery_settings=battery_settings,
        dt=dt,
        import_cap_kwh=import_cap_kwh,
    )


def make_battery_settings(**overrides):
    """Create a BatterySettings instance with sensible test defaults.

    Accepts keyword overrides for any BatterySettings field.
    """
    defaults: dict[str, Any] = {
        "total_capacity": 20.0,
        "min_soc": 11.0,
        "max_soc": 100.0,
        "max_charge_power_kw": 10.0,
        "max_discharge_power_kw": 10.0,
        "efficiency_charge": 0.97,
        "efficiency_discharge": 0.95,
        "cycle_cost_per_kwh": 0.40,
    }
    defaults.update(overrides)
    return BatterySettings(**defaults)


def assert_savings_positive(result) -> None:
    """Assert the optimization produces positive savings vs grid-only."""
    savings = result.economic_summary.grid_to_battery_solar_savings
    assert savings > 0, (
        f"Expected positive savings, got {savings:.2f}. "
        f"Grid-only: {result.economic_summary.grid_only_cost:.2f}, "
        f"Optimized: {result.economic_summary.battery_solar_cost:.2f}"
    )


def empty_slot_table() -> list[dict]:
    """A Growatt MIN inverter with nothing programmed.

    The hardware always reports all 9 slots; unused ones come back disabled.
    An empty list means the read itself failed, which GrowattMinController
    treats as fatal (issue #551) — so mocks representing an idle inverter must
    return this, not [].
    """
    return [
        {
            "segment_id": slot_id,
            "start_time": "00:00",
            "end_time": "00:00",
            "batt_mode": "load_first",
            "enabled": False,
        }
        for slot_id in range(1, 10)
    ]
