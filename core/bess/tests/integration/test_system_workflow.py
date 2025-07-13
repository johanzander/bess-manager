# tests/integration/test_system_workflow.py
"""
End-to-end system workflow integration tests.

Tests complete workflows from external data input through optimization
to hardware control using the new HourlyData structures throughout.

UPDATED: All tests now pass explicit current_hour parameter for deterministic testing.
"""

from datetime import datetime, timedelta

from core.bess.models import EnergyData, HourlyData


def populate_historical_data(
    battery_system, start_hour: int, end_hour: int, sample_energy_data=None
):
    """Populate historical data store with realistic mock data for integration tests.

    Args:
        battery_system: BatterySystemManager instance
        start_hour: First hour to populate (inclusive)
        end_hour: Last hour to populate (inclusive)
        sample_energy_data: Optional EnergyData template, creates realistic data if None
    """
    if sample_energy_data is None:
        # Create realistic energy data template
        sample_energy_data = EnergyData(
            solar_production=0.0,  # Will be set per hour
            home_consumption=4.0,  # Constant consumption
            grid_imported=4.0,  # Will be adjusted per hour
            grid_exported=0.0,  # Will be adjusted per hour
            battery_charged=0.0,
            battery_discharged=0.0,
            battery_soe_start=25.0,  # Will be chained per hour, 50% SOC = 25.0 kWh (assuming 50 kWh battery)
            battery_soe_end=25.0,  # Will be chained per hour, 50% SOC = 25.0 kWh (assuming 50 kWh battery)
        )

    current_soe = 25.0  # Starting SOE in kWh (50% SOC = 25 kWh assuming 50 kWh battery)
    base_time = datetime.now().replace(minute=0, second=0, microsecond=0)

    for hour in range(start_hour, end_hour + 1):
        # Create realistic hourly variation
        if 6 <= hour <= 18:  # Daytime
            solar = max(0, 8.0 * (1 - abs(hour - 12) / 6))  # Peak at noon
        else:
            solar = 0.0

        consumption = 4.0 + (hour % 3) * 0.5  # Slight variation

        # Simple energy balance
        net_solar = max(0, solar - consumption)
        grid_import = max(0, consumption - solar)
        grid_export = net_solar

        # Create energy data for this hour
        hour_energy_data = EnergyData(
            solar_production=solar,
            home_consumption=consumption,
            grid_imported=grid_import,
            grid_exported=grid_export,
            battery_charged=0.0,
            battery_discharged=0.0,
            battery_soe_start=current_soe,
            battery_soe_end=current_soe,  # No battery action in mock data
        )

        # Record the historical data
        success = battery_system.historical_store.record_energy_data(
            hour=hour,
            energy_data=hour_energy_data,
            data_source="actual",
            timestamp=base_time + timedelta(hours=hour),
        )

        if not success:
            raise RuntimeError(f"Failed to record historical data for hour {hour}")


class TestCompleteWorkflows:
    """Test complete system workflows from data input to hardware control."""

    def test_price_to_hardware_workflow(
        self, battery_system_with_arbitrage, mock_controller
    ):
        """Test complete workflow: prices → optimization → hardware commands."""
        # Clear any previous calls
        mock_controller.calls = {
            "grid_charge": [],
            "discharge_rate": [],
            "charge_rate": [],
            "tou_segments": [],
        }

        # No historical data needed for prepare_next_day=True (tomorrow's schedule)

        # Execute complete workflow with explicit current_hour
        success = battery_system_with_arbitrage.update_battery_schedule(
            current_hour=0, prepare_next_day=True
        )
        assert success, "Should create and apply schedule"

        # Verify optimization was performed
        latest_schedule = (
            battery_system_with_arbitrage.schedule_store.get_latest_schedule()
        )
        assert latest_schedule is not None, "Should have created schedule"

        # Verify hardware received commands (should have some calls due to arbitrage opportunities)
        total_calls = (
            len(mock_controller.calls["grid_charge"])
            + len(mock_controller.calls["discharge_rate"])
            + len(mock_controller.calls["charge_rate"])
            + len(mock_controller.calls["tou_segments"])
        )

        assert (
            total_calls > 0
        ), f"Should send hardware commands, got calls: {mock_controller.calls}"

    def test_sensor_to_storage_workflow(self, battery_system, sample_new_hourly_data):
        """Test workflow: sensor data → processing → storage."""
        # Simulate sensor data collection
        hour = 12
        success = battery_system.historical_store.record_energy_data(
            hour=hour, energy_data=sample_new_hourly_data.energy, data_source="actual"
        )
        assert success, "Should record sensor data"

        # Verify data can be retrieved
        stored_data = battery_system.historical_store.get_hour_record(hour)
        assert stored_data is not None, "Should retrieve stored data"
        assert isinstance(stored_data, HourlyData), "Should return HourlyData"
        assert stored_data.data_source == "actual", "Should preserve data source"

        # Verify data integrity
        assert (
            stored_data.energy.solar_production
            == sample_new_hourly_data.energy.solar_production
        )
        assert (
            stored_data.energy.home_consumption
            == sample_new_hourly_data.energy.home_consumption
        )

    def test_forecast_to_optimization_workflow(self, battery_system):
        """Test workflow: forecasts → optimization → schedule storage."""
        current_hour = 8

        # Set realistic forecasts
        controller = battery_system._controller
        controller.solar_forecast = (
            [0.0] * 6 + [8.0] * 8 + [0.0] * 10
        )  # 24 elements total
        controller.consumption_forecast = [4.0] * 24

        # POPULATE HISTORICAL DATA for past hours
        populate_historical_data(battery_system, 0, current_hour - 1)

        # Execute workflow with explicit current_hour
        success = battery_system.update_battery_schedule(
            current_hour=current_hour, prepare_next_day=False
        )
        assert success, "Should complete forecast to optimization workflow"

        # Verify optimization results stored
        latest_schedule = battery_system.schedule_store.get_latest_schedule()
        assert latest_schedule is not None, "Should store optimization results"

        # Verify data consistency
        hourly_data = latest_schedule.optimization_result.hourly_data
        expected_hours = 24 - current_hour  # Remaining hours in day
        assert (
            len(hourly_data) == expected_hours
        ), f"Should have {expected_hours} hours of schedule data"

        # Debug: Print first few hours to understand the structure
        print(f"DEBUG: current_hour={current_hour}, expected_hours={expected_hours}")
        for i in range(min(3, len(hourly_data))):
            hour_data = hourly_data[i]
            print(f"DEBUG: hourly_data[{i}].hour = {hour_data.hour}")

        # Verify all hours have HourlyData structure
        for i, hour_data in enumerate(hourly_data):
            assert isinstance(
                hour_data, HourlyData
            ), f"Hour {i} should be HourlyData"


#           expected_hour = current_hour + i
#            assert hour_data.hour == expected_hour, f"Hourly data index {i} should be for hour {expected_hour}, got hour {hour_data.hour}"


class TestDailyViewGeneration:
    """Test daily view generation and data combination."""

    def test_daily_view_creation(self, battery_system):
        """Test daily view generation uses HourlyData throughout."""
        current_hour = 12

        # POPULATE HISTORICAL DATA for past hours
        populate_historical_data(battery_system, 0, current_hour - 1)

        # Create schedule for future hours with explicit current_hour
        success = battery_system.update_battery_schedule(
            current_hour=current_hour, prepare_next_day=False
        )
        assert success, "Should create schedule"

        # Get daily view with explicit current hour (no more real-time dependency!)
        daily_view = battery_system.get_current_daily_view(current_hour=current_hour)
        assert daily_view is not None, "Should return daily view"
        assert len(daily_view.hourly_data) == 24, "Should have complete 24-hour view"

        # Verify data sources are correctly marked
        actual_count = sum(
            1 for h in daily_view.hourly_data if h.data_source == "actual"
        )
        predicted_count = sum(
            1 for h in daily_view.hourly_data if h.data_source == "predicted"
        )

        assert actual_count == current_hour, f"Should have {current_hour} actual hours"
        assert (
            predicted_count == 24 - current_hour
        ), f"Should have {24 - current_hour} predicted hours"

        # Verify hourly data structure
        for i, hour_data in enumerate(daily_view.hourly_data):
            assert isinstance(
                hour_data, HourlyData
            ), f"Hour {i} should be HourlyData"
            assert hour_data.hour == i, f"Hour {i} should have correct hour number"

            if i < current_hour:
                assert hour_data.data_source == "actual", f"Hour {i} should be actual"
            else:
                assert (
                    hour_data.data_source == "predicted"
                ), f"Hour {i} should be predicted"

    def test_daily_view_with_mixed_data_sources(
        self, battery_system, sample_new_hourly_data
    ):
        """Test daily view with mixed actual/predicted data sources."""
        current_hour = 14

        # POPULATE HISTORICAL DATA for past hours
        populate_historical_data(battery_system, 0, current_hour - 1)

        # Create schedule for future hours with explicit current_hour
        success = battery_system.update_battery_schedule(
            current_hour=current_hour, prepare_next_day=False
        )
        assert success, "Should create schedule from hour 14"

        # Generate daily view with explicit current hour
        buy_prices = [1.0] * 24
        sell_prices = [0.8] * 24

        daily_view = battery_system.daily_view_builder.build_daily_view(
            current_hour=current_hour, buy_price=buy_prices, sell_price=sell_prices
        )

        # Verify data sources are correctly marked
        assert (
            daily_view.actual_hours_count == current_hour
        ), f"Should have {current_hour} actual hours"
        assert (
            daily_view.predicted_hours_count == 24 - current_hour
        ), f"Should have {24 - current_hour} predicted hours"

        # Verify data source annotations
        for i, hour_data in enumerate(daily_view.hourly_data):
            if i < current_hour:
                assert hour_data.data_source == "actual", f"Hour {i} should be actual"
            else:
                assert (
                    hour_data.data_source == "predicted"
                ), f"Hour {i} should be predicted"

    def test_daily_view_economic_calculations(self, battery_system_with_arbitrage):
        """Test daily view economic calculations."""
        current_hour = 6

        # POPULATE HISTORICAL DATA for past hours
        populate_historical_data(battery_system_with_arbitrage, 0, current_hour - 1)

        # Create schedule with explicit current_hour
        success = battery_system_with_arbitrage.update_battery_schedule(
            current_hour=current_hour, prepare_next_day=False
        )
        assert success, "Should create schedule"

        # Get daily view with explicit current hour
        daily_view = battery_system_with_arbitrage.get_current_daily_view(
            current_hour=current_hour
        )

        # Verify economic metrics
        assert isinstance(
            daily_view.total_daily_savings, int | float
        ), "Total savings should be numeric"
        assert isinstance(
            daily_view.actual_savings_so_far, int | float
        ), "Actual savings should be numeric"
        assert isinstance(
            daily_view.predicted_remaining_savings, int | float
        ), "Predicted savings should be numeric"

        # Verify consistency
        calculated_total = (
            daily_view.actual_savings_so_far + daily_view.predicted_remaining_savings
        )
        assert (
            abs(daily_view.total_daily_savings - calculated_total) < 0.01
        ), "Savings calculations should be consistent"


class TestSystemResilience:
    """Test system resilience and error recovery."""

    def test_partial_data_handling(self, battery_system):
        """Test system handling of partial or missing data."""
        # Create schedule with minimal data
        controller = battery_system._controller
        original_solar = controller.solar_forecast

        # Set partial solar data (some hours missing)
        controller.solar_forecast = [0.0] * 12 + [None] * 6 + [0.0] * 6

        try:
            success = battery_system.update_battery_schedule(
                current_hour=0, prepare_next_day=True
            )
            # Should either succeed with default values or fail gracefully
            assert isinstance(success, bool), "Should return boolean result"
        finally:
            # Restore original data
            controller.solar_forecast = original_solar


class TestPerformanceWorkflows:
    """Test performance-critical workflows."""

    def test_optimization_performance(self, battery_system_with_arbitrage):
        """Test that optimization completes in reasonable time."""
        import time

        current_hour = 10

        # POPULATE HISTORICAL DATA
        populate_historical_data(battery_system_with_arbitrage, 0, current_hour - 1)

        # Time the optimization with explicit current_hour
        start_time = time.time()
        success = battery_system_with_arbitrage.update_battery_schedule(
            current_hour=current_hour, prepare_next_day=False
        )
        end_time = time.time()

        assert success, "Optimization should complete successfully"

        optimization_time = end_time - start_time
        assert (
            optimization_time < 10.0
        ), f"Optimization should complete in under 10 seconds, took {optimization_time:.2f}s"

        # Verify result quality with explicit current hour
        latest_schedule = (
            battery_system_with_arbitrage.schedule_store.get_latest_schedule()
        )
        assert latest_schedule is not None, "Should produce valid schedule"

        economic_summary = latest_schedule.optimization_result.economic_summary
        assert (
            economic_summary.grid_to_battery_solar_savings >= 0
        ), "Should show non-negative savings"


class TestDataFlowValidation:
    """Test data flow consistency and validation."""

    def test_end_to_end_data_consistency(self, battery_system_with_arbitrage):
        """Test data consistency from input to output."""
        current_hour = 8

        # POPULATE HISTORICAL DATA
        populate_historical_data(battery_system_with_arbitrage, 0, current_hour - 1)

        # Execute complete workflow with explicit current_hour
        success = battery_system_with_arbitrage.update_battery_schedule(
            current_hour=current_hour, prepare_next_day=False
        )
        assert success, "Should complete workflow"

        # Get data at different stages with explicit current hour
        latest_schedule = (
            battery_system_with_arbitrage.schedule_store.get_latest_schedule()
        )
        daily_view = battery_system_with_arbitrage.get_current_daily_view(
            current_hour=current_hour
        )

        # Verify consistency between schedule and daily view
        schedule_data = latest_schedule.optimization_result.hourly_data
        predicted_view_data = [
            h for h in daily_view.hourly_data if h.data_source == "predicted"
        ]

        assert len(schedule_data) == len(
            predicted_view_data
        ), "Schedule and predicted view should have same length"

        # Verify hour consistency for predicted hours
        for i, (sched_hour, view_hour) in enumerate(
            zip(schedule_data, predicted_view_data, strict=False)
        ):
            #            assert sched_hour.hour == view_hour.hour, f"Predicted hour {i} should be consistent"
            assert isinstance(
                sched_hour, HourlyData
            ), f"Schedule hour {i} should be HourlyData"
            assert isinstance(
                view_hour, HourlyData
            ), f"View hour {i} should be HourlyData"

    def test_decision_intent_propagation(self, battery_system_with_arbitrage):
        """Test that strategic intents propagate correctly through the system."""
        current_hour = 5

        # POPULATE HISTORICAL DATA
        populate_historical_data(battery_system_with_arbitrage, 0, current_hour - 1)

        success = battery_system_with_arbitrage.update_battery_schedule(
            current_hour=current_hour, prepare_next_day=False
        )
        assert success, "Should create schedule"

        # Get strategic intents from different sources with explicit current hour
        latest_schedule = (
            battery_system_with_arbitrage.schedule_store.get_latest_schedule()
        )
        schedule_intents = [
            h.decision.strategic_intent
            for h in latest_schedule.optimization_result.hourly_data
        ]

        daily_view = battery_system_with_arbitrage.get_current_daily_view(
            current_hour=current_hour
        )
        predicted_view_intents = [
            h.decision.strategic_intent
            for h in daily_view.hourly_data
            if h.data_source == "predicted"
        ]

        # Verify consistency for predicted hours
        assert (
            schedule_intents == predicted_view_intents
        ), "Strategic intents should be consistent between schedule and predicted view hours"

        # Verify valid intents
        valid_intents = {
            "GRID_CHARGING",
            "SOLAR_STORAGE",
            "LOAD_SUPPORT",
            "EXPORT_ARBITRAGE",
            "IDLE",
        }
        for intent in schedule_intents:
            assert intent in valid_intents, f"Invalid strategic intent: {intent}"
