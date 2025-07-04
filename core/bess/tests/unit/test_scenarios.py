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
from core.bess.models import EconomicSummary, HourlyData
from core.bess.price_manager import MockSource, PriceManager
from core.bess.settings import BatterySettings

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
        total_capacity=battery["max_soc_kwh"],
        min_soc=(battery["min_soc_kwh"] / battery["max_soc_kwh"]) * 100.0,
        max_soc=100.0,
        max_charge_power_kw=battery["max_charge_power_kw"],
        max_discharge_power_kw=battery["max_discharge_power_kw"],
        efficiency_charge=battery["efficiency_charge"],
        efficiency_discharge=battery["efficiency_discharge"],
        cycle_cost_per_kwh=battery["cycle_cost_per_kwh"],
    )

    # Create PriceManager
    price_manager = PriceManager(MockSource(base_prices))

    # Get buy and sell prices
    buy_prices = price_manager.get_buy_prices(raw_prices=base_prices)
    sell_prices = price_manager.get_sell_prices(raw_prices=base_prices)

    # Run optimization
    result = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soc=battery["min_soc_kwh"],
        battery_settings=battery_settings,
    )

    # Validate results using new data structures
    assert isinstance(result.hourly_data, list)
    assert (
        len(result.hourly_data) == horizon
    )  # Use actual horizon instead of hardcoded 24
    assert isinstance(result.economic_summary, EconomicSummary)

    # Validate hourly data structure
    for i, hour_data in enumerate(result.hourly_data):
        assert isinstance(hour_data, HourlyData)
        assert hour_data.energy is not None
        assert hour_data.economic is not None
        assert hour_data.decision is not None
        assert hour_data.hour == i  # Should match the index
        assert hour_data.data_source == "predicted"

    # Validate economic summary - use proper attribute access
    assert hasattr(result.economic_summary, "base_cost")
    assert hasattr(result.economic_summary, "battery_solar_cost")
    assert hasattr(result.economic_summary, "base_to_battery_solar_savings")
    assert result.economic_summary.base_cost >= 0

    # Log results for debugging
    logger.info(f"Scenario: {scenario_name} (horizon: {horizon} hours)")
    logger.info(f"Base cost: {result.economic_summary.base_cost:.2f} SEK")
    logger.info(f"Optimized cost: {result.economic_summary.battery_solar_cost:.2f} SEK")
    logger.info(
        f"Savings: {result.economic_summary.base_to_battery_solar_savings:.2f} SEK"
    )
    logger.info(
        f"Savings %: {result.economic_summary.base_to_battery_solar_savings_pct:.1f}%"
    )

    # Print full optimization results for detailed analysis
    print_optimization_results(result, buy_prices, sell_prices)

    # Validate that the optimization is reasonable
    assert result.economic_summary.base_cost > 0, "Base cost should be positive"

    # Battery usage should be within physical constraints
    for hour_data in result.hourly_data:
        # FIXED: Access SOC through the energy field - these are already in percentage
        soc_start_percent = hour_data.energy.battery_soc_start  # Already in %
        soc_end_percent = hour_data.energy.battery_soc_end  # Already in %

        # Convert to kWh for comparison with battery constraints
        soc_start_kwh = (soc_start_percent / 100.0) * battery_settings.total_capacity
        soc_end_kwh = (soc_end_percent / 100.0) * battery_settings.total_capacity

        # Validate SOC bounds in kWh
        assert (
            battery["min_soc_kwh"] <= soc_start_kwh <= battery["max_soc_kwh"]
        ), f"SOC start {soc_start_kwh:.2f} kWh outside bounds [{battery['min_soc_kwh']}, {battery['max_soc_kwh']}]"
        assert (
            battery["min_soc_kwh"] <= soc_end_kwh <= battery["max_soc_kwh"]
        ), f"SOC end {soc_end_kwh:.2f} kWh outside bounds [{battery['min_soc_kwh']}, {battery['max_soc_kwh']}]"

        # Battery action should respect power limits - access through strategy field
        battery_action = hour_data.decision.battery_action
        if (
            battery_action and abs(battery_action) > 0.01
        ):  # Allow for small numerical errors
            assert abs(battery_action) <= max(
                battery["max_charge_power_kw"], battery["max_discharge_power_kw"]
            ), f"Battery action {battery_action:.2f} kW exceeds power limits"
