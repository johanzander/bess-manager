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

import pytest  # type: ignore

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


@pytest.mark.parametrize("scenario_name", get_all_scenario_files())
def test_all_scenarios(scenario_name):
    """Test all scenario files with the battery optimization algorithm."""
    scenario = load_test_scenario(scenario_name)
    base_prices = scenario["base_prices"]
    home_consumption = scenario["home_consumption"]
    solar_production = scenario["solar_production"]
    battery = scenario["battery"]
    price_data = scenario.get("price_data")

    # Determine the actual horizon from the scenario data
    horizon = len(base_prices)

    # Validate that all arrays have the same length
    assert (
        len(home_consumption) == horizon
    ), f"home_consumption length {len(home_consumption)} != base_prices length {horizon}"
    assert (
        len(solar_production) == horizon
    ), f"solar_production length {len(solar_production)} != base_prices length {horizon}"

    # Create battery settings directly from the test scenario values
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

    # Create PriceManager
    price_manager = PriceManager(
        MockSource(base_prices),
        markup_rate=markup_rate,
        vat_multiplier=vat_multiplier,
        additional_costs=additional_costs,
        tax_reduction=tax_reduction,
        area="SE4",
    )

    # Get buy and sell prices
    buy_prices = price_manager.get_buy_prices(raw_prices=base_prices)
    sell_prices = price_manager.get_sell_prices(raw_prices=base_prices)

    # These scenario files are hourly test data
    # System runs quarterly internally, but these unit tests use hourly resolution
    period_duration_hours = 1.0

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
            battery["min_soe_kwh"] - soe_tolerance <= soe_start_kwh <= battery["max_soe_kwh"] + soe_tolerance
        ), f"SOE start {soe_start_kwh:.2f} kWh outside bounds [{battery['min_soe_kwh']}, {battery['max_soe_kwh']}]"
        assert (
            battery["min_soe_kwh"] - soe_tolerance <= soe_end_kwh <= battery["max_soe_kwh"] + soe_tolerance
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
