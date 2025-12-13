"""Integration tests for quarterly (15-minute) resolution support.

This test file demonstrates how to use the new quarterly test fixtures
and validates that the system works correctly with 96-period data.
"""

import pytest  # type: ignore

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.settings import BatterySettings
from core.bess.tests.conftest import MockHomeAssistantController


class TestQuarterlyOptimization:
    """Test optimization with quarterly (96-period) data."""

    def test_quarterly_optimization_returns_96_periods(self, quarterly_test_scenario):
        """Test that optimization with 96 quarterly prices returns 96 periods.

        This is the foundational test for quarterly resolution support.
        It validates that:
        1. The optimizer accepts 96-period input
        2. Returns 96 periods in the result
        3. Produces valid economic calculations
        """
        battery_settings = BatterySettings()
        data = quarterly_test_scenario

        result = optimize_battery_schedule(
            buy_price=data["buy_prices"],
            sell_price=data["sell_prices"],
            home_consumption=data["consumption"],
            solar_production=data["solar"],
            initial_soe=data["initial_soe"],
            battery_settings=battery_settings,
            initial_cost_basis=data["initial_cost_basis"],
        )

        # Verify we get 96 quarterly periods back
        assert len(result.period_data) == 96, "Should return 96 quarterly periods"

        # Verify period indices are correct (0-95)
        period_indices = [p.period for p in result.period_data]
        assert period_indices == list(range(96)), "Period indices should be 0-95"

        # Verify economic summary is valid
        assert result.economic_summary is not None, "Economic summary should be present"
        economic_summary = result.economic_summary
        assert (
            economic_summary.grid_only_cost > 0
        ), "Grid-only cost should be positive"
        assert (
            economic_summary.grid_to_battery_solar_savings >= 0
        ), "Savings should be non-negative"

    def test_quarterly_optimization_produces_savings(self, quarterly_test_scenario):
        """Test that quarterly optimization produces cost savings."""
        battery_settings = BatterySettings()
        data = quarterly_test_scenario

        result = optimize_battery_schedule(
            buy_price=data["buy_prices"],
            sell_price=data["sell_prices"],
            home_consumption=data["consumption"],
            solar_production=data["solar"],
            initial_soe=data["initial_soe"],
            battery_settings=battery_settings,
            initial_cost_basis=data["initial_cost_basis"],
        )

        # With arbitrage prices, should produce savings
        assert result.economic_summary is not None, "Economic summary should be present"
        economic_summary = result.economic_summary
        savings = economic_summary.grid_to_battery_solar_savings
        assert savings > 0, f"Should produce savings, got {savings} SEK"

        # Savings should be a reasonable percentage
        grid_cost = economic_summary.grid_only_cost
        savings_pct = (savings / grid_cost) * 100
        assert (
            savings_pct < 100
        ), f"Savings percentage should be reasonable, got {savings_pct}%"

    def test_quarterly_daily_view_creation(self, quarterly_test_scenario):
        """Test that DailyViewBuilder works with quarterly optimization results."""
        manager = BatterySystemManager(controller=MockHomeAssistantController())
        battery_settings = BatterySettings()
        data = quarterly_test_scenario

        # Create quarterly optimization
        optimization_result = optimize_battery_schedule(
            buy_price=data["buy_prices"],
            sell_price=data["sell_prices"],
            home_consumption=data["consumption"],
            solar_production=data["solar"],
            initial_soe=data["initial_soe"],
            battery_settings=battery_settings,
            initial_cost_basis=data["initial_cost_basis"],
        )

        # Store the schedule
        manager.schedule_store.store_schedule(
            optimization_result=optimization_result,
            optimization_period=0,
        )

        # Build daily view
        daily_view = manager.daily_view_builder.build_daily_view(
            current_period=0,
        )

        # DailyView passes through quarterly periods (no aggregation)
        # We expect 96 quarterly periods in the view
        assert (
            len(daily_view.periods) == 96
        ), f"DailyView should have 96 quarterly periods, got {len(daily_view.periods)}"

        # Verify total savings is calculated
        assert daily_view.total_savings >= 0, "Total savings should be non-negative"

        # All periods should be predicted (no actual data)
        assert daily_view.predicted_count == 96, "All periods should be predicted"
        assert daily_view.actual_count == 0, "No actual data yet"


class TestQuarterlyDataStructures:
    """Test that data structures handle quarterly resolution correctly."""

    def test_period_indices_quarterly(self, quarterly_test_scenario):
        """Test that period indices work correctly for quarterly resolution."""
        data = quarterly_test_scenario
        battery_settings = BatterySettings()

        result = optimize_battery_schedule(
            buy_price=data["buy_prices"],
            sell_price=data["sell_prices"],
            home_consumption=data["consumption"],
            solar_production=data["solar"],
            initial_soe=data["initial_soe"],
            battery_settings=battery_settings,
            initial_cost_basis=data["initial_cost_basis"],
        )

        # Check period mapping
        # Period 0 = 00:00, Period 4 = 01:00, Period 8 = 02:00, etc.
        assert result.period_data[0].period == 0, "First period should be 0 (00:00)"
        assert result.period_data[4].period == 4, "Period 4 should be 4 (01:00)"
        assert result.period_data[8].period == 8, "Period 8 should be 8 (02:00)"
        assert result.period_data[95].period == 95, "Last period should be 95 (23:45)"

    def test_quarterly_energy_balance(self, quarterly_test_scenario):
        """Test that energy balance is maintained with quarterly data."""
        data = quarterly_test_scenario
        battery_settings = BatterySettings()

        result = optimize_battery_schedule(
            buy_price=data["buy_prices"],
            sell_price=data["sell_prices"],
            home_consumption=data["consumption"],
            solar_production=data["solar"],
            initial_soe=data["initial_soe"],
            battery_settings=battery_settings,
            initial_cost_basis=data["initial_cost_basis"],
        )

        # Check energy balance for each period
        for i, period_data in enumerate(result.period_data):
            energy = period_data.energy

            # All energy values should be non-negative
            assert energy.solar_production >= 0, f"Period {i}: Solar should be >= 0"
            assert energy.home_consumption >= 0, f"Period {i}: Consumption should be >= 0"
            assert energy.battery_charged >= 0, f"Period {i}: Charging should be >= 0"
            assert (
                energy.battery_discharged >= 0
            ), f"Period {i}: Discharging should be >= 0"
            assert energy.grid_imported >= 0, f"Period {i}: Grid import should be >= 0"
            assert energy.grid_exported >= 0, f"Period {i}: Grid export should be >= 0"

            # SOE should be within battery capacity (allow small floating point tolerance)
            battery_capacity = battery_settings.total_capacity
            epsilon = 1e-6  # Tolerance for floating point precision (accumulated over 96 periods)
            assert (
                -epsilon <= energy.battery_soe_start <= battery_capacity + epsilon
            ), f"Period {i}: SOE start should be in range"
            assert (
                -epsilon <= energy.battery_soe_end <= battery_capacity + epsilon
            ), f"Period {i}: SOE end should be in range"


class TestQuarterlyVsHourlyComparison:
    """Compare quarterly vs hourly resolution results.

    These tests validate that the system produces consistent results
    when given the same data at different resolutions.
    """

    @pytest.mark.skip(reason="Comparison test - implement after hourly tests are stable")
    def test_quarterly_aggregates_to_hourly(self, quarterly_test_scenario):
        """Test that quarterly results aggregate to similar hourly results.

        This test will validate that when we aggregate 4 quarterly periods
        into 1 hourly period, we get similar economic results to running
        the optimization with hourly data.
        """
        # TODO: Implement quarterly-to-hourly aggregation comparison
        pass

    @pytest.mark.skip(reason="Comparison test - implement after hourly tests are stable")
    def test_savings_comparable_across_resolutions(self, quarterly_test_scenario):
        """Test that total daily savings are comparable between resolutions.

        While quarterly resolution should give better optimization results
        (due to finer granularity), the difference shouldn't be dramatic
        for typical price curves.
        """
        # TODO: Implement savings comparison
        pass
