"""
Test module for core battery optimization algorithm functions (DP-based, canonical for BESS).

This module contains the fundamental unit tests for the battery optimization algorithm,
using the unified optimize_battery_schedule API function. These tests verify that the
core functions produce outputs with the expected structure and reasonable values,
but don't test specific optimization results.
"""

import pytest  # type: ignore

from core.bess.dp_battery_algorithm import (
    optimize_battery_schedule,
    split_solar_forecast,
)
from core.bess.models import EconomicSummary, PeriodData
from core.bess.settings import BatterySettings

# Create a BatterySettings instance for testing
battery_settings = BatterySettings()


def test_battery_simulation_results(
    sample_price_data, sample_consumption_data, sample_solar_data
):
    """
    Test that battery optimization produces the expected results structure with new APIs.
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
        initial_soe=initial_soc,
        battery_settings=battery_settings,
    )

    # Test new OptimizationResult structure
    assert hasattr(results, "period_data")
    assert hasattr(results, "economic_summary")
    assert hasattr(results, "input_data")

    hourly_data_list = results.period_data
    economic_summary = results.economic_summary

    # Test that we have the right structure
    assert isinstance(hourly_data_list, list)
    assert len(hourly_data_list) == 24  # Should have 24 hours
    assert isinstance(
        economic_summary, EconomicSummary
    )  # Should be EconomicSummary dataclass

    # Test that each hourly data object is PeriodData with proper structure
    for hour_data in hourly_data_list:
        assert isinstance(hour_data, PeriodData)

        # Test core properties (these use the property accessors)
        assert hasattr(hour_data, "period")
        assert 0 <= hour_data.period <= 23

        # Test energy data access - using single source of truth pattern
        assert hasattr(hour_data.energy, "solar_production")
        assert hasattr(hour_data.energy, "home_consumption")
        assert hasattr(hour_data.energy, "grid_imported")
        assert hasattr(hour_data.energy, "grid_exported")
        assert hasattr(hour_data.energy, "battery_charged")
        assert hasattr(hour_data.energy, "battery_discharged")
        assert hasattr(hour_data.energy, "battery_soe_start")
        assert hasattr(hour_data.energy, "battery_soe_end")

        # Test economic data access - using single source of truth pattern
        assert hasattr(hour_data.economic, "buy_price")
        assert hasattr(hour_data.economic, "sell_price")
        assert hasattr(hour_data.economic, "hourly_cost")
        assert hasattr(hour_data.economic, "hourly_savings")

        # Test strategy data access - using single source of truth pattern
        assert hasattr(hour_data.decision, "strategic_intent")
        assert hasattr(hour_data.decision, "battery_action")

        # Test that data source is set correctly
        assert hour_data.data_source == "predicted"

        # Test that all components are present
        assert hour_data.energy is not None
        assert hour_data.economic is not None
        assert hour_data.decision is not None

    # Test economic summary has expected fields (EconomicSummary dataclass)
    assert hasattr(economic_summary, "grid_only_cost")
    assert hasattr(economic_summary, "battery_solar_cost")
    assert hasattr(economic_summary, "grid_to_battery_solar_savings")
    assert hasattr(economic_summary, "grid_to_battery_solar_savings_pct")
    assert hasattr(economic_summary, "total_charged")
    assert hasattr(economic_summary, "total_discharged")

    # Test economic calculations with proper floating-point tolerance
    assert economic_summary.grid_only_cost >= 0

    # Use floating-point tolerance for accumulated vs calculated values
    expected_savings = (
        economic_summary.grid_only_cost - economic_summary.battery_solar_cost
    )
    actual_savings = economic_summary.grid_to_battery_solar_savings

    # Allow for small floating-point precision differences from 24 hours of calculations
    tolerance = 1e-10  # Very small tolerance for precision differences
    assert (
        abs(actual_savings - expected_savings) < tolerance
    ), f"Savings calculation mismatch: {actual_savings} vs {expected_savings} (diff: {abs(actual_savings - expected_savings)})"

    # Test that savings percentage is calculated correctly
    if economic_summary.grid_only_cost > 0:
        expected_pct = (
            economic_summary.grid_to_battery_solar_savings
            / economic_summary.grid_only_cost
        ) * 100
        assert (
            abs(economic_summary.grid_to_battery_solar_savings_pct - expected_pct)
            < 0.01
        )


def test_battery_constraints_respected():
    """
    Test that the battery simulation respects physical constraints using new APIs.
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
        initial_soe=initial_soc,
        battery_settings=battery_settings,
    )

    # Test constraints using new PeriodData structure
    for hour_data in results.period_data:
        # SOE is already in kWh, no conversion needed
        soe_start_kwh = hour_data.energy.battery_soe_start
        soe_end_kwh = hour_data.energy.battery_soe_end

        assert (
            battery_settings.min_soe_kwh
            <= soe_start_kwh
            <= battery_settings.max_soe_kwh
        )
        assert (
            battery_settings.min_soe_kwh <= soe_end_kwh <= battery_settings.max_soe_kwh
        )

        # Battery action should respect power limits
        if hour_data.decision.battery_action:
            assert abs(hour_data.decision.battery_action) <= max(
                battery_settings.max_charge_power_kw,
                battery_settings.max_discharge_power_kw,
            )

        # Energy balance should be maintained (approximately)
        energy_in = hour_data.energy.solar_production + hour_data.energy.grid_imported
        energy_out = hour_data.energy.home_consumption + hour_data.energy.grid_exported
        battery_net = (
            hour_data.energy.battery_charged - hour_data.energy.battery_discharged
        )

        # Energy balance: energy_in = energy_out + battery_net (within tolerance for efficiency losses)
        balance_error = abs(energy_in - energy_out - battery_net)
        assert balance_error < 0.1, f"Energy balance error too large: {balance_error}"


def SKIP_test_strategic_intent_assignment():  # TODO: Improve test to validate correct strategic decisions, not just presence of intents
    """
    Test that strategic intents are assigned correctly using new APIs.
    """
    # Create scenario with high price spread to encourage battery usage
    buy_price = [
        0.3,
        0.3,
        0.3,
        0.3,
        0.3,
        0.3,  # Night - cheap
        0.8,
        0.8,
        0.8,
        0.8,
        0.8,
        0.8,  # Morning - expensive
        0.4,
        0.4,
        0.4,
        0.4,
        0.4,
        0.4,  # Afternoon - medium
        0.9,
        0.9,
        0.9,
        0.9,
        0.3,
        0.3,
    ]  # Evening peak then night

    sell_price = [p * 0.7 for p in buy_price]  # Sell price is 70% of buy price
    home_consumption = [1.5] * 24  # Constant consumption
    solar_production = (
        [0.0] * 6 + [1.0, 2.0, 3.0, 4.0, 3.0, 2.0] + [1.0] * 6 + [0.0] * 6
    )  # Solar during day

    results = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=battery_settings.min_soe_kwh,
        battery_settings=battery_settings,
    )

    # Check that strategic intents are assigned
    intents = [hour_data.decision.strategic_intent for hour_data in results.period_data]

    # Should have some strategic decisions (not all IDLE)
    assert len(set(intents)) > 1, "Should have multiple strategic intents"

    # Verify valid strategic intents only
    valid_intents = {
        "IDLE",
        "GRID_CHARGING",
        "SOLAR_STORAGE",
        "LOAD_SUPPORT",
        "EXPORT_ARBITRAGE",
    }
    for intent in intents:
        assert intent in valid_intents, f"Invalid strategic intent: {intent}"


def test_energy_data_structure():
    """
    Test that energy data structure is properly populated in PeriodData.
    """
    buy_price = [0.5] * 24
    sell_price = [0.3] * 24
    home_consumption = [2.0] * 24
    solar_production = [1.0] * 24
    initial_soc = battery_settings.reserved_capacity

    results = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soc,
        battery_settings=battery_settings,
    )

    for hour_data in results.period_data:
        # Test that energy component exists and has data
        assert hour_data.energy is not None
        assert hour_data.energy.solar_production >= 0
        assert hour_data.energy.home_consumption >= 0
        assert hour_data.energy.grid_imported >= 0
        assert hour_data.energy.grid_exported >= 0

        # Test detailed flows are calculated
        assert hour_data.energy.solar_to_home >= 0
        assert hour_data.energy.solar_to_battery >= 0
        assert hour_data.energy.solar_to_grid >= 0
        assert hour_data.energy.grid_to_home >= 0
        assert hour_data.energy.grid_to_battery >= 0
        assert hour_data.energy.battery_to_home >= 0
        assert hour_data.energy.battery_to_grid >= 0


def test_economic_data_structure():
    """
    Test that economic data structure is properly populated in PeriodData.
    """
    buy_price = [0.5] * 24
    sell_price = [0.3] * 24
    home_consumption = [2.0] * 24
    solar_production = [1.0] * 24
    initial_soc = battery_settings.reserved_capacity

    results = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soc,
        battery_settings=battery_settings,
    )

    for hour_data in results.period_data:
        # Test that economic component exists and has data
        assert hour_data.economic is not None
        assert hour_data.economic.buy_price >= 0
        assert hour_data.economic.sell_price >= 0
        assert hour_data.economic.grid_only_cost >= 0  # Grid-only baseline cost
        # Solar-only cost can be negative when exporting solar (earning money from export)
        # No assertion needed for solar_only_cost as it can be positive, negative, or zero
        assert hour_data.economic.battery_cycle_cost >= 0

        # Test that hourly savings is calculated correctly vs solar-only baseline
        expected_savings = (
            hour_data.economic.solar_only_cost - hour_data.economic.hourly_cost
        )
        assert abs(hour_data.economic.hourly_savings - expected_savings) < 0.01


def test_strategy_data_structure():
    """
    Test that strategy data structure is properly populated in PeriodData.
    """
    buy_price = [0.5] * 24
    sell_price = [0.3] * 24
    home_consumption = [2.0] * 24
    solar_production = [1.0] * 24
    initial_soc = battery_settings.reserved_capacity

    results = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soc,
        battery_settings=battery_settings,
    )

    for hour_data in results.period_data:
        # Test that strategy component exists and has data
        assert hour_data.decision is not None
        assert hour_data.decision.strategic_intent is not None
        assert hour_data.decision.battery_action is not None
        assert hour_data.decision.cost_basis >= 0


# =============================================================================
# Solar Clipping Tests
# =============================================================================


def test_split_solar_forecast_math():
    """split_solar_forecast correctly separates AC and DC-excess components."""
    # 96 periods of 15min each (0.25h), inverter limited to 5kW → 1.25 kWh/period
    raw_solar = [0.0] * 32 + [0.5] * 16 + [1.5] * 16 + [2.0] * 16 + [0.0] * 16
    ac_solar, dc_excess = split_solar_forecast(
        solar_production=raw_solar,
        inverter_ac_capacity_kw=5.0,
        period_duration_hours=0.25,
    )
    ac_limit = 5.0 * 0.25  # 1.25 kWh per period

    assert len(ac_solar) == len(raw_solar)
    assert len(dc_excess) == len(raw_solar)

    for raw, ac, dc in zip(raw_solar, ac_solar, dc_excess, strict=True):
        assert ac == min(raw, ac_limit)
        assert dc == max(0.0, raw - ac_limit)
        assert abs(ac + dc - raw) < 1e-9

    # Periods below the limit have no DC excess
    for i in range(48):  # first 48 periods: 0.0 or 0.5 kWh (both < 1.25 kWh)
        assert dc_excess[i] == 0.0

    # Periods above the limit have DC excess
    for i in range(64, 80):  # 2.0 kWh/period > 1.25 kWh limit
        assert dc_excess[i] == pytest.approx(0.75)


def test_split_solar_forecast_preserves_total():
    """AC + DC excess always equals the raw solar input for every period."""
    raw_solar = [0.0, 0.5, 1.25, 2.0, 3.5]
    ac_solar, dc_excess = split_solar_forecast(
        solar_production=raw_solar,
        inverter_ac_capacity_kw=5.0,
        period_duration_hours=0.25,
    )
    for raw, ac, dc in zip(raw_solar, ac_solar, dc_excess, strict=True):
        assert ac + dc == pytest.approx(raw)


def test_no_clipping_when_disabled():
    """Optimizer behavior is identical when inverter_ac_capacity_kw is 0 (disabled)."""
    buy_price = [0.3] * 8 + [1.5] * 8 + [0.3] * 8
    sell_price = [0.2] * 24
    home_consumption = [0.5] * 24
    solar = [0.0] * 8 + [3.0] * 8 + [0.0] * 8

    settings = BatterySettings(
        total_capacity=10.0,
        min_soc=10.0,
        max_soc=100.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        cycle_cost_per_kwh=0.10,
        min_action_profit_threshold=0.0,
    )

    # Without DC excess (no clipping)
    result_no_clip = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar,
        initial_soe=settings.min_soe_kwh,
        battery_settings=settings,
        dc_excess_solar=None,
    )

    # With dc_excess_solar of all zeros (equivalent to disabled)
    result_zeros = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar,
        initial_soe=settings.min_soe_kwh,
        battery_settings=settings,
        dc_excess_solar=[0.0] * 24,
    )

    # Both results should have identical economic outcomes
    assert result_no_clip.economic_summary is not None
    assert result_zeros.economic_summary is not None
    assert (
        result_no_clip.economic_summary.grid_to_battery_solar_savings
        == pytest.approx(
            result_zeros.economic_summary.grid_to_battery_solar_savings, abs=0.01
        )
    )
    assert result_no_clip.economic_summary.battery_solar_cost == pytest.approx(
        result_zeros.economic_summary.battery_solar_cost, abs=0.01
    )


def test_dc_excess_has_zero_grid_cost():
    """DC excess stored in battery has cost basis reflecting only cycle cost (no grid cost).

    Even when the profitability gate rejects AC optimization (falls back to idle schedule),
    DC excess is still physically absorbed into the battery — it is tracked in the result.
    """
    settings = BatterySettings(
        total_capacity=10.0,
        min_soc=0.0,
        max_soc=100.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        cycle_cost_per_kwh=0.40,
        min_action_profit_threshold=0.0,
    )

    # 4 periods: DC excess midday, high-price consumption in the evening.
    # Period 0-1: DC excess available, battery absorbs it (free solar, cycle cost only)
    # Period 2-3: expensive grid, discharge stored DC energy for home consumption
    buy_price = [0.3, 0.3, 2.0, 2.0]
    sell_price = [0.1, 0.1, 0.1, 0.1]
    home_consumption = [0.0, 0.0, 1.5, 1.5]
    ac_solar = [0.0, 0.0, 0.0, 0.0]
    dc_excess = [2.0, 2.0, 0.0, 0.0]

    result = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=ac_solar,
        initial_soe=0.0,
        battery_settings=settings,
        dc_excess_solar=dc_excess,
    )

    assert len(result.period_data) == 4

    # DC excess periods should show absorption with no grid import
    dc_periods = [p for p in result.period_data if p.energy.dc_excess_to_battery > 0]
    assert len(dc_periods) > 0, "Expected at least one period with DC excess absorption"

    for period in dc_periods:
        # DC excess is absorbed without any grid import (it's free solar on DC bus)
        assert period.energy.grid_imported == pytest.approx(
            0.0, abs=0.01
        ), "DC excess absorption should not require grid import"
        # DC excess tracked separately (not as AC solar)
        assert period.energy.solar_production == pytest.approx(0.0, abs=0.01)


def test_clipping_capture_preferred_over_grid_charge():
    """Optimizer keeps battery headroom for free clipped solar rather than grid-charging early."""
    settings = BatterySettings(
        total_capacity=10.0,
        min_soc=0.0,
        max_soc=100.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        cycle_cost_per_kwh=0.10,
        min_action_profit_threshold=0.0,
    )

    # Scenario: cheap grid at night (periods 0-7), DC clipping midday (periods 8-15),
    # expensive grid evening (periods 16-23).
    # A clipping-unaware optimizer would grid-charge at night, filling battery before clipping.
    # A clipping-aware optimizer should leave headroom for free clipped solar.
    buy_price = [0.2] * 8 + [1.0] * 8 + [2.0] * 8
    sell_price = [0.1] * 24
    home_consumption = [0.2] * 24
    ac_solar = [0.0] * 8 + [1.0] * 8 + [0.0] * 8  # AC solar (capped at inverter limit)
    dc_excess = [0.0] * 8 + [1.5] * 8 + [0.0] * 8  # DC excess above inverter limit

    result_with_clipping = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=ac_solar,
        initial_soe=0.0,
        battery_settings=settings,
        dc_excess_solar=dc_excess,
    )

    # Calculate total solar clipped in the clipping-aware result
    total_clipped = sum(
        p.energy.solar_clipped for p in result_with_clipping.period_data
    )

    # The optimizer should capture most of the available DC excess (not clip it due to full battery)
    total_dc_available = sum(dc_excess)
    capture_rate = (
        1.0 - (total_clipped / total_dc_available) if total_dc_available > 0 else 1.0
    )
    assert capture_rate > 0.5, (
        f"Expected optimizer to capture >50% of DC excess, got {capture_rate:.1%} "
        f"(clipped={total_clipped:.2f} of {total_dc_available:.2f} kWh)"
    )
