"""
Unit tests for new hierarchical data models.

Tests the new EnergyData, EconomicData, StrategyData, and NewHourlyData structures
that will replace the existing data structures during migration.
"""

from datetime import datetime

from core.bess.models import EconomicData, EnergyData, NewHourlyData, StrategyData


class TestEnergyData:
    """Test EnergyData - pure energy flow data structure."""

    def test_creation_and_basic_properties(self):
        """Test basic EnergyData creation and properties."""
        energy = EnergyData(
            solar_generated=5.0,
            home_consumed=3.0,
            grid_imported=1.0,
            grid_exported=2.0,
            battery_charged=1.5,
            battery_discharged=0.0,
            battery_soc_start=45.0,
            battery_soc_end=50.0
        )
        
        assert energy.solar_generated == 5.0
        assert energy.home_consumed == 3.0
        assert energy.grid_imported == 1.0
        assert energy.grid_exported == 2.0
        assert energy.battery_charged == 1.5
        assert energy.battery_discharged == 0.0
        assert energy.battery_soc_start == 45.0
        assert energy.battery_soc_end == 50.0

    def test_computed_properties(self):
        """Test computed properties."""
        energy = EnergyData(
            solar_generated=4.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=1.0,
            battery_charged=2.0,
            battery_discharged=0.5,
            battery_soc_start=40.0,
            battery_soc_end=45.0
        )
        
        assert energy.battery_net_change == 1.5  # charged - discharged
        assert energy.soc_change_percent == 5.0  # end - start

    def test_detailed_flow_calculation_charging_scenario(self):
        """Test detailed flow calculation for battery charging scenario."""
        energy = EnergyData(
            solar_generated=6.0,    # 6 kWh solar
            home_consumed=3.0,      # 3 kWh home consumption
            grid_imported=0.0,      # No grid import
            grid_exported=1.0,      # 1 kWh to grid
            battery_charged=2.0,    # 2 kWh to battery
            battery_discharged=0.0, # No discharge
            battery_soc_start=40.0,
            battery_soc_end=47.0
        )
        
        energy.calculate_detailed_flows()
        
        # Verify flow calculations for charging scenario
        assert energy.solar_to_home == 3.0    # Solar covers home consumption first
        assert energy.solar_to_battery == 2.0 # Remaining solar charges battery
        assert energy.solar_to_grid == 1.0    # Excess solar to grid
        assert energy.grid_to_home == 0.0     # No grid needed for home
        assert energy.grid_to_battery == 0.0  # No grid charging needed
        assert energy.battery_to_home == 0.0  # No battery discharge
        assert energy.battery_to_grid == 0.0  # No battery export

    def test_detailed_flow_calculation_discharging_scenario(self):
        """Test detailed flow calculation for battery discharging scenario."""
        energy = EnergyData(
            solar_generated=2.0,    # 2 kWh solar (limited)
            home_consumed=5.0,      # 5 kWh home consumption
            grid_imported=1.0,      # 1 kWh from grid
            grid_exported=0.0,      # No export
            battery_charged=0.0,    # No charging
            battery_discharged=2.0, # 2 kWh from battery
            battery_soc_start=60.0,
            battery_soc_end=53.0
        )
        
        energy.calculate_detailed_flows()
        
        # Verify flow calculations for discharging scenario
        assert energy.solar_to_home == 2.0    # Solar contributes to home
        assert energy.battery_to_home == 2.0  # Battery supplies remaining home load
        assert energy.grid_to_home == 1.0     # Grid supplies final remaining load
        assert energy.solar_to_grid == 0.0    # No solar excess
        assert energy.battery_to_grid == 0.0  # No battery export
        assert energy.solar_to_battery == 0.0 # No solar to battery
        assert energy.grid_to_battery == 0.0  # No grid charging

    def test_detailed_flow_calculation_idle_scenario(self):
        """Test detailed flow calculation for idle battery scenario."""
        energy = EnergyData(
            solar_generated=4.0,    # 4 kWh solar
            home_consumed=3.0,      # 3 kWh home consumption
            grid_imported=0.0,      # No grid import
            grid_exported=1.0,      # 1 kWh to grid
            battery_charged=0.0,    # No charging
            battery_discharged=0.0, # No discharge
            battery_soc_start=50.0,
            battery_soc_end=50.0    # No SOC change
        )
        
        energy.calculate_detailed_flows()
        
        # Verify flow calculations for idle scenario
        assert energy.solar_to_home == 3.0    # Solar covers home
        assert energy.solar_to_grid == 1.0    # Excess solar to grid
        assert energy.grid_to_home == 0.0     # No grid needed
        assert energy.battery_to_home == 0.0  # No battery action
        assert energy.battery_to_grid == 0.0  # No battery action
        assert energy.solar_to_battery == 0.0 # No battery action
        assert energy.grid_to_battery == 0.0  # No battery action

    def test_energy_balance_validation_valid(self):
        """Test energy balance validation with valid data."""
        energy = EnergyData(
            solar_generated=4.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=1.0,  # 1 kWh excess solar exported
            battery_charged=0.0,
            battery_discharged=0.0,
            battery_soc_start=50.0,
            battery_soc_end=50.0
        )
        
        is_valid, message = energy.validate_energy_balance()
        assert is_valid, f"Energy balance should be valid: {message}"
        assert "Energy balance OK" in message

    def test_energy_balance_validation_invalid(self):
        """Test energy balance validation with invalid data."""
        energy = EnergyData(
            solar_generated=4.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=2.0,  # Too much export - violates energy balance
            battery_charged=0.0,
            battery_discharged=0.0,
            battery_soc_start=50.0,
            battery_soc_end=50.0
        )
        
        is_valid, message = energy.validate_energy_balance()
        assert not is_valid, f"Energy balance should be invalid: {message}"
        assert "Energy balance error" in message

    def test_energy_balance_validation_with_tolerance(self):
        """Test energy balance validation respects tolerance."""
        # Small imbalance within tolerance
        energy = EnergyData(
            solar_generated=4.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=1.05,  # 0.05 kWh error - within default 0.1 tolerance
            battery_charged=0.0,
            battery_discharged=0.0,
            battery_soc_start=50.0,
            battery_soc_end=50.0
        )
        
        is_valid, message = energy.validate_energy_balance()
        assert is_valid, f"Small imbalance should be within tolerance: {message}"
        
        # Same imbalance with stricter tolerance
        is_valid, message = energy.validate_energy_balance(tolerance=0.01)
        assert not is_valid, f"Should fail with stricter tolerance: {message}"


class TestEconomicData:
    """Test EconomicData structure."""

    def test_creation_and_properties(self):
        """Test EconomicData creation and properties."""
        economic = EconomicData(
            buy_price=1.2,
            sell_price=0.8,
            hourly_cost=5.0,
            hourly_savings=2.0,
            battery_cycle_cost=0.5
        )
        
        assert economic.buy_price == 1.2
        assert economic.sell_price == 0.8
        assert economic.hourly_cost == 5.0
        assert economic.hourly_savings == 2.0
        assert economic.battery_cycle_cost == 0.5

    def test_net_value_calculation(self):
        """Test net economic value calculation."""
        economic = EconomicData(
            hourly_savings=3.0,
            battery_cycle_cost=0.5
        )
        
        assert economic.calculate_net_value() == 2.5  # savings - cycle_cost

    def test_default_values(self):
        """Test EconomicData with default values."""
        economic = EconomicData()
        
        assert economic.buy_price == 0.0
        assert economic.sell_price == 0.0
        assert economic.hourly_cost == 0.0
        assert economic.hourly_savings == 0.0
        assert economic.battery_cycle_cost == 0.0
        assert economic.calculate_net_value() == 0.0


class TestStrategyData:
    """Test StrategyData structure."""

    def test_creation_and_properties(self):
        """Test StrategyData creation and properties."""
        strategy = StrategyData(
            strategic_intent="GRID_CHARGING",
            battery_action=2.5,  # 2.5 kW charging
            cost_basis=1.0,
            pattern_name="Cheap Grid Arbitrage",
            description="Store cheap grid energy for later use",
            economic_chain="Grid(1.0) -> Battery -> Home(1.5)",
            immediate_value=0.0,
            future_value=2.5,
            risk_factors=["Price volatility", "Forecast accuracy"]
        )
        
        assert strategy.strategic_intent == "GRID_CHARGING"
        assert strategy.battery_action == 2.5
        assert strategy.cost_basis == 1.0
        assert strategy.pattern_name == "Cheap Grid Arbitrage"
        assert strategy.description == "Store cheap grid energy for later use"
        assert strategy.economic_chain == "Grid(1.0) -> Battery -> Home(1.5)"
        assert strategy.immediate_value == 0.0
        assert strategy.future_value == 2.5
        assert len(strategy.risk_factors) == 2

    def test_default_values(self):
        """Test StrategyData with default values."""
        strategy = StrategyData()
        
        assert strategy.strategic_intent == "IDLE"
        assert strategy.battery_action is None
        assert strategy.cost_basis == 0.0
        assert strategy.pattern_name == ""
        assert strategy.description == ""
        assert strategy.economic_chain == ""
        assert strategy.immediate_value == 0.0
        assert strategy.future_value == 0.0
        assert strategy.net_strategy_value == 0.0
        assert strategy.risk_factors == []


class TestNewHourlyData:
    """Test NewHourlyData composition structure."""

    def test_creation_from_optimization(self):
        """Test creating NewHourlyData from optimization results."""
        energy = EnergyData(
            solar_generated=5.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=1.0,
            battery_charged=1.0,
            battery_discharged=0.0,
            battery_soc_start=40.0,
            battery_soc_end=43.0
        )
        
        economic = EconomicData(
            buy_price=1.2,
            sell_price=0.8,
            hourly_savings=2.5,
            battery_cycle_cost=0.3
        )
        
        strategy = StrategyData(
            strategic_intent="SOLAR_STORAGE",
            battery_action=1.0,
            pattern_name="Solar Excess Storage"
        )
        
        timestamp = datetime(2025, 6, 28, 14, 0, 0)
        hourly = NewHourlyData.from_optimization(
            hour=14,
            energy_data=energy,
            economic_data=economic,
            strategy_data=strategy,
            timestamp=timestamp
        )
        
        # Test context fields
        assert hourly.hour == 14
        assert hourly.timestamp == timestamp
        assert hourly.data_source == "predicted"
        
        # Test composition
        assert hourly.energy is energy
        assert hourly.economic is economic
        assert hourly.strategy is strategy

    def test_creation_from_energy_data(self):
        """Test creating NewHourlyData from sensor energy data."""
        energy = EnergyData(
            solar_generated=4.0,
            home_consumed=3.5,
            grid_imported=0.0,
            grid_exported=0.5,
            battery_charged=0.0,
            battery_discharged=0.0,
            battery_soc_start=50.0,
            battery_soc_end=50.0
        )
        
        timestamp = datetime(2025, 6, 28, 10, 0, 0)
        hourly = NewHourlyData.from_energy_data(
            hour=10,
            energy_data=energy,
            data_source="actual",
            timestamp=timestamp
        )
        
        assert hourly.hour == 10
        assert hourly.timestamp == timestamp
        assert hourly.data_source == "actual"
        assert hourly.energy is energy
        
        # Economic and strategy should have defaults
        assert isinstance(hourly.economic, EconomicData)
        assert isinstance(hourly.strategy, StrategyData)
        assert hourly.economic.buy_price == 0.0
        assert hourly.strategy.strategic_intent == "IDLE"

    def test_convenience_properties(self):
        """Test convenience properties delegate correctly."""
        energy = EnergyData(
            solar_generated=5.0,
            home_consumed=3.0,
            grid_imported=1.0,
            grid_exported=2.0,
            battery_charged=1.5,
            battery_discharged=0.5,
            battery_soc_start=45.0,
            battery_soc_end=50.0
        )
        
        economic = EconomicData(
            buy_price=1.3,
            sell_price=0.9,
            hourly_cost=4.2,
            hourly_savings=1.8
        )
        
        strategy = StrategyData(
            strategic_intent="LOAD_SUPPORT",
            battery_action=-2.0  # Discharging
        )
        
        hourly = NewHourlyData.from_optimization(
            hour=18,
            energy_data=energy,
            economic_data=economic,
            strategy_data=strategy
        )
        
        # Test all convenience properties
        assert hourly.solar_generated == 5.0
        assert hourly.home_consumed == 3.0
        assert hourly.grid_imported == 1.0
        assert hourly.grid_exported == 2.0
        assert hourly.battery_charged == 1.5
        assert hourly.battery_discharged == 0.5
        assert hourly.battery_soc_start == 45.0
        assert hourly.battery_soc_end == 50.0
        assert hourly.battery_net_change == 1.0  # 1.5 - 0.5
        assert hourly.strategic_intent == "LOAD_SUPPORT"
        assert hourly.battery_action == -2.0
        assert hourly.buy_price == 1.3
        assert hourly.sell_price == 0.9
        assert hourly.hourly_cost == 4.2
        assert hourly.hourly_savings == 1.8

    def test_data_validation_valid(self):
        """Test data validation with valid data."""
        energy = EnergyData(
            solar_generated=5.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=1.0,
            battery_charged=1.0,
            battery_discharged=0.0,
            battery_soc_start=40.0,
            battery_soc_end=43.0
        )
        
        hourly = NewHourlyData.from_energy_data(hour=14, energy_data=energy)
        errors = hourly.validate_data()
        
        assert len(errors) == 0, f"Should have no validation errors: {errors}"

    def test_data_validation_invalid_hour(self):
        """Test data validation catches invalid hour."""
        energy = EnergyData(
            solar_generated=5.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=1.0,
            battery_charged=1.0,
            battery_discharged=0.0,
            battery_soc_start=40.0,
            battery_soc_end=43.0
        )
        
        hourly = NewHourlyData.from_energy_data(hour=25, energy_data=energy)
        errors = hourly.validate_data()
        
        assert len(errors) > 0
        assert any("Invalid hour" in error for error in errors)

    def test_data_validation_invalid_soc(self):
        """Test data validation catches invalid SOC values."""
        energy = EnergyData(
            solar_generated=5.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=1.0,
            battery_charged=1.0,
            battery_discharged=0.0,
            battery_soc_start=150.0,  # Invalid SOC > 100%
            battery_soc_end=43.0
        )
        
        hourly = NewHourlyData.from_energy_data(hour=14, energy_data=energy)
        errors = hourly.validate_data()
        
        assert len(errors) > 0
        assert any("Invalid start SOC" in error for error in errors)

    def test_data_validation_energy_balance_error(self):
        """Test data validation catches energy balance errors."""
        energy = EnergyData(
            solar_generated=4.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=2.0,  # Invalid - too much export
            battery_charged=0.0,
            battery_discharged=0.0,
            battery_soc_start=50.0,
            battery_soc_end=50.0
        )
        
        hourly = NewHourlyData.from_energy_data(hour=14, energy_data=energy)
        errors = hourly.validate_data()
        
        assert len(errors) > 0
        assert any("Energy balance error" in error for error in errors)

    def test_timestamp_defaults(self):
        """Test that timestamp defaults to current time when not provided."""
        energy = EnergyData(
            solar_generated=3.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=0.0,
            battery_charged=0.0,
            battery_discharged=0.0,
            battery_soc_start=50.0,
            battery_soc_end=50.0
        )
        
        before = datetime.now()
        hourly = NewHourlyData.from_energy_data(hour=12, energy_data=energy)
        after = datetime.now()
        
        assert hourly.timestamp is not None
        assert before <= hourly.timestamp <= after