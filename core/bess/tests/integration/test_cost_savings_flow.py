"""Integration tests for cost/savings flow validation.

Tests the complete flow from optimization through daily view to dashboard API
to ensure cost and savings calculations are correct after the SOE migration.
"""

import pytest

from backend.api_dataclasses import flatten_hourly_data
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.settings import BatterySettings


class TestCostSavingsFlow:
    """Test complete cost/savings flow from optimization to API."""
    
    @pytest.fixture
    def test_scenario_data(self):
        """Provide test scenario with significant cost differences."""
        return {
            "buy_prices": [0.30, 0.20, 0.10, 0.10, 0.20, 1.50, 2.80, 3.50, 0.80, 0.40, 
                          0.30, 0.20, 0.10, 0.40, 2.00, 3.00, 3.80, 4.00, 3.50, 2.80, 
                          1.50, 0.70, 0.40, 0.30],
            "sell_prices": [0.30, 0.20, 0.10, 0.10, 0.20, 1.50, 2.80, 3.50, 0.80, 0.40, 
                           0.30, 0.20, 0.10, 0.40, 2.00, 3.00, 3.80, 4.00, 3.50, 2.80, 
                           1.50, 0.70, 0.40, 0.30],
            "consumption": [0.8, 0.7, 0.6, 0.5, 0.5, 0.7, 1.5, 2.5, 3.0, 2.0, 
                           1.5, 2.0, 2.5, 1.8, 2.0, 2.5, 3.5, 4.5, 5.0, 4.5, 
                           3.5, 2.5, 1.5, 1.0],
            "solar": [0.0, 0.0, 0.0, 0.0, 0.0, 0.1, 0.3, 0.7, 1.2, 0.5, 
                     2.5, 0.8, 3.0, 1.5, 2.8, 0.6, 1.2, 0.7, 0.3, 0.1, 
                     0.0, 0.0, 0.0, 0.0],
            "initial_soe": 3.0,
            "initial_cost_basis": 0.4
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
        assert optimization_result.economic_summary.grid_to_battery_solar_savings > 0, \
            "Optimization should produce positive savings"
        assert optimization_result.economic_summary.grid_only_cost > 0, \
            "Grid-only cost should be positive"
        # Note: battery_solar_cost can be negative when the system makes money
        # by buying cheap and selling expensive - this is expected behavior
    
    def test_daily_view_shows_positive_savings(self, optimization_result, test_scenario_data):
        """Test that daily view shows positive savings (core issue that was fixed)."""
        # Create battery system manager
        manager = BatterySystemManager()
        
        # Store optimization result
        manager.schedule_store.store_schedule(
            optimization_result=optimization_result,
            optimization_hour=0,
            scenario="test",
        )
        
        # Create daily view
        daily_view = manager.daily_view_builder.build_daily_view(
            current_hour=0,
            buy_price=test_scenario_data["buy_prices"],
            sell_price=test_scenario_data["sell_prices"]
        )
        
        # Check that daily view shows positive savings (this was the main issue)
        assert daily_view.total_daily_savings > 0, \
            f"Daily view should show positive savings, got {daily_view.total_daily_savings}"
    
    def test_dashboard_api_provides_required_fields(self, optimization_result, test_scenario_data):
        """Test that dashboard API provides required fields with non-zero totals."""
        # Create battery system manager
        manager = BatterySystemManager()
        
        # Store optimization result
        manager.schedule_store.store_schedule(
            optimization_result=optimization_result,
            optimization_hour=0,
            scenario="test",
        )
        
        # Create daily view
        daily_view = manager.daily_view_builder.build_daily_view(
            current_hour=0,
            buy_price=test_scenario_data["buy_prices"],
            sell_price=test_scenario_data["sell_prices"]
        )
        
        # Test API data flattening
        flattened_data = [flatten_hourly_data(hourly, 30.0) for hourly in daily_view.hourly_data]
        
        # Check that all required fields are present
        required_fields = ["gridOnlyCost", "batterySolarCost", "solarSavings", "hour"]
        for hour_data in flattened_data[:3]:  # Check first 3 hours
            for field in required_fields:
                assert field in hour_data, f"Field {field} missing from flattened data"
        
        # Check that grid-only cost totals are positive (this was the main issue)
        total_grid_only_cost = sum(hour.get("gridOnlyCost", 0) for hour in flattened_data)
        assert total_grid_only_cost > 0, f"Total grid-only cost should be positive, got {total_grid_only_cost}"
        
        # Check that total savings are positive
        total_solar_savings = sum(hour.get("solarSavings", 0) for hour in flattened_data)
        assert total_solar_savings > 0, f"Total solar savings should be positive, got {total_solar_savings}"
    
    def test_battery_soe_data_within_limits(self, optimization_result, test_scenario_data):
        """Test that battery SOE data stays within physical limits."""
        # Create battery system manager
        manager = BatterySystemManager()
        
        # Store optimization result
        manager.schedule_store.store_schedule(
            optimization_result=optimization_result,
            optimization_hour=0,
            scenario="test",
        )
        
        # Create daily view
        daily_view = manager.daily_view_builder.build_daily_view(
            current_hour=0,
            buy_price=test_scenario_data["buy_prices"],
            sell_price=test_scenario_data["sell_prices"]
        )
        
        # Check battery SOE data is within limits
        battery_capacity = 30.0  # kWh from BatterySettings
        
        for hourly in daily_view.hourly_data:
            soe_start = hourly.energy.battery_soe_start
            soe_end = hourly.energy.battery_soe_end
            
            # Verify SOE is within battery limits (with small tolerance for floating point precision)
            assert -0.01 <= soe_start <= battery_capacity + 0.01, \
                f"SOE start {soe_start} kWh outside battery capacity 0-{battery_capacity} kWh"
            assert -0.01 <= soe_end <= battery_capacity + 0.01, \
                f"SOE end {soe_end} kWh outside battery capacity 0-{battery_capacity} kWh"
    
    def test_actual_hours_show_proper_costs(self, optimization_result, test_scenario_data):
        """Test that actual hours with historical data show proper costs (user's reported issue)."""
        from datetime import datetime, timedelta
        
        from core.bess.models import EnergyData
        
        # Create battery system manager
        manager = BatterySystemManager()
        
        # Store optimization result
        manager.schedule_store.store_schedule(
            optimization_result=optimization_result,
            optimization_hour=0,
            scenario="test",
        )
        
        # Simulate historical data for the first 8 hours (like user's scenario)
        base_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Add historical data for hours 0-7 (simulate real sensor data)
        for hour in range(8):
            # Create realistic historical energy data
            historical_energy = EnergyData(
                solar_generated=test_scenario_data["solar"][hour],
                home_consumed=test_scenario_data["consumption"][hour],
                battery_charged=0.5 if hour < 4 else 0.0,  # Some charging in early hours
                battery_discharged=0.0 if hour < 4 else 0.2,  # Some discharging later
                grid_imported=test_scenario_data["consumption"][hour] + (0.5 if hour < 4 else -0.2),
                grid_exported=0.0,
                battery_soe_start=3.0 + hour * 0.3,  # Gradually increasing SOE
                battery_soe_end=3.0 + hour * 0.3 + (0.5 if hour < 4 else -0.2),
            )
            
            # Store in historical data store
            manager.historical_store.record_energy_data(
                hour=hour,
                energy_data=historical_energy,
                data_source="actual",
                timestamp=base_time + timedelta(hours=hour)
            )
        
        # Create daily view with current hour = 8 (like user's scenario)
        daily_view = manager.daily_view_builder.build_daily_view(
            current_hour=8,
            buy_price=test_scenario_data["buy_prices"],
            sell_price=test_scenario_data["sell_prices"]
        )
        
        # Check that the first 8 hours show proper costs (not 0.00)
        for hour in range(8):
            hour_data = daily_view.hourly_data[hour]
            
            # Verify this hour uses actual data
            assert hour_data.data_source == "actual", f"Hour {hour} should be actual data"
            
            # Verify costs are not zero (this is the user's issue)
            assert hour_data.economic.hourly_cost != 0.0, \
                f"Hour {hour} shows 0.00 cost but should have proper cost calculation"
            assert hour_data.economic.grid_only_cost != 0.0, \
                f"Hour {hour} shows 0.00 grid-only cost but should have proper baseline cost"
            assert hour_data.economic.solar_only_cost != 0.0, \
                f"Hour {hour} shows 0.00 solar-only cost but should have proper baseline cost"
            
            # The savings can be negative (battery charging) or positive, but grid-only baseline costs should be positive
            assert hour_data.economic.grid_only_cost > 0, \
                f"Hour {hour} grid-only cost should be positive, got {hour_data.economic.grid_only_cost}"
            # Solar-only cost can be negative when exporting solar (earning money from export)
            # No assertion needed for solar_only_cost as it can be positive, negative, or zero
