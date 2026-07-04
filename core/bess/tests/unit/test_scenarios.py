"""
Test module for running tests with scenario files (DP-based, canonical for BESS).

This module contains tests that run the battery optimization algorithm on various
scenario files. These tests ensure the algorithm can process scenario files and
produce reasonable outputs.
"""

import json
import logging
import os
from pathlib import Path

import pytest

from core.bess.dp_battery_algorithm import (
    optimize_battery_schedule,
    print_optimization_results,
)
from core.bess.models import EconomicSummary, PeriodData
from core.bess.price_manager import MockSource, PriceManager
from core.bess.settings import (
    ADDITIONAL_COSTS,
    MARKUP_RATE,
    TAX_REDUCTION,
    VAT_MULTIPLIER,
    BatterySettings,
)
from core.bess.tests.helpers import (
    assert_intent_absent,
    assert_intent_present,
    assert_physical_constraints,
    assert_savings_positive,
    get_intent_distribution,
)

pytestmark = pytest.mark.slow

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_test_scenario(scenario_name):
    file_path = os.path.join(os.path.dirname(__file__), "data", f"{scenario_name}.json")
    with open(file_path) as f:
        scenario = json.load(f)
    return scenario


def get_all_scenario_files():
    """Get all scenario files from the data directory."""
    data_dir = Path(__file__).parent / "data"
    scenario_files = []

    if data_dir.exists():
        for file_path in data_dir.glob("*.json"):
            scenario_files.append(file_path.stem)  # filename without extension

    return sorted(scenario_files)


def build_scenario_inputs(scenario_name):
    """Load a scenario file and derive battery settings + buy/sell prices.

    Shared by every test that runs a scenario through the optimizer, so the
    battery/price derivation logic (and its price_data fallback rules) lives
    in exactly one place.
    """
    scenario = load_test_scenario(scenario_name)
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
    buy_prices = price_manager.get_buy_prices(raw_prices=base_prices)
    sell_prices = price_manager.get_sell_prices(raw_prices=base_prices)
    period_duration_hours = scenario.get("period_duration_hours", 1.0)

    return scenario, battery_settings, buy_prices, sell_prices, period_duration_hours


@pytest.mark.parametrize("scenario_name", get_all_scenario_files())
def test_all_scenarios(scenario_name):
    """Test all scenario files with the battery optimization algorithm."""
    scenario, battery_settings, buy_prices, sell_prices, period_duration_hours = (
        build_scenario_inputs(scenario_name)
    )
    home_consumption = scenario["home_consumption"]
    solar_production = scenario["solar_production"]
    battery = scenario["battery"]

    # Determine the actual horizon from the scenario data
    horizon = len(scenario["base_prices"])

    # Validate that all arrays have the same length
    assert (
        len(home_consumption) == horizon
    ), f"home_consumption length {len(home_consumption)} != base_prices length {horizon}"
    assert (
        len(solar_production) == horizon
    ), f"solar_production length {len(solar_production)} != base_prices length {horizon}"

    # Run optimization
    result = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=battery["initial_soe"],
        battery_settings=battery_settings,
        period_duration_hours=period_duration_hours,
    )

    # Validate results using new data structures
    assert isinstance(result.period_data, list)
    assert (
        len(result.period_data) == horizon
    )  # Use actual horizon instead of hardcoded 24
    assert isinstance(result.economic_summary, EconomicSummary)

    # Validate hourly data structure
    for i, hour_data in enumerate(result.period_data):
        assert isinstance(hour_data, PeriodData)
        assert hour_data.energy is not None
        assert hour_data.economic is not None
        assert hour_data.decision is not None
        assert hour_data.period == i  # Should match the index
        assert hour_data.data_source == "predicted"

    # Validate economic summary - use proper attribute access
    assert hasattr(result.economic_summary, "grid_only_cost")
    assert hasattr(result.economic_summary, "battery_solar_cost")
    assert hasattr(result.economic_summary, "grid_to_battery_solar_savings")
    assert result.economic_summary.grid_only_cost >= 0

    # Log results for debugging
    logger.info(f"Scenario: {scenario_name} (horizon: {horizon} hours)")
    logger.info(f"Grid-only cost: {result.economic_summary.grid_only_cost:.2f} SEK")
    logger.info(f"Optimized cost: {result.economic_summary.battery_solar_cost:.2f} SEK")
    logger.info(
        f"Savings: {result.economic_summary.grid_to_battery_solar_savings:.2f} SEK"
    )
    logger.info(
        f"Savings %: {result.economic_summary.grid_to_battery_solar_savings_pct:.1f}%"
    )

    # Print full optimization results for detailed analysis
    print_optimization_results(result, buy_prices, sell_prices)

    # Validate that the optimization is reasonable
    assert (
        result.economic_summary.grid_only_cost > 0
    ), "Grid-only cost should be positive"

    # Check if 'expected_results' exists in the test data
    if "expected_results" in scenario:
        expected_results = scenario["expected_results"]
        economic_results = result.economic_summary

        # Compare expected vs actual results with rounding to account for small numerical differences
        # Map scenario field names to EconomicSummary field names
        assert round(economic_results.grid_only_cost, 1) == round(
            expected_results["base_cost"], 1
        ), f"Grid-only cost mismatch: {economic_results.grid_only_cost:.2f} != {expected_results['base_cost']:.2f}"

        assert round(economic_results.battery_solar_cost, 1) == round(
            expected_results["battery_solar_cost"], 1
        ), f"Battery solar cost mismatch: {economic_results.battery_solar_cost:.2f} != {expected_results['battery_solar_cost']:.2f}"

        assert round(economic_results.grid_to_battery_solar_savings, 1) == round(
            expected_results["base_to_battery_solar_savings"], 1
        ), f"Savings mismatch: {economic_results.grid_to_battery_solar_savings:.2f} != {expected_results['base_to_battery_solar_savings']:.2f}"

        assert round(economic_results.grid_to_battery_solar_savings_pct, 1) == round(
            expected_results["base_to_battery_solar_savings_pct"], 1
        ), f"Savings percentage mismatch: {economic_results.grid_to_battery_solar_savings_pct:.2f}% != {expected_results['base_to_battery_solar_savings_pct']:.2f}%"
    else:
        logger.info(
            f"No expected results for scenario {scenario_name}, skipping validation"
        )

    # Battery usage should be within physical constraints
    # Small tolerance for floating-point precision errors (e.g., np.arange producing 30.000000000000025)
    soe_tolerance = 1e-6
    for hour_data in result.period_data:
        # Access SOE directly - these are already in kWh
        soe_start_kwh = hour_data.energy.battery_soe_start  # Already in kWh
        soe_end_kwh = hour_data.energy.battery_soe_end  # Already in kWh

        # Validate SOE bounds in kWh (with tolerance for floating-point precision)
        assert (
            battery["min_soe_kwh"] - soe_tolerance
            <= soe_start_kwh
            <= battery["max_soe_kwh"] + soe_tolerance
        ), f"SOE start {soe_start_kwh:.2f} kWh outside bounds [{battery['min_soe_kwh']}, {battery['max_soe_kwh']}]"
        assert (
            battery["min_soe_kwh"] - soe_tolerance
            <= soe_end_kwh
            <= battery["max_soe_kwh"] + soe_tolerance
        ), f"SOE end {soe_end_kwh:.2f} kWh outside bounds [{battery['min_soe_kwh']}, {battery['max_soe_kwh']}]"

        # Battery action should respect power limits - access through strategy field
        battery_action = hour_data.decision.battery_action
        if (
            battery_action and abs(battery_action) > 0.01
        ):  # Allow for small numerical errors
            # Add small tolerance for floating-point precision errors
            tolerance = 1e-10
            if battery_action > 0:  # Charging (positive)
                assert (
                    battery_action <= battery["max_charge_power_kw"] + tolerance
                ), f"Battery charging action {battery_action:.2f} kW exceeds max charge power {battery['max_charge_power_kw']} kW"
            else:  # Discharging (negative)
                assert (
                    abs(battery_action) <= battery["max_discharge_power_kw"] + tolerance
                ), f"Battery discharging action {abs(battery_action):.2f} kW exceeds max discharge power {battery['max_discharge_power_kw']} kW"

    # ── Behavioral assertions (from expected_behavior in scenario JSON) ──
    if "expected_behavior" in scenario:
        behavior = scenario["expected_behavior"]
        dist = get_intent_distribution(result)
        logger.info(f"Intent distribution: {dist}")

        for intent in behavior.get("intents_present", []):
            assert_intent_present(result, intent)

        for intent in behavior.get("intents_absent", []):
            assert_intent_absent(result, intent)

        if behavior.get("savings_positive"):
            assert_savings_positive(result)

        if behavior.get("constraints", {}).get("soe_within_bounds"):
            assert_physical_constraints(result, battery)
    else:
        logger.info(
            f"No expected_behavior for scenario {scenario_name}, skipping behavioral validation"
        )

    # ── Plan-faithfulness: R == P (#145) ──
    # Executing the optimizer's plan through the inverter simulator must reproduce
    # the planned economics within the DP's SoE/power-grid resolution. A larger gap
    # is a control-fidelity finding, not just discretization.
    from core.bess.simulation.inverter_simulator import (
        derive_control_command,
        simulate,
    )

    commands = [
        derive_control_command(
            pd.decision.strategic_intent,
            pd.decision.battery_action / period_duration_hours,
            battery_settings,
        )
        for pd in result.period_data
    ]
    sim = simulate(
        commands,
        solar_production,
        home_consumption,
        buy_prices,
        sell_prices,
        battery["initial_soe"],
        battery_settings,
        period_duration_hours,
    )
    planned_cost = result.economic_summary.battery_solar_cost
    gap = sim.realized_cost - planned_cost

    tol = max(0.5, 0.01 * abs(planned_cost))
    assert abs(gap) <= tol, (
        f"{scenario_name}: realized != planned — R={sim.realized_cost:.2f}, "
        f"P={planned_cost:.2f}, gap {gap:+.3f} SEK exceeds tolerance {tol:.2f}"
    )


@pytest.mark.parametrize(
    "scenario_name",
    [
        "realworld_2026_04_11_004719",
        "realworld_2026_04_19_084608",
        "realworld_2026_04_24_090423",
    ],
)
def test_gate_never_substitutes_a_worse_fallback(scenario_name):
    """Regression for #231 follow-up: when the profitability gate trips, the
    all-IDLE fallback it substitutes must never cost more than the DP
    schedule it's rejecting. `_create_idle_schedule` still pays wear cost on
    passively-absorbed solar but never discharges to recoup any of it, so on
    these three real scenarios the "safe" fallback was in fact strictly more
    expensive than the schedule it replaced.

    Compares the actual (gated) result against the DP's real schedule,
    obtained by re-running with the gate effectively disabled — not against
    a freshly recomputed fallback, which would trivially match the gated
    result and prove nothing.
    """
    import dataclasses

    scenario, battery_settings, buy_prices, sell_prices, period_duration_hours = (
        build_scenario_inputs(scenario_name)
    )
    home_consumption = scenario["home_consumption"]
    solar_production = scenario["solar_production"]
    battery = scenario["battery"]

    result = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=battery["initial_soe"],
        battery_settings=battery_settings,
        period_duration_hours=period_duration_hours,
    )

    # Re-run with the gate effectively disabled to recover the DP's real,
    # rejected schedule and its true cost.
    unfettered_settings = dataclasses.replace(
        battery_settings, min_action_profit_threshold=-1e9
    )
    unfettered_result = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=battery["initial_soe"],
        battery_settings=unfettered_settings,
        period_duration_hours=period_duration_hours,
    )
    dp_real_cost = unfettered_result.economic_summary.battery_solar_cost

    assert result.economic_summary.battery_solar_cost <= dp_real_cost + 1e-6, (
        f"{scenario_name}: returned schedule costs "
        f"{result.economic_summary.battery_solar_cost:.2f} but the DP's own "
        f"(rejected) schedule only cost {dp_real_cost:.2f} — the gate "
        f"substituted a schedule worse than the one it rejected."
    )
