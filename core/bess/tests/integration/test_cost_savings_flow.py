"""Integration tests for cost/savings flow validation.

Tests the complete flow from optimization through daily view
to ensure cost and savings calculations are correct after the SOE migration.
"""

import pytest  # type: ignore

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.models import DecisionData, EconomicData, PeriodData
from core.bess.settings import BatterySettings


class TestCostSavingsFlow:
    """Test complete cost/savings flow from optimization to API."""

    @pytest.fixture
    def test_scenario_data(self):
        """Provide test scenario with significant cost differences."""
        return {
            "buy_prices": [
                0.30,
                0.20,
                0.10,
                0.10,
                0.20,
                1.50,
                2.80,
                3.50,
                0.80,
                0.40,
                0.30,
                0.20,
                0.10,
                0.40,
                2.00,
                3.00,
                3.80,
                4.00,
                3.50,
                2.80,
                1.50,
                0.70,
                0.40,
                0.30,
            ],
            "sell_prices": [
                0.30,
                0.20,
                0.10,
                0.10,
                0.20,
                1.50,
                2.80,
                3.50,
                0.80,
                0.40,
                0.30,
                0.20,
                0.10,
                0.40,
                2.00,
                3.00,
                3.80,
                4.00,
                3.50,
                2.80,
                1.50,
                0.70,
                0.40,
                0.30,
            ],
            "consumption": [
                0.8,
                0.7,
                0.6,
                0.5,
                0.5,
                0.7,
                1.5,
                2.5,
                3.0,
                2.0,
                1.5,
                2.0,
                2.5,
                1.8,
                2.0,
                2.5,
                3.5,
                4.5,
                5.0,
                4.5,
                3.5,
                2.5,
                1.5,
                1.0,
            ],
            "solar": [
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.1,
                0.3,
                0.7,
                1.2,
                0.5,
                2.5,
                0.8,
                3.0,
                1.5,
                2.8,
                0.6,
                1.2,
                0.7,
                0.3,
                0.1,
                0.0,
                0.0,
                0.0,
                0.0,
            ],
            "initial_soe": 3.0,
            "initial_cost_basis": 0.4,
        }

    @pytest.fixture
    def optimization_result(self, test_scenario_data):
        """Create optimization result from test scenario."""
        battery_settings = BatterySettings()

        return optimize_battery_schedule(
            buy_price=test_scenario_data["buy_prices"],
            sell_price=test_scenario_data["sell_prices"],
            home_consumption=test_scenario_data["consumption"],
            solar_production=test_scenario_data["solar"],
            initial_soe=test_scenario_data["initial_soe"],
            battery_settings=battery_settings,
            initial_cost_basis=test_scenario_data["initial_cost_basis"],
        )

    def test_optimization_produces_positive_savings(self, optimization_result):
        """Test that optimization produces positive savings."""
        assert (
            optimization_result.economic_summary.grid_to_battery_solar_savings > 0
        ), "Optimization should produce positive savings"
        assert (
            optimization_result.economic_summary.grid_only_cost > 0
        ), "Grid-only cost should be positive"
        # Note: battery_solar_cost can be negative when the system makes money
        # by buying cheap and selling expensive - this is expected behavior

    def test_daily_view_shows_positive_savings(
        self, optimization_result, test_scenario_data
    ):
        """Test that daily view shows positive savings (core issue that was fixed)."""
        from core.bess.tests.conftest import MockHomeAssistantController

        manager = BatterySystemManager(controller=MockHomeAssistantController())

        # Store optimization result
        manager.schedule_store.store_schedule(
            optimization_result=optimization_result,
            optimization_period=0,
        )

        # Create daily view
        daily_view = manager.daily_view_builder.build_daily_view(
            current_period=0,
        )

        # Check that daily view shows positive savings (this was the main issue)
        assert (
            daily_view.total_savings > 0
        ), f"Daily view should show positive savings, got {daily_view.total_savings}"

    def test_dashboard_api_provides_required_fields(
        self, optimization_result, test_scenario_data
    ):
        """Test that dashboard API provides required fields with non-zero totals."""
        from core.bess.tests.conftest import MockHomeAssistantController

        manager = BatterySystemManager(controller=MockHomeAssistantController())

        # Store optimization result
        manager.schedule_store.store_schedule(
            optimization_result=optimization_result,
            optimization_period=0,
        )

        # Create daily view
        daily_view = manager.daily_view_builder.build_daily_view(
            current_period=0,
        )

        # Test core data structures directly (no API conversion needed)
        hourly_data = daily_view.periods

        # Check that all required core fields are present
        for hour_idx, hour_data in enumerate(hourly_data[:3]):  # Check first 3 hours
            assert hasattr(hour_data, "period"), f"Hour {hour_idx}: Missing hour field"
            assert hasattr(
                hour_data, "economic"
            ), f"Hour {hour_idx}: Missing economic field"
            assert hasattr(
                hour_data.economic, "grid_cost"
            ), f"Hour {hour_idx}: Missing grid_cost in economic"
            assert hasattr(
                hour_data.economic, "hourly_cost"
            ), f"Hour {hour_idx}: Missing hourly_cost in economic"
            assert hasattr(
                hour_data.economic, "battery_cycle_cost"
            ), f"Hour {hour_idx}: Missing battery_cycle_cost in economic"

        # Check that grid costs are reasonable (this was the main issue)
        total_grid_costs = sum(hour.economic.grid_cost for hour in hourly_data)
        total_hourly_costs = sum(hour.economic.hourly_cost for hour in hourly_data)

        assert (
            abs(total_grid_costs) > 0.01
        ), f"Total grid costs should be non-zero, got {total_grid_costs}"
        assert (
            abs(total_hourly_costs) > 0.01
        ), f"Total hourly costs should be non-zero, got {total_hourly_costs}"

        # Check that battery cycle costs are calculated
        total_battery_costs = sum(
            hour.economic.battery_cycle_cost for hour in hourly_data
        )
        assert (
            total_battery_costs >= 0
        ), f"Total battery costs should be non-negative, got {total_battery_costs}"

    def test_battery_soe_data_within_limits(
        self, optimization_result, test_scenario_data
    ):
        """Test that battery SOE data stays within physical limits."""
        from core.bess.tests.conftest import MockHomeAssistantController

        manager = BatterySystemManager(controller=MockHomeAssistantController())

        # Store optimization result
        manager.schedule_store.store_schedule(
            optimization_result=optimization_result,
            optimization_period=0,
        )

        # Create daily view
        daily_view = manager.daily_view_builder.build_daily_view(
            current_period=0,
        )

        # Check battery SOE data is within limits
        battery_capacity = 30.0  # kWh from BatterySettings

        for hourly in daily_view.periods:
            soe_start = hourly.energy.battery_soe_start
            soe_end = hourly.energy.battery_soe_end

            # Verify SOE is within battery limits (with small tolerance for floating point precision)
            assert (
                -0.01 <= soe_start <= battery_capacity + 0.01
            ), f"SOE start {soe_start} kWh outside battery capacity 0-{battery_capacity} kWh"
            assert (
                -0.01 <= soe_end <= battery_capacity + 0.01
            ), f"SOE end {soe_end} kWh outside battery capacity 0-{battery_capacity} kWh"

    def test_actual_hours_show_proper_costs(
        self, optimization_result, test_scenario_data
    ):
        """Test that actual hours with historical data show proper costs (user's reported issue)."""
        from datetime import datetime, timedelta

        from core.bess.models import EnergyData
        from core.bess.tests.conftest import MockHomeAssistantController

        manager = BatterySystemManager(controller=MockHomeAssistantController())

        # Store optimization result
        manager.schedule_store.store_schedule(
            optimization_result=optimization_result,
            optimization_period=0,
        )

        # Simulate historical data for the first 8 hours (32 quarterly periods)
        base_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        # Add historical data for periods 0-31 (simulate real sensor data at 15-min intervals)
        for period_index in range(32):
            hour = period_index // 4  # Which hour this period belongs to

            # Create realistic historical energy data (scaled to 15-min period)
            # Divide hourly values by 4 to get quarterly energy
            historical_energy = EnergyData(
                solar_production=test_scenario_data["solar"][hour] / 4,
                home_consumption=test_scenario_data["consumption"][hour] / 4,
                battery_charged=(0.5 / 4 if hour < 4 else 0.0),
                battery_discharged=(0.0 if hour < 4 else 0.2 / 4),
                grid_imported=(test_scenario_data["consumption"][hour] + (0.5 if hour < 4 else -0.2)) / 4,
                grid_exported=0.0,
                battery_soe_start=3.0 + period_index * 0.075,  # Gradual SOE change
                battery_soe_end=3.0 + (period_index + 1) * 0.075,
            )

            # Create economic data from energy flows using standard calculation
            economic_data = EconomicData.from_energy_data(
                energy_data=historical_energy,
                buy_price=test_scenario_data["buy_prices"][hour],
                sell_price=test_scenario_data["sell_prices"][hour],
                battery_cycle_cost=0.0,  # No cycle cost for actual historical data
            )

            # Create full PeriodData for this quarterly period
            period_data = PeriodData(
                period=period_index,  # Consecutive periods: 0, 1, 2, 3...31
                energy=historical_energy,
                timestamp=base_time + timedelta(minutes=period_index * 15),
                data_source="actual",
                economic=economic_data,
                decision=DecisionData(),
            )

            # Store consecutive periods
            manager.historical_store.record_period(
                period_index=period_index,
                period_data=period_data,
            )

        # Create daily view at current period = 32 (8:00 AM = 8 hours * 4 periods/hour)
        daily_view = manager.daily_view_builder.build_daily_view(
            current_period=32,  # Period 32 = 8:00 AM
        )

        # Check that the first 32 periods (8 hours) show proper costs (not 0.00)
        # We stored consecutive quarterly periods 0-31
        for period_index in range(32):
            # Find the period data in daily_view.periods by matching period index
            period_data = next(
                (p for p in daily_view.periods if p.period == period_index),
                None
            )

            assert period_data is not None, f"Period {period_index} not found in daily view"

            # Verify this period uses actual data
            assert (
                period_data.data_source == "actual"
            ), f"Period {period_index} should be actual data"

            # Verify costs are not zero (this is the user's issue)
            assert (
                period_data.economic.hourly_cost != 0.0
            ), f"Period {period_index} shows 0.00 cost but should have proper cost calculation"
            assert (
                period_data.economic.grid_only_cost != 0.0
            ), f"Period {period_index} shows 0.00 grid-only cost but should have proper baseline cost"
            assert (
                period_data.economic.solar_only_cost != 0.0
            ), f"Period {period_index} shows 0.00 solar-only cost but should have proper baseline cost"

            # The savings can be negative (battery charging) or positive, but grid-only baseline costs should be positive
            assert (
                period_data.economic.grid_only_cost > 0
            ), f"Period {period_index} grid-only cost should be positive, got {period_data.economic.grid_only_cost}"
            # Solar-only cost can be negative when exporting solar (earning money from export)
            # No assertion needed for solar_only_cost as it can be positive, negative, or zero
