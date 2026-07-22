"""Shared test utilities for battery optimization tests.

Reduces boilerplate across test files by providing:
- run_scenario(): one-liner to run optimization from a scenario dict (plan, P)
- run_scenario_realized(): also executes the plan through the inverter simulator,
  returning the *realized* economics (R) so scenarios can verify the plan is
  faithfully executable (R == P), not just that the plan claims a number.
- Behavioral assertion helpers for strategic intents and physical constraints
"""

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.price_manager import MockSource, PriceManager
from core.bess.settings import (
    ADDITIONAL_COSTS,
    MARKUP_RATE,
    TAX_REDUCTION,
    VAT_MULTIPLIER,
    BatterySettings,
)
from core.bess.simulation.inverter_simulator import derive_control_command, simulate


def _scenario_inputs(scenario: dict):
    """Build optimizer inputs from a scenario dict. Shared by run_scenario and
    run_scenario_realized so plan (P) and realized (R) use identical inputs."""
    base_prices = scenario["base_prices"]
    battery = scenario["battery"]
    price_data = scenario.get("price_data")

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
    )

    if price_data:
        markup_rate = price_data["markup_rate"]
        vat_multiplier = price_data["vat_multiplier"]
        additional_costs = price_data["additional_costs"]
        tax_reduction = price_data["tax_reduction"]
    else:
        markup_rate = MARKUP_RATE
        vat_multiplier = VAT_MULTIPLIER
        additional_costs = ADDITIONAL_COSTS
        tax_reduction = TAX_REDUCTION

    price_manager = PriceManager(
        MockSource(base_prices),
        markup_rate=markup_rate,
        vat_multiplier=vat_multiplier,
        additional_costs=additional_costs,
        tax_reduction=tax_reduction,
        area="SE4",
    )
    return {
        "buy_price": price_manager.get_buy_prices(raw_prices=base_prices),
        "sell_price": price_manager.get_sell_prices(raw_prices=base_prices),
        "home_consumption": scenario["home_consumption"],
        "solar_production": scenario["solar_production"],
        "initial_soe": battery["initial_soe"],
        "battery_settings": battery_settings,
        "period_duration_hours": scenario.get("period_duration_hours", 1.0),
    }


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
            pd.decision.strategic_intent, pd.decision.battery_action / dt, settings
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
    """
    tolerance = 1e-6

    for pd in result.period_data:
        soe_start = pd.energy.battery_soe_start
        soe_end = pd.energy.battery_soe_end

        assert (
            battery["min_soe_kwh"] - tolerance
            <= soe_start
            <= battery["max_soe_kwh"] + tolerance
        ), (
            f"Period {pd.period}: SOE start {soe_start:.2f} outside "
            f"[{battery['min_soe_kwh']}, {battery['max_soe_kwh']}]"
        )
        assert (
            battery["min_soe_kwh"] - tolerance
            <= soe_end
            <= battery["max_soe_kwh"] + tolerance
        ), (
            f"Period {pd.period}: SOE end {soe_end:.2f} outside "
            f"[{battery['min_soe_kwh']}, {battery['max_soe_kwh']}]"
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


def make_battery_settings(**overrides):
    """Create a BatterySettings instance with sensible test defaults.

    Accepts keyword overrides for any BatterySettings field.
    """
    defaults = {
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
