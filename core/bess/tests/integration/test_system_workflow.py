# tests/integration/test_system_workflow.py
"""
End-to-end system workflow integration tests.

Tests complete workflows from external data input through optimization
to hardware control using the new PeriodData structures throughout.

UPDATED: All tests now pass explicit current_hour parameter for deterministic testing.
"""

from datetime import datetime, timedelta

from core.bess.models import DecisionData, EconomicData, EnergyData, PeriodData


def hourly_to_quarterly(hourly_data: list) -> list:
    """Convert 24-hour data to 96-period quarterly data by repeating each hour 4 times."""
    return [value for value in hourly_data for _ in range(4)]


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

        # For quarterly resolution, create 4 consecutive periods per hour
        for quarter in range(4):
            period_index = hour * 4 + quarter  # Consecutive period index (0,1,2,3...)

            # Scale hourly energy values to 15-minute periods (divide by 4)
            energy_data = EnergyData(
                solar_production=solar / 4,
                home_consumption=consumption / 4,
                grid_imported=grid_import / 4,
                grid_exported=grid_export / 4,
                battery_charged=0.0,
                battery_discharged=0.0,
                battery_soe_start=current_soe,
                battery_soe_end=current_soe,  # No battery action in mock data
            )

            # Calculate economic data from energy flows
            economic_data = EconomicData.from_energy_data(
                energy_data=energy_data,
                buy_price=1.0,
                sell_price=0.5,
                battery_cycle_cost=0.0,  # No cycle cost for actual historical data
            )

            # Create full PeriodData object for this quarterly period
            period_data = PeriodData(
                period=period_index,  # Consecutive period: 0, 1, 2, 3...
                energy=energy_data,
                timestamp=base_time + timedelta(minutes=period_index * 15),  # 15-minute increments
                data_source="actual",
                economic=economic_data,
                decision=DecisionData(),
            )

            # Store consecutive period
            battery_system.historical_store.record_period(
                period_index=period_index,
                period_data=period_data,
            )


class TestCompleteWorkflows:
    """Test complete system workflows from data input to hardware control."""

    def test_price_to_hardware_workflow(
        self, quarterly_battery_system, mock_controller
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

        # Execute complete workflow with explicit current_period
        success = quarterly_battery_system.update_battery_schedule(
            current_period=0, prepare_next_day=True
        )
        assert success, "Should create and apply schedule"

        # Verify optimization was performed
        latest_schedule = (
            quarterly_battery_system.schedule_store.get_latest_schedule()
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
        # Simulate sensor data collection at 12:00 = period 48
        period_index = 48
        battery_system.historical_store.record_period(
            period_index=period_index, period_data=sample_new_hourly_data
        )

        # Verify data can be retrieved
        stored_data = battery_system.historical_store.get_period(period_index)
        assert stored_data is not None, "Should retrieve stored data"
        assert isinstance(stored_data, PeriodData), "Should return PeriodData"
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

    def test_forecast_to_optimization_workflow(self, quarterly_battery_system):
        """Test workflow: forecasts → optimization → schedule storage."""
        current_hour = 8
        current_period = current_hour * 4  # Convert to quarterly periods

        # Set realistic forecasts (convert hourly to quarterly)
        controller = quarterly_battery_system._controller
        hourly_solar = [0.0] * 6 + [8.0] * 8 + [0.0] * 10  # 24 elements
        hourly_consumption = [4.0] * 24
        controller.solar_forecast = hourly_to_quarterly(hourly_solar)  # 96 elements
        controller.consumption_forecast = hourly_to_quarterly(hourly_consumption)  # 96 elements

        # POPULATE HISTORICAL DATA for past hours
        populate_historical_data(quarterly_battery_system, 0, current_hour - 1)

        # Execute workflow with explicit current_period
        success = quarterly_battery_system.update_battery_schedule(
            current_period=current_period, prepare_next_day=False
        )
        assert success, "Should complete forecast to optimization workflow"

        # Verify optimization results stored
        latest_schedule = quarterly_battery_system.schedule_store.get_latest_schedule()
        assert latest_schedule is not None, "Should store optimization results"

        # Verify data consistency - quarterly resolution means 96 periods per day
        period_data = latest_schedule.optimization_result.period_data
        expected_periods = 96 - current_period  # Remaining periods in day
        assert (
            len(period_data) == expected_periods
        ), f"Should have {expected_periods} quarterly periods of schedule data"

        # Verify all periods have PeriodData structure
        for i, period in enumerate(period_data):
            assert isinstance(period, PeriodData), f"Period {i} should be PeriodData"


#           expected_hour = current_hour + i
#            assert hour_data.hour == expected_hour, f"Hourly data index {i} should be for hour {expected_hour}, got hour {hour_data.hour}"


class TestDailyViewGeneration:
    """Test daily view generation and data combination."""

    def test_daily_view_creation(self, quarterly_battery_system):
        """Test daily view generation uses PeriodData throughout."""
        current_hour = 12
        current_period = current_hour * 4  # Convert to quarterly periods

        # POPULATE HISTORICAL DATA for past hours
        populate_historical_data(quarterly_battery_system, 0, current_hour - 1)

        # Create schedule for future hours with explicit current_period
        success = quarterly_battery_system.update_battery_schedule(
            current_period=current_period, prepare_next_day=False
        )
        assert success, "Should create schedule"

        # Get daily view with explicit current period (no more real-time dependency!)
        daily_view = quarterly_battery_system.get_current_daily_view(current_period=current_period)
        assert daily_view is not None, "Should return daily view"
        assert len(daily_view.periods) == 96, "Should have complete 96-period view"

        # Verify data sources are correctly marked
        actual_count = sum(
            1 for h in daily_view.periods if h.data_source == "actual"
        )
        predicted_count = sum(
            1 for h in daily_view.periods if h.data_source == "predicted"
        )

        expected_actual = current_hour * 4  # Convert hours to periods
        expected_predicted = 96 - expected_actual
        assert actual_count == expected_actual, f"Should have {expected_actual} actual periods"
        assert (
            predicted_count == expected_predicted
        ), f"Should have {expected_predicted} predicted periods"

        # Verify period data structure
        for i, period_data in enumerate(daily_view.periods):
            assert isinstance(period_data, PeriodData), f"Period {i} should be PeriodData"
            assert period_data.period == i, f"Period {i} should have correct period number"

            if i < expected_actual:
                assert period_data.data_source == "actual", f"Period {i} should be actual"
            else:
                assert (
                    period_data.data_source == "predicted"
                ), f"Period {i} should be predicted"

    def test_daily_view_with_mixed_data_sources(
        self, quarterly_battery_system, sample_new_hourly_data
    ):
        """Test daily view with mixed actual/predicted data sources."""
        current_hour = 14
        current_period = current_hour * 4  # Convert to quarterly periods

        # POPULATE HISTORICAL DATA for past hours
        populate_historical_data(quarterly_battery_system, 0, current_hour - 1)

        # Create schedule for future hours with explicit current_period
        success = quarterly_battery_system.update_battery_schedule(
            current_period=current_period, prepare_next_day=False
        )
        assert success, "Should create schedule from hour 14"

        # Generate daily view with explicit current period
        daily_view = quarterly_battery_system.daily_view_builder.build_daily_view(
            current_period=current_period
        )

        # Verify data sources are correctly marked
        expected_actual_periods = current_hour * 4
        assert (
            daily_view.actual_count == expected_actual_periods
        ), f"Should have {expected_actual_periods} actual periods"
        expected_predicted_periods = (24 - current_hour) * 4
        assert (
            daily_view.predicted_count == expected_predicted_periods
        ), f"Should have {expected_predicted_periods} predicted periods"

        # Verify data source annotations
        expected_actual_periods = current_hour * 4
        for i, period_data in enumerate(daily_view.periods):
            if i < expected_actual_periods:
                assert period_data.data_source == "actual", f"Period {i} should be actual"
            else:
                assert (
                    period_data.data_source == "predicted"
                ), f"Period {i} should be predicted"

    def test_daily_view_economic_calculations(self, quarterly_battery_system):
        """Test that daily view includes proper economic calculations."""
        current_hour = 10
        current_period = current_hour * 4  # Convert to quarterly periods

        # POPULATE HISTORICAL DATA for past hours
        populate_historical_data(quarterly_battery_system, 0, current_hour - 1)

        # Create schedule with explicit current_period
        success = quarterly_battery_system.update_battery_schedule(
            current_period=current_period, prepare_next_day=False
        )
        assert success, "Should create schedule"

        # Get daily view with explicit current period
        daily_view = quarterly_battery_system.get_current_daily_view(
            current_period=current_period
        )

        # Verify economic metrics
        assert isinstance(
            daily_view.total_savings, int | float
        ), "Total savings should be numeric"

        # Verify period counts
        assert daily_view.actual_count >= 0, "Actual count should be non-negative"
        assert daily_view.predicted_count >= 0, "Predicted count should be non-negative"
        assert len(daily_view.periods) == daily_view.actual_count + daily_view.predicted_count, \
            "Total periods should equal actual + predicted counts"


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
                current_period=0, prepare_next_day=True
            )
            # Should either succeed with default values or fail gracefully
            assert isinstance(success, bool), "Should return boolean result"
        finally:
            # Restore original data
            controller.solar_forecast = original_solar


class TestPerformanceWorkflows:
    """Test performance-critical workflows."""

    def test_optimization_performance(self, quarterly_battery_system):
        """Test that optimization completes in reasonable time."""
        import time

        current_hour = 8
        current_period = current_hour * 4  # Convert to quarterly periods

        # POPULATE HISTORICAL DATA for past hours
        populate_historical_data(quarterly_battery_system, 0, current_hour - 1)

        # Time the optimization with explicit current_period
        start_time = time.time()
        success = quarterly_battery_system.update_battery_schedule(
            current_period=current_period, prepare_next_day=False
        )
        end_time = time.time()

        assert success, "Optimization should complete successfully"

        optimization_time = end_time - start_time
        # Quarterly resolution (96 periods) takes longer than hourly (24 periods)
        # Dynamic programming complexity is O(T * S * A) where T=periods, S=states, A=actions
        # 96 periods vs 24 periods = 4x more work, so 30s is reasonable for quarterly resolution
        assert (
            optimization_time < 30.0
        ), f"Optimization should complete in under 30 seconds, took {optimization_time:.2f}s"

        # Verify result quality with explicit current hour
        latest_schedule = (
            quarterly_battery_system.schedule_store.get_latest_schedule()
        )
        assert latest_schedule is not None, "Should produce valid schedule"

        economic_summary = latest_schedule.optimization_result.economic_summary
        assert (
            economic_summary.grid_to_battery_solar_savings >= 0
        ), "Should show non-negative savings"


class TestDataFlowValidation:
    """Test data flow consistency and validation."""

    def test_end_to_end_data_consistency(self, quarterly_battery_system):
        """Test data consistency from input to output."""
        current_hour = 8
        current_period = current_hour * 4  # Convert to quarterly periods

        # POPULATE HISTORICAL DATA
        populate_historical_data(quarterly_battery_system, 0, current_hour - 1)

        # Execute complete workflow with explicit current_period
        success = quarterly_battery_system.update_battery_schedule(
            current_period=current_period, prepare_next_day=False
        )
        assert success, "Should complete workflow"

        # Get data at different stages with explicit current hour
        latest_schedule = (
            quarterly_battery_system.schedule_store.get_latest_schedule()
        )
        daily_view = quarterly_battery_system.get_current_daily_view(
            current_period=current_period
        )

        # Verify consistency between schedule and daily view
        schedule_data = latest_schedule.optimization_result.period_data
        predicted_view_data = [
            h for h in daily_view.periods if h.data_source == "predicted"
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
                sched_hour, PeriodData
            ), f"Schedule hour {i} should be PeriodData"
            assert isinstance(
                view_hour, PeriodData
            ), f"View hour {i} should be PeriodData"

    def test_decision_intent_propagation(self, quarterly_battery_system):
        """Test that strategic intents propagate correctly through the system."""
        current_hour = 8
        current_period = current_hour * 4  # Convert to quarterly periods

        # POPULATE HISTORICAL DATA for past hours
        populate_historical_data(quarterly_battery_system, 0, current_hour - 1)

        success = quarterly_battery_system.update_battery_schedule(
            current_period=current_period, prepare_next_day=False
        )
        assert success, "Should create schedule"

        # Get strategic intents from different sources with explicit current hour
        latest_schedule = (
            quarterly_battery_system.schedule_store.get_latest_schedule()
        )
        schedule_intents = [
            h.decision.strategic_intent
            for h in latest_schedule.optimization_result.period_data
        ]

        daily_view = quarterly_battery_system.get_current_daily_view(
            current_period=current_period
        )
        predicted_view_intents = [
            h.decision.strategic_intent
            for h in daily_view.periods
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
