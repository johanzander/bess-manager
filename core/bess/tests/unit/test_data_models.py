"""
Unit tests for new hierarchical data models.

Tests the EnergyData, EconomicData, DecisionData, and HourlyData structures
"""

from datetime import datetime

from core.bess.models import DecisionData, EconomicData, EnergyData, HourlyData


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
            battery_soe_start=22.5,  
            battery_soe_end=25.0,    
        )

        assert energy.solar_generated == 5.0
        assert energy.home_consumed == 3.0
        assert energy.grid_imported == 1.0
        assert energy.grid_exported == 2.0
        assert energy.battery_charged == 1.5
        assert energy.battery_discharged == 0.0
        assert energy.battery_soe_start == 22.5  # Changed from battery_soe_start
        assert energy.battery_soe_end == 25.0    # Changed from battery_soe_end

    def test_computed_properties(self):
        """Test computed properties."""
        energy = EnergyData(
            solar_generated=4.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=1.0,
            battery_charged=2.0,
            battery_discharged=0.5,
            battery_soe_start=20.0,  # Changed from battery_soe_start=40.0
            battery_soe_end=22.5,    # Changed from battery_soe_end=45.0
        )

        assert energy.battery_net_change == 1.5  # charged - discharged
        assert energy.soe_change_kwh == 2.5      # Changed from soc_change_percent == 5.0


    def test_detailed_flow_calculation_charging_scenario(self):
        """Test detailed flow calculation for battery charging scenario."""
        energy = EnergyData(
            solar_generated=6.0,  # 6 kWh solar
            home_consumed=3.0,  # 3 kWh home consumption
            grid_imported=0.0,  # No grid import
            grid_exported=1.0,  # 1 kWh to grid
            battery_charged=2.0,  # 2 kWh to battery
            battery_discharged=0.0,  # No discharge
            battery_soe_start=20.0,  # Changed from battery_soe_start=40.0
            battery_soe_end=23.5,    # Changed from battery_soe_end=47.0
        )

        # Verify flow calculations for charging scenario
        assert energy.solar_to_home == 3.0  # Solar covers home consumption first
        assert energy.solar_to_battery == 2.0  # Remaining solar charges battery
        assert energy.solar_to_grid == 1.0  # Excess solar to grid
        assert energy.grid_to_home == 0.0  # No grid needed for home
        assert energy.grid_to_battery == 0.0  # No grid charging needed
        assert energy.battery_to_home == 0.0  # No battery discharge
        assert energy.battery_to_grid == 0.0  # No battery export

    def test_detailed_flow_calculation_discharging_scenario(self):
        """Test detailed flow calculation for battery discharging scenario."""
        energy = EnergyData(
            solar_generated=2.0,  # 2 kWh solar (limited)
            home_consumed=5.0,  # 5 kWh home consumption
            grid_imported=1.0,  # 1 kWh from grid
            grid_exported=0.0,  # No export
            battery_charged=0.0,  # No charging
            battery_discharged=2.0,  # 2 kWh from battery
            battery_soe_start=30.0,  # Changed from battery_soe_start=60.0
            battery_soe_end=26.5,    # Changed from battery_soe_end=53.0
        )

        # Verify flow calculations for discharging scenario
        assert energy.solar_to_home == 2.0  # Solar contributes to home
        assert energy.battery_to_home == 2.0  # Battery supplies remaining home load
        assert energy.grid_to_home == 1.0  # Grid supplies final remaining load
        assert energy.solar_to_grid == 0.0  # No solar excess
        assert energy.battery_to_grid == 0.0  # No battery export
        assert energy.solar_to_battery == 0.0  # No solar to battery
        assert energy.grid_to_battery == 0.0  # No grid charging

    def test_detailed_flow_calculation_idle_scenario(self):
        """Test detailed flow calculation for idle battery scenario."""
        energy = EnergyData(
            solar_generated=4.0,  # 4 kWh solar
            home_consumed=3.0,  # 3 kWh home consumption
            grid_imported=0.0,  # No grid import
            grid_exported=1.0,  # 1 kWh to grid
            battery_charged=0.0,  # No charging
            battery_discharged=0.0,  # No discharge
            battery_soe_start=25.0,  
            battery_soe_end=25.0,     
        )

        # Verify flow calculations for idle scenario
        assert energy.solar_to_home == 3.0  # Solar covers home
        assert energy.solar_to_grid == 1.0  # Excess solar to grid
        assert energy.grid_to_home == 0.0  # No grid needed
        assert energy.battery_to_home == 0.0  # No battery action
        assert energy.battery_to_grid == 0.0  # No battery action
        assert energy.solar_to_battery == 0.0  # No battery action
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
            battery_soe_start=25.0,  
            battery_soe_end=25.0,    
        )

        is_valid, message = energy.validate_energy_balance()
        assert is_valid, f"Energy balance should be valid: {message}"
        assert "Energy balance OK" in message


    def test_energy_balance_validation_with_tolerance(self):
        """Test energy balance validation respects tolerance."""
        energy = EnergyData(
            solar_generated=4.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=1.1,  # Slightly off balance
            battery_charged=0.0,
            battery_discharged=0.0,
            battery_soe_start=25.0,  
            battery_soe_end=25.0,    
        )

        is_valid, message = energy.validate_energy_balance(tolerance=0.2)
        assert is_valid, f"Should pass with tolerance: {message}"



class TestEconomicData:
    """Test EconomicData structure."""

    def test_creation_and_properties(self):
        """Test EconomicData creation and properties."""
        economic = EconomicData(
            buy_price=1.2,
            sell_price=0.8,
            hourly_cost=5.0,
            hourly_savings=2.0,
            battery_cycle_cost=0.5,
            grid_only_cost=7.0,
            solar_only_cost=6.0,
        )

        assert economic.buy_price == 1.2
        assert economic.sell_price == 0.8
        assert economic.hourly_cost == 5.0
        assert economic.hourly_savings == 2.0
        assert economic.battery_cycle_cost == 0.5

    def test_net_value_calculation(self):
        """Test net economic value calculation."""
        economic = EconomicData(hourly_savings=3.0, battery_cycle_cost=0.5)

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


class TestDecisionData:
    """Test DecisionData structure."""

    def test_creation_and_properties(self):
        """Test DecisionData creation and properties."""
        decision = DecisionData(
            strategic_intent="GRID_CHARGING",
            battery_action=2.5,  # 2.5 kW charging
            cost_basis=1.0,
            pattern_name="Cheap Grid Arbitrage",
            description="Store cheap grid energy for later use",
            economic_chain="Grid(1.0) -> Battery -> Home(1.5)",
            immediate_value=0.0,
            future_value=2.5,
        )

        assert decision.strategic_intent == "GRID_CHARGING"
        assert decision.battery_action == 2.5
        assert decision.cost_basis == 1.0
        assert decision.pattern_name == "Cheap Grid Arbitrage"
        assert decision.description == "Store cheap grid energy for later use"
        assert decision.economic_chain == "Grid(1.0) -> Battery -> Home(1.5)"
        assert decision.immediate_value == 0.0
        assert decision.future_value == 2.5

    def test_default_values(self):
        """Test DecisionData with default values."""
        decision = DecisionData()

        assert decision.strategic_intent == "IDLE"
        assert decision.battery_action is None
        assert decision.cost_basis == 0.0
        assert decision.pattern_name == ""
        assert decision.description == ""
        assert decision.economic_chain == ""
        assert decision.immediate_value == 0.0
        assert decision.future_value == 0.0
        assert decision.net_strategy_value == 0.0


class TestHourlyData:
    """Test HourlyData composition structure."""

    def test_creation_from_optimization(self):
        """Test creating HourlyData from optimization results."""
        energy = EnergyData(
            solar_generated=5.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=1.0,
            battery_charged=1.0,
            battery_discharged=0.0,
            battery_soe_start=40.0,
            battery_soe_end=43.0,
        )

        economic = EconomicData(
            buy_price=1.2, sell_price=0.8, hourly_savings=2.5, battery_cycle_cost=0.3
        )

        strategy = DecisionData(
            strategic_intent="SOLAR_STORAGE",
            battery_action=1.0,
            pattern_name="Solar Excess Storage",
        )

        timestamp = datetime(2025, 6, 28, 14, 0, 0)
        hourly = HourlyData.from_optimization(
            hour=14,
            energy_data=energy,
            economic_data=economic,
            decision_data=strategy,
            timestamp=timestamp,
        )

        # Test context fields
        assert hourly.hour == 14
        assert hourly.timestamp == timestamp
        assert hourly.data_source == "predicted"

        # Test composition
        assert hourly.energy is energy
        assert hourly.economic is economic
        assert hourly.decision is strategy

    def test_creation_from_energy_data(self):
        """Test creating HourlyData from sensor energy data."""
        energy = EnergyData(
            solar_generated=4.0,
            home_consumed=3.5,
            grid_imported=0.0,
            grid_exported=0.5,
            battery_charged=0.0,
            battery_discharged=0.0,
            battery_soe_start=50.0,
            battery_soe_end=50.0,
        )

        timestamp = datetime(2025, 6, 28, 10, 0, 0)
        hourly = HourlyData.from_energy_data(
            hour=10, energy_data=energy, data_source="actual", timestamp=timestamp
        )

        assert hourly.hour == 10
        assert hourly.timestamp == timestamp
        assert hourly.data_source == "actual"
        assert hourly.energy is energy

        # Economic and strategy should have defaults
        assert isinstance(hourly.economic, EconomicData)
        assert isinstance(hourly.decision, DecisionData)
        assert hourly.economic.buy_price == 0.0
        assert hourly.decision.strategic_intent == "IDLE"

    def test_data_validation_valid(self):
        """Test data validation with valid data."""
        energy = EnergyData(
            solar_generated=5.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=1.0,
            battery_charged=1.0,
            battery_discharged=0.0,
            battery_soe_start=40.0,
            battery_soe_end=43.0,
        )

        hourly = HourlyData.from_energy_data(hour=14, energy_data=energy)
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
            battery_soe_start=22.5,  
            battery_soe_end=25.0,    
        )

        hourly = HourlyData.from_energy_data(hour=25, energy_data=energy)
        errors = hourly.validate_data()

        assert len(errors) > 0
        assert any("Invalid hour" in error for error in errors)


    def test_timestamp_defaults(self):
        """Test timestamp defaults to provided value."""
        energy = EnergyData(
            solar_generated=5.0,
            home_consumed=3.0,
            grid_imported=1.0,
            grid_exported=2.0,
            battery_charged=1.5,
            battery_discharged=0.0,
            battery_soe_start=22.5,  
            battery_soe_end=25.0,    
        )

        before = datetime.now()
        hourly = HourlyData.from_energy_data(hour=12, energy_data=energy)
        after = datetime.now()

        assert hourly.timestamp is not None
        assert before <= hourly.timestamp <= after
