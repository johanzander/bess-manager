"""
Test module for core battery optimization algorithm functions (DP-based, canonical for BESS).

This module contains the fundamental unit tests for the battery optimization algorithm,
using the unified optimize_battery_schedule API function from core.bess.dp_schedule and core.bess.dp_price_manager.
These tests verify that the core functions produce outputs with the expected structure
and reasonable values, but don't test specific optimization results.
"""

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.settings import BatterySettings

# Create a BatterySettings instance for testing
battery_settings = BatterySettings()


def test_battery_simulation_results(
    sample_price_data, sample_consumption_data, sample_solar_data
):
    """
    Test that battery optimization produces the expected results structure.
    """
    buy_price = sample_price_data["buy_price"]
    sell_price = sample_price_data["sell_price"]
    home_consumption = sample_consumption_data
    solar_production = sample_solar_data
    initial_soc = battery_settings.reserved_capacity

    results = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soc=initial_soc,
        battery_settings=battery_settings,
    )

    hourly_data = results["hourly_data"]
    economic_results = results["economic_results"]

    assert isinstance(hourly_data, dict)
    expected_keys = [
        "hour",
        "buy_price",
        "sell_price",
        "home_consumption",
        "solar_production",
        "battery_action",
        "state_of_charge",
        "grid_import",
        "grid_export",
        "base_case_hourly_cost",
        "battery_solar_hourly_cost",
        "battery_cost",
    ]
    for key in expected_keys:
        assert key in hourly_data

    expected_keys = [
        "base_cost",
        "battery_solar_cost",
        "base_to_battery_solar_savings",
        "base_to_battery_solar_savings_pct",
        "total_charged",
        "total_discharged",
    ]
    for key in expected_keys:
        assert key in economic_results

    assert economic_results["base_cost"] >= 0
    assert (
        economic_results["base_to_battery_solar_savings"]
        == economic_results["base_cost"] - economic_results["battery_solar_cost"]
    )


def test_battery_constraints_respected():
    """
    Test that the battery simulation respects physical constraints.
    """
    buy_price = [0.1] * 12 + [1.0] * 12
    sell_price = [price * 0.7 for price in buy_price]
    home_consumption = [2.0] * 24
    solar_production = [0.0] * 24
    initial_soc = battery_settings.reserved_capacity

    results = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soc=initial_soc,
        battery_settings=battery_settings,
    )

    hourly_data = results["hourly_data"]
    soc_values = hourly_data["state_of_charge"]
    assert all(
        battery_settings.reserved_capacity <= soc <= battery_settings.total_capacity
        for soc in soc_values
    )
    actions = hourly_data["battery_action"]
    assert all(
        -battery_settings.max_discharge_power_kw
        <= action
        <= battery_settings.max_charge_power_kw
        for action in actions
    )
