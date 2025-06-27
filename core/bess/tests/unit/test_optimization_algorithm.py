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

    # Test new OptimizationResult structure
    assert hasattr(results, 'hourly_data')
    assert hasattr(results, 'economic_summary')
    
    hourly_data_list = results.hourly_data
    economic_results = results.economic_summary

    # Test that we have the right structure
    assert isinstance(hourly_data_list, list)
    assert len(hourly_data_list) == 24  # Should have 24 hours
    assert isinstance(economic_results, dict)

    # Test that each hourly data object has expected attributes
    for hour_data in hourly_data_list:
        assert hasattr(hour_data, 'hour')
        assert hasattr(hour_data, 'buy_price')
        assert hasattr(hour_data, 'sell_price')
        assert hasattr(hour_data, 'home_consumed')
        assert hasattr(hour_data, 'solar_generated')
        assert hasattr(hour_data, 'battery_action')
        assert hasattr(hour_data, 'battery_soc_end')
        assert hasattr(hour_data, 'grid_imported')
        assert hasattr(hour_data, 'grid_exported')
        assert hasattr(hour_data, 'hourly_cost')
        assert hasattr(hour_data, 'battery_cycle_cost')

    # Test economic results have expected keys
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
    buy_price = [0.5] * 24
    sell_price = [0.3] * 24
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

    # Test constraints using new structure
    for hour_data in results.hourly_data:
        # SOC should stay within bounds
        assert battery_settings.min_soc_kwh <= hour_data.battery_soc_end <= battery_settings.max_soc_kwh
        
        # Battery action should respect power limits
        if hour_data.battery_action:
            assert abs(hour_data.battery_action) <= max(
                battery_settings.max_charge_power_kw,
                battery_settings.max_discharge_power_kw
            )