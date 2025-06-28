"""
Unit tests for conversion bridge functions between old and new data structures.

These tests ensure that data conversion preserves all information and works correctly
during the migration process.
"""

from datetime import datetime

import pytest

from core.bess.models import (
    EnergyData,
    EnergyFlow,
    NewHourlyData,
    convert_energy_flow_to_new_format,
    convert_energy_flows_list,
    validate_conversion_equivalence,
)


class TestEnergyFlowToEnergyData:
    """Test conversion from EnergyFlow to EnergyData."""

    def test_basic_conversion(self):
        """Test basic EnergyFlow to EnergyData conversion."""
        energy_flow = EnergyFlow(
            hour=14,
            timestamp=datetime(2025, 6, 28, 14, 0, 0),
            battery_charged=2.0,
            battery_discharged=0.5,
            system_production=5.0,
            load_consumption=3.5,
            export_to_grid=1.0,
            import_from_grid=0.0,
            grid_to_battery=0.0,
            solar_to_battery=2.0,
            self_consumption=3.5,
            battery_soc_start=40.0,
            battery_soc_end=45.0,
            battery_soe_start=12.0,
            battery_soe_end=13.5,
            strategic_intent="SOLAR_STORAGE"
        )
        
        energy_data = energy_flow.to_energy_data()
        
        # Verify core fields are preserved
        assert energy_data.solar_generated == 5.0
        assert energy_data.home_consumed == 3.5
        assert energy_data.grid_imported == 0.0
        assert energy_data.grid_exported == 1.0
        assert energy_data.battery_charged == 2.0
        assert energy_data.battery_discharged == 0.5
        assert energy_data.battery_soc_start == 40.0
        assert energy_data.battery_soc_end == 45.0
        
        # Verify computed properties
        assert energy_data.battery_net_change == 1.5  # 2.0 - 0.5
        assert energy_data.soc_change_percent == 5.0  # 45.0 - 40.0

    def test_detailed_flows_calculated(self):
        """Test that detailed flows are calculated during conversion."""
        energy_flow = EnergyFlow(
            hour=10,
            timestamp=datetime(2025, 6, 28, 10, 0, 0),
            battery_charged=1.0,
            battery_discharged=0.0,
            system_production=4.0,
            load_consumption=2.0,
            export_to_grid=1.0,
            import_from_grid=0.0,
            grid_to_battery=0.0,
            solar_to_battery=1.0,
            self_consumption=2.0,
            battery_soc_start=30.0,
            battery_soc_end=33.0,
            battery_soe_start=9.0,
            battery_soe_end=10.0,
            strategic_intent="SOLAR_STORAGE"
        )
        
        energy_data = energy_flow.to_energy_data()
        
        # Should calculate detailed flows automatically
        assert energy_data.solar_to_home == 2.0    # Solar covers home first
        assert energy_data.solar_to_battery == 1.0 # Remaining solar to battery
        assert energy_data.solar_to_grid == 1.0    # Excess solar to grid
        assert energy_data.grid_to_home == 0.0     # No grid needed


class TestEnergyFlowToNewHourlyData:
    """Test conversion from EnergyFlow to NewHourlyData."""

    def test_basic_conversion(self):
        """Test basic EnergyFlow to NewHourlyData conversion."""
        timestamp = datetime(2025, 6, 28, 16, 0, 0)
        energy_flow = EnergyFlow(
            hour=16,
            timestamp=timestamp,
            battery_charged=0.0,
            battery_discharged=2.0,
            system_production=1.0,
            load_consumption=4.0,
            export_to_grid=0.0,
            import_from_grid=1.0,
            grid_to_battery=0.0,
            solar_to_battery=0.0,
            self_consumption=1.0,
            battery_soc_start=60.0,
            battery_soc_end=53.0,
            battery_soe_start=18.0,
            battery_soe_end=16.0,
            strategic_intent="LOAD_SUPPORT"
        )
        
        hourly_data = energy_flow.to_new_hourly_data("actual")
        
        # Verify context preserved
        assert hourly_data.hour == 16
        assert hourly_data.timestamp == timestamp
        assert hourly_data.data_source == "actual"
        
        # Verify energy data preserved
        assert hourly_data.energy.solar_generated == 1.0
        assert hourly_data.energy.home_consumed == 4.0
        assert hourly_data.energy.battery_discharged == 2.0
        
        # Verify strategy preserved
        assert hourly_data.strategy.strategic_intent == "LOAD_SUPPORT"
        
        # Verify convenience properties work
        assert hourly_data.solar_generated == 1.0
        assert hourly_data.strategic_intent == "LOAD_SUPPORT"

    def test_from_energy_flow_class_method(self):
        """Test NewHourlyData.from_energy_flow class method."""
        energy_flow = EnergyFlow(
            hour=12,
            timestamp=datetime(2025, 6, 28, 12, 0, 0),
            battery_charged=3.0,
            battery_discharged=0.0,
            system_production=8.0,
            load_consumption=3.0,
            export_to_grid=2.0,
            import_from_grid=0.0,
            grid_to_battery=0.0,
            solar_to_battery=3.0,
            self_consumption=3.0,
            battery_soc_start=20.0,
            battery_soc_end=30.0,
            battery_soe_start=6.0,
            battery_soe_end=9.0,
            strategic_intent="SOLAR_STORAGE"
        )
        
        hourly_data = NewHourlyData.from_energy_flow(energy_flow, "actual")
        
        assert hourly_data.hour == 12
        assert hourly_data.data_source == "actual"
        assert hourly_data.energy.solar_generated == 8.0
        assert hourly_data.strategy.strategic_intent == "SOLAR_STORAGE"


class TestNewHourlyDataToEnergyFlow:
    """Test reverse conversion from NewHourlyData to EnergyFlow."""

    def test_reverse_conversion(self):
        """Test converting NewHourlyData back to EnergyFlow."""
        timestamp = datetime(2025, 6, 28, 14, 0, 0)
        energy_data = EnergyData(
            solar_generated=6.0,
            home_consumed=4.0,
            grid_imported=0.0,
            grid_exported=1.0,
            battery_charged=1.0,
            battery_discharged=0.0,
            battery_soc_start=45.0,
            battery_soc_end=48.0
        )
        
        hourly_data = NewHourlyData(
            hour=14,
            energy=energy_data,
            timestamp=timestamp,
            data_source="actual"
        )
        hourly_data.strategy.strategic_intent = "SOLAR_STORAGE"
        
        energy_flow = hourly_data.to_energy_flow()
        
        # Verify all fields converted correctly
        assert energy_flow.hour == 14
        assert energy_flow.timestamp == timestamp
        assert energy_flow.system_production == 6.0
        assert energy_flow.load_consumption == 4.0
        assert energy_flow.battery_charged == 1.0
        assert energy_flow.battery_soc_start == 45.0
        assert energy_flow.strategic_intent == "SOLAR_STORAGE"
        
        # Verify computed fields
        assert energy_flow.self_consumption == 4.0  # min(solar, home)

    def test_reverse_conversion_missing_timestamp(self):
        """Test that reverse conversion fails without timestamp."""
        energy_data = EnergyData(
            solar_generated=5.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=2.0,
            battery_charged=0.0,
            battery_discharged=0.0,
            battery_soc_start=50.0,
            battery_soc_end=50.0
        )
        
        hourly_data = NewHourlyData(
            hour=14,
            energy=energy_data,
            timestamp=None  # Missing timestamp
        )
        
        with pytest.raises(ValueError, match="timestamp is required"):
            hourly_data.to_energy_flow()


class TestDictionaryConversions:
    """Test dictionary conversion methods."""

    def test_energy_data_from_dict(self):
        """Test creating EnergyData from dictionary."""
        data = {
            "solar_generated": 5.0,
            "home_consumed": 3.0,
            "grid_imported": 0.0,
            "grid_exported": 2.0,
            "battery_charged": 0.0,
            "battery_discharged": 0.0,
            "battery_soc_start": 50.0,
            "battery_soc_end": 50.0,
            "solar_to_home": 3.0,
            "solar_to_grid": 2.0
        }
        
        energy_data = EnergyData.from_dict(data)
        
        assert energy_data.solar_generated == 5.0
        assert energy_data.home_consumed == 3.0
        assert energy_data.solar_to_home == 3.0
        assert energy_data.solar_to_grid == 2.0

    def test_energy_data_from_dict_missing_required(self):
        """Test EnergyData.from_dict fails with missing required fields."""
        data = {
            "solar_generated": 5.0,
            # Missing other required fields
        }
        
        with pytest.raises(ValueError, match="home_consumed is required"):
            EnergyData.from_dict(data)

    def test_energy_data_to_dict(self):
        """Test converting EnergyData to dictionary."""
        energy_data = EnergyData(
            solar_generated=4.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=1.0,
            battery_charged=0.0,
            battery_discharged=0.0,
            battery_soc_start=45.0,
            battery_soc_end=45.0
        )
        
        data = energy_data.to_dict()
        
        assert data["solar_generated"] == 4.0
        assert data["home_consumed"] == 3.0
        assert data["battery_net_change"] == 0.0
        assert "solar_to_home" in data

    def test_new_hourly_data_to_dict(self):
        """Test converting NewHourlyData to dictionary."""
        timestamp = datetime(2025, 6, 28, 14, 0, 0)
        energy_data = EnergyData(
            solar_generated=5.0,
            home_consumed=3.0,
            grid_imported=0.0,
            grid_exported=2.0,
            battery_charged=0.0,
            battery_discharged=0.0,
            battery_soc_start=50.0,
            battery_soc_end=50.0
        )
        
        hourly_data = NewHourlyData(
            hour=14,
            energy=energy_data,
            timestamp=timestamp,
            data_source="actual"
        )
        
        data = hourly_data.to_dict()
        
        assert data["hour"] == 14
        assert data["data_source"] == "actual"
        assert data["solar_generated"] == 5.0
        assert data["strategic_intent"] == "IDLE"  # Default
        assert data["timestamp"] == timestamp.isoformat()


class TestBulkConversionHelpers:
    """Test bulk conversion helper functions."""

    def test_convert_energy_flow_to_new_format(self):
        """Test top-level conversion function."""
        energy_flow = EnergyFlow(
            hour=10,
            timestamp=datetime(2025, 6, 28, 10, 0, 0),
            battery_charged=1.0,
            battery_discharged=0.0,
            system_production=4.0,
            load_consumption=3.0,
            export_to_grid=0.0,
            import_from_grid=0.0,
            grid_to_battery=0.0,
            solar_to_battery=1.0,
            self_consumption=3.0,
            battery_soc_start=40.0,
            battery_soc_end=43.0,
            battery_soe_start=12.0,
            battery_soe_end=13.0,
            strategic_intent="SOLAR_STORAGE"
        )
        
        hourly_data = convert_energy_flow_to_new_format(energy_flow)
        
        assert isinstance(hourly_data, NewHourlyData)
        assert hourly_data.data_source == "actual"
        assert hourly_data.energy.solar_generated == 4.0

    def test_convert_energy_flows_list(self):
        """Test bulk conversion of EnergyFlow list."""
        flows = []
        for hour in range(3):
            flow = EnergyFlow(
                hour=hour,
                timestamp=datetime(2025, 6, 28, hour, 0, 0),
                battery_charged=float(hour),
                battery_discharged=0.0,
                system_production=float(hour + 1),
                load_consumption=2.0,
                export_to_grid=0.0,
                import_from_grid=0.0,
                grid_to_battery=0.0,
                solar_to_battery=float(hour),
                self_consumption=2.0,
                battery_soc_start=50.0,
                battery_soc_end=50.0 + hour,
                battery_soe_start=15.0,
                battery_soe_end=15.0 + hour,
                strategic_intent="IDLE"
            )
            flows.append(flow)
        
        hourly_data_list = convert_energy_flows_list(flows)
        
        assert len(hourly_data_list) == 3
        assert all(isinstance(hd, NewHourlyData) for hd in hourly_data_list)
        assert hourly_data_list[0].hour == 0
        assert hourly_data_list[1].hour == 1
        assert hourly_data_list[2].hour == 2

    def test_validate_conversion_equivalence(self):
        """Test conversion validation helper."""
        energy_flow = EnergyFlow(
            hour=15,
            timestamp=datetime(2025, 6, 28, 15, 0, 0),
            battery_charged=0.0,
            battery_discharged=1.5,
            system_production=2.0,
            load_consumption=3.5,
            export_to_grid=0.0,
            import_from_grid=0.0,
            grid_to_battery=0.0,
            solar_to_battery=0.0,
            self_consumption=2.0,
            battery_soc_start=55.0,
            battery_soc_end=50.0,
            battery_soe_start=16.5,
            battery_soe_end=15.0,
            strategic_intent="LOAD_SUPPORT"
        )
        
        hourly_data = convert_energy_flow_to_new_format(energy_flow)
        
        # Should validate as equivalent
        assert validate_conversion_equivalence(energy_flow, hourly_data)
        
        # Test with modified data - should fail validation
        hourly_data.energy.solar_generated = 999.0  # Different value
        assert not validate_conversion_equivalence(energy_flow, hourly_data)