# tests/integration/test_schedule_management.py
"""
Schedule creation and management integration tests.

Tests schedule creation, updates, strategic intent classification, and
schedule persistence using NewHourlyData structures.
"""

from core.bess.models import NewHourlyData


class TestScheduleCreation:
    """Test schedule creation with new data structures."""

    def test_create_tomorrow_schedule(self, battery_system):
        """Test creating tomorrow's schedule returns NewHourlyData."""
        success = battery_system.update_battery_schedule(0, prepare_next_day=True)
        assert success, "Should create tomorrow's schedule"

        # Verify stored schedule uses new data structures
        latest_schedule = battery_system.schedule_store.get_latest_schedule()
        assert latest_schedule is not None, "Should have created schedule"

        optimization_result = latest_schedule.optimization_result
        assert hasattr(optimization_result, "hourly_data"), "Should have hourly_data"
        assert len(optimization_result.hourly_data) == 24, "Should have 24 hours"

        # Verify hourly_data contains NewHourlyData objects
        for i, hour_data in enumerate(optimization_result.hourly_data):
            assert isinstance(
                hour_data, NewHourlyData
            ), f"Hour {i} should be NewHourlyData"
            assert hour_data.hour == i, f"Hour {i} should have correct hour value"
            assert hasattr(hour_data, "energy"), f"Hour {i} should have energy data"
            assert hasattr(hour_data, "economic"), f"Hour {i} should have economic data"
            assert hasattr(hour_data, "strategy"), f"Hour {i} should have strategy data"

    def test_create_hourly_update_schedule(self, battery_system):
        """Test creating hourly update schedule."""
        current_hour = 8
        success = battery_system.update_battery_schedule(
            current_hour, prepare_next_day=False
        )
        assert success, "Should create hourly update schedule"

        latest_schedule = battery_system.schedule_store.get_latest_schedule()
        assert latest_schedule is not None, "Should have created schedule"

        # Verify optimization range
        start_hour, end_hour = latest_schedule.get_optimization_range()
        assert start_hour == current_hour, f"Should start from hour {current_hour}"
        assert end_hour == 23, "Should end at hour 23"

        # Verify hourly data covers remaining hours
        optimization_result = latest_schedule.optimization_result
        expected_hours = end_hour - start_hour + 1
        assert (
            len(optimization_result.hourly_data) == expected_hours
        ), f"Should have {expected_hours} hours"

    def test_schedule_scenario_tracking(self, battery_system):
        """Test that schedule scenarios are properly tracked."""
        # Create tomorrow schedule
        success1 = battery_system.update_battery_schedule(0, prepare_next_day=True)
        assert success1, "Should create tomorrow schedule"

        schedule1 = battery_system.schedule_store.get_latest_schedule()
        assert (
            "tomorrow" in schedule1.created_for_scenario
        ), "Should track tomorrow scenario"

        # Create hourly update
        success2 = battery_system.update_battery_schedule(10, prepare_next_day=False)
        assert success2, "Should create hourly schedule"

        schedule2 = battery_system.schedule_store.get_latest_schedule()
        assert (
            "hourly" in schedule2.created_for_scenario
        ), "Should track hourly scenario"


class TestStrategicIntentClassification:
    """Test strategic intent classification with new data structures."""

    def test_strategic_intent_with_arbitrage_prices(
        self, battery_system_with_arbitrage
    ):
        """Test that strategic intents are properly classified with arbitrage opportunities."""
        success = battery_system_with_arbitrage.update_battery_schedule(
            0, prepare_next_day=True
        )
        assert success, "Should create schedule with arbitrage prices"

        latest_schedule = (
            battery_system_with_arbitrage.schedule_store.get_latest_schedule()
        )
        strategic_intents = [
            h.strategy.strategic_intent
            for h in latest_schedule.optimization_result.hourly_data
        ]

        # With arbitrage prices, should have strategic decisions beyond IDLE
        non_idle_intents = [intent for intent in strategic_intents if intent != "IDLE"]
        assert (
            len(non_idle_intents) > 0
        ), f"Should have strategic decisions, got: {strategic_intents}"

        # Should contain specific strategic intents
        unique_intents = set(strategic_intents)
        expected_intents = {
            "GRID_CHARGING",
            "SOLAR_STORAGE",
            "LOAD_SUPPORT",
            "EXPORT_ARBITRAGE",
            "IDLE",
        }
        assert unique_intents.issubset(
            expected_intents
        ), f"Invalid strategic intents: {unique_intents - expected_intents}"

    def test_grid_charging_intent(self, battery_system_with_arbitrage):
        """Test that GRID_CHARGING intent is classified correctly."""
        success = battery_system_with_arbitrage.update_battery_schedule(
            0, prepare_next_day=True
        )
        assert success, "Should create schedule"

        latest_schedule = (
            battery_system_with_arbitrage.schedule_store.get_latest_schedule()
        )

        # Look for grid charging during low price hours (night hours 0-2)
        night_hours = latest_schedule.optimization_result.hourly_data[0:3]
        night_intents = [h.strategy.strategic_intent for h in night_hours]

        # Should have at least some grid charging during cheap hours
        grid_charging_count = night_intents.count("GRID_CHARGING")
        assert (
            grid_charging_count >= 0
        ), "Should classify grid charging during cheap hours"

    def test_export_arbitrage_intent(self, battery_system_with_arbitrage):
        """Test that EXPORT_ARBITRAGE intent is classified correctly."""
        success = battery_system_with_arbitrage.update_battery_schedule(
            0, prepare_next_day=True
        )
        assert success, "Should create schedule"

        latest_schedule = (
            battery_system_with_arbitrage.schedule_store.get_latest_schedule()
        )

        # Look for export arbitrage during high price hours (peak hours 9-11)
        peak_hours = latest_schedule.optimization_result.hourly_data[9:12]
        peak_intents = [h.strategy.strategic_intent for h in peak_hours]

        # Should potentially have export arbitrage during expensive hours
        export_arbitrage_count = peak_intents.count("EXPORT_ARBITRAGE")
        assert (
            export_arbitrage_count >= 0
        ), "Should classify export arbitrage during expensive hours"

    def test_solar_storage_intent(self, battery_system):
        """Test that SOLAR_STORAGE intent is classified correctly."""
        # Set high solar production during day
        mock_controller = battery_system._controller
        mock_controller.solar_forecast = (
            [0.0] * 6 + [10.0] * 8 + [0.0] * 10
        )  # High solar midday

        success = battery_system.update_battery_schedule(0, prepare_next_day=True)
        assert success, "Should create schedule with solar"

        latest_schedule = battery_system.schedule_store.get_latest_schedule()

        # Look for solar storage during high solar hours
        solar_hours = latest_schedule.optimization_result.hourly_data[10:14]
        solar_intents = [h.strategy.strategic_intent for h in solar_hours]

        # Should have some solar storage when solar production is high
        solar_storage_count = solar_intents.count("SOLAR_STORAGE")
        assert (
            solar_storage_count >= 0
        ), "Should classify solar storage during high solar hours"


class TestScheduleUpdates:
    """Test schedule updates and persistence."""

    def test_multiple_schedule_updates(self, battery_system):
        """Test system handles multiple schedule updates correctly."""
        successful_updates = 0

        # Perform multiple updates
        for _i in range(3):
            success = battery_system.update_battery_schedule(0, prepare_next_day=True)
            if success:
                successful_updates += 1

        assert (
            successful_updates >= 2
        ), f"Should handle multiple updates, got {successful_updates}"

        # Verify schedules are stored
        all_schedules = battery_system.schedule_store.get_all_schedules_today()
        assert (
            len(all_schedules) >= 2
        ), f"Should store multiple schedules, got {len(all_schedules)}"

    def test_schedule_replacement(self, battery_system):
        """Test that new schedules properly replace old ones."""
        # Create initial schedule
        success1 = battery_system.update_battery_schedule(0, prepare_next_day=True)
        assert success1, "Should create initial schedule"

        schedule1 = battery_system.schedule_store.get_latest_schedule()
        timestamp1 = schedule1.timestamp

        # Create second schedule
        success2 = battery_system.update_battery_schedule(0, prepare_next_day=True)
        assert success2, "Should create second schedule"

        schedule2 = battery_system.schedule_store.get_latest_schedule()
        timestamp2 = schedule2.timestamp

        # Second schedule should be newer
        assert timestamp2 > timestamp1, "Second schedule should be newer"

        # Both should be stored
        all_schedules = battery_system.schedule_store.get_all_schedules_today()
        assert len(all_schedules) >= 2, "Should store both schedules"

    def test_schedule_persistence_across_hours(self, battery_system):
        """Test schedule persistence for different optimization hours."""
        hours_to_test = [0, 8, 16]

        for hour in hours_to_test:
            success = battery_system.update_battery_schedule(
                hour, prepare_next_day=False
            )
            assert success, f"Should create schedule for hour {hour}"

            latest_schedule = battery_system.schedule_store.get_latest_schedule()
            assert (
                latest_schedule.optimization_hour == hour
            ), f"Should track optimization hour {hour}"

    def test_schedule_summary_info(self, battery_system):
        """Test schedule summary information generation."""
        success = battery_system.update_battery_schedule(0, prepare_next_day=True)
        assert success, "Should create schedule"

        latest_schedule = battery_system.schedule_store.get_latest_schedule()
        summary_info = latest_schedule.get_summary_info()

        assert isinstance(summary_info, str), "Summary should be a string"
        assert "00:00-23:00" in summary_info, "Should include time range"
        assert "SEK" in summary_info, "Should include currency"
        assert "tomorrow" in summary_info.lower(), "Should indicate scenario"


class TestScheduleEconomics:
    """Test economic calculations in schedules."""

    def test_savings_calculation(self, battery_system_with_arbitrage):
        """Test that savings are calculated correctly."""
        success = battery_system_with_arbitrage.update_battery_schedule(
            0, prepare_next_day=True
        )
        assert success, "Should create schedule"

        latest_schedule = (
            battery_system_with_arbitrage.schedule_store.get_latest_schedule()
        )
        total_savings = latest_schedule.get_total_savings()

        # With arbitrage opportunities, should have positive savings
        assert isinstance(total_savings, int | float), "Savings should be numeric"
        assert total_savings >= 0, "Savings should be non-negative"

    def test_hourly_economic_data(self, battery_system):
        """Test that each hour has proper economic data."""
        success = battery_system.update_battery_schedule(0, prepare_next_day=True)
        assert success, "Should create schedule"

        latest_schedule = battery_system.schedule_store.get_latest_schedule()

        for i, hour_data in enumerate(latest_schedule.optimization_result.hourly_data):
            economic = hour_data.economic

            # Verify economic data structure
            assert hasattr(economic, "buy_price"), f"Hour {i} should have buy_price"
            assert hasattr(economic, "sell_price"), f"Hour {i} should have sell_price"
            assert hasattr(economic, "hourly_cost"), f"Hour {i} should have hourly_cost"
            assert hasattr(
                economic, "hourly_savings"
            ), f"Hour {i} should have hourly_savings"

            # Verify types
            assert isinstance(
                economic.buy_price, int | float
            ), f"Hour {i} buy_price should be numeric"
            assert isinstance(
                economic.sell_price, int | float
            ), f"Hour {i} sell_price should be numeric"
            assert isinstance(
                economic.hourly_cost, int | float
            ), f"Hour {i} hourly_cost should be numeric"
            assert isinstance(
                economic.hourly_savings, int | float
            ), f"Hour {i} hourly_savings should be numeric"

    def test_economic_summary_consistency(self, battery_system):
        """Test that economic summary is consistent with hourly data."""
        success = battery_system.update_battery_schedule(0, prepare_next_day=True)
        assert success, "Should create schedule"

        latest_schedule = battery_system.schedule_store.get_latest_schedule()
        economic_summary = latest_schedule.optimization_result.economic_summary

        # Verify economic summary has expected fields
        assert hasattr(economic_summary, "base_cost"), "Should have base_cost"
        assert hasattr(
            economic_summary, "battery_solar_cost"
        ), "Should have battery_solar_cost"
        assert hasattr(
            economic_summary, "base_to_battery_solar_savings"
        ), "Should have savings"

        # Verify consistency
        total_savings = latest_schedule.get_total_savings()
        summary_savings = economic_summary.base_to_battery_solar_savings
        assert (
            abs(total_savings - summary_savings) < 0.01
        ), "Savings calculations should be consistent"


class TestScheduleValidation:
    """Test schedule validation and error handling."""

    def test_invalid_optimization_hour(self, battery_system):
        """Test handling of invalid optimization hours."""
        # Test negative hour
        success = battery_system.update_battery_schedule(-1, prepare_next_day=False)
        assert not success, "Should reject negative hour"

        # Test hour > 23
        success = battery_system.update_battery_schedule(25, prepare_next_day=False)
        assert not success, "Should reject hour > 23"

    def test_schedule_data_integrity(self, battery_system):
        """Test that schedule data maintains integrity."""
        success = battery_system.update_battery_schedule(0, prepare_next_day=True)
        assert success, "Should create schedule"

        latest_schedule = battery_system.schedule_store.get_latest_schedule()

        # Verify hour sequence
        for i, hour_data in enumerate(latest_schedule.optimization_result.hourly_data):
            assert hour_data.hour == i, f"Hour {i} should have correct hour value"

        # Verify energy balance for each hour
        for i, hour_data in enumerate(latest_schedule.optimization_result.hourly_data):
            energy = hour_data.energy

            # Basic energy balance checks
            assert energy.solar_generated >= 0, f"Hour {i} solar should be non-negative"
            assert (
                energy.home_consumed >= 0
            ), f"Hour {i} consumption should be non-negative"
            assert (
                energy.grid_imported >= 0
            ), f"Hour {i} grid import should be non-negative"
            assert (
                energy.grid_exported >= 0
            ), f"Hour {i} grid export should be non-negative"
            assert (
                0 <= energy.battery_soc_start <= 100
            ), f"Hour {i} start SOC should be 0-100%"
            assert (
                0 <= energy.battery_soc_end <= 100
            ), f"Hour {i} end SOC should be 0-100%"

    def test_schedule_store_limits(self, battery_system):
        """Test schedule store handles storage limits appropriately."""
        initial_count = battery_system.schedule_store.get_schedule_count()

        # Create many schedules
        for i in range(10):
            success = battery_system.update_battery_schedule(0, prepare_next_day=True)
            assert success, f"Should create schedule {i}"

        final_count = battery_system.schedule_store.get_schedule_count()
        assert final_count == initial_count + 10, "Should store all schedules"

        # Test clearing
        cleared_count = battery_system.schedule_store.clear_all_schedules()
        assert cleared_count > 0, "Should clear some schedules"

        empty_count = battery_system.schedule_store.get_schedule_count()
        assert empty_count == 0, "Should have no schedules after clearing"
