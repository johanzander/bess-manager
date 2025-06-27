"""
Test module for running tests with the sample scenario (DP-based, canonical for BESS).

This module contains tests that run the battery optimization algorithm on various
scenario files. These tests ensure the algorithm can process scenario files and
produce reasonable outputs.
"""

import json
import logging
import os

import pytest

from core.bess.dp_battery_algorithm import (
    optimize_battery_schedule,
    print_optimization_results,
)
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


@pytest.mark.parametrize(
    "scenario_name",
    [
        "historical_2024_08_16_high_spread_no_solar",
        "historical_2025_01_05_no_spread_no_solar",
        "historical_2025_01_12_evening_peak_no_solar",
        "historical_2025_01_13_night_low_no_solar",
        "historical_2025_06_02_high_solar_export",
    ],
)
def test_historical_scenarios(scenario_name):
    scenario = load_test_scenario(scenario_name)
    base_prices = scenario["base_prices"]
    home_consumption = scenario["home_consumption"]
    solar_production = scenario["solar_production"]
    battery = scenario["battery"]

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

    # Log the battery settings being used
    logger.info(
        "Using battery settings: max charge power = %.1f kW, max discharge power = %.1f kW",
        battery_settings.max_charge_power_kw,
        battery_settings.max_discharge_power_kw,
    )

    # Use PriceManager for price calculations
    price_source = MockSource(base_prices)
    price_manager = PriceManager(
        price_source=price_source,
        markup_rate=0.08,
        vat_multiplier=1.25,
        additional_costs=1.03,
        tax_reduction=0.6518,
    )

    buy_prices = price_manager.buy_prices
    sell_prices = price_manager.sell_prices

    results = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soc=battery["initial_soc"],
        battery_settings=battery_settings,
    )

    # Log the results table using the new structure
    print_optimization_results(results, buy_prices, sell_prices)

    # Check if 'expected_results' exists in the test data
    if "expected_results" in scenario:
        expected_results = scenario["expected_results"]
        economic_results = results.economic_summary
        
        assert round(economic_results["base_cost"], 2) == round(
            expected_results["base_cost"], 2
        )
        assert round(economic_results["battery_solar_cost"], 2) == round(
            expected_results["battery_solar_cost"], 2
        )
        assert round(
            economic_results["base_to_battery_solar_savings"], 2
        ) == round(expected_results["base_to_battery_solar_savings"], 2)
        assert round(
            economic_results["base_to_battery_solar_savings_pct"], 2
        ) == round(expected_results["base_to_battery_solar_savings_pct"], 2)


@pytest.mark.parametrize(
    "scenario_name",
    [
        "synthetic_2024_08_16_high_spread_with_solar",
        "synthetic_2025_01_12_evening_peak_with_solar",
        "synthetic_consumption_high_no_solar",
        "synthetic_seasonal_winter",
        "synthetic_consumption_ev_charging",
        "synthetic_extreme_volatility",
        "synthetic_seasonal_summer",
        "synthetic_seasonal_spring",
        "synthetic_extreme_negative_prices",
        "synthetic_consumption_efficient",
        "synthetic_historical_2024_08_16_high_spread_with_solar",
        "synthetic_historical_2025_01_12_evening_peak_with_solar",
    ],
)
def test_synthetic_scenarios(scenario_name):
    scenario = load_test_scenario(scenario_name)
    base_prices = scenario["base_prices"]
    home_consumption = scenario["home_consumption"]
    solar_production = scenario["solar_production"]
    battery = scenario["battery"]

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

    # Log the battery settings being used
    logger.info(
        "Using battery settings: max charge power = %.1f kW, max discharge power = %.1f kW",
        battery_settings.max_charge_power_kw,
        battery_settings.max_discharge_power_kw,
    )

    price_source = MockSource(base_prices)
    price_manager = PriceManager(
        price_source=price_source,
        markup_rate=0.0,
        vat_multiplier=1.0,
        additional_costs=0.0,
        tax_reduction=0.0,
    )
    buy_prices = price_manager.get_buy_prices()
    sell_prices = price_manager.get_sell_prices()

    results = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soc=battery["initial_soc"],
        battery_settings=battery_settings,
    )

    # Log the results table using the new structure
    print_optimization_results(results, buy_prices, sell_prices)

    if "expected_results" in scenario:
        economic_results = results.economic_summary
        expected_results = scenario["expected_results"]

        # Verify the economic results with a tolerance for floating-point differences
        assert round(economic_results["base_cost"], 1) == round(
            expected_results["base_cost"], 1
        )
        assert round(economic_results["battery_solar_cost"], 1) == round(
            expected_results["battery_solar_cost"], 1
        )
        assert round(economic_results["base_to_battery_solar_savings"], 1) == round(
            expected_results["base_to_battery_solar_savings"], 1
        )
        assert round(economic_results["base_to_battery_solar_savings_pct"], 1) == round(
            expected_results["base_to_battery_solar_savings_pct"], 1
        )