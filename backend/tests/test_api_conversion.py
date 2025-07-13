"""Tests for API conversion functionality.

This test validates the backend API layer conversion from core models to API responses.
This is separate from core tests to maintain proper architecture boundaries.
"""

from datetime import datetime

import pytest
from api_dataclasses import flatten_hourly_data

from core.bess.models import DecisionData, EconomicData, EnergyData, HourlyData


class TestAPIConversion:
    """Test API conversion from core models to API responses."""
    
    @pytest.fixture
    def sample_hourly_data(self):
        """Create sample core HourlyData for testing."""
        energy = EnergyData(
            solar_production=5.0,
            home_consumption=3.0,
            battery_charged=1.5,
            battery_discharged=0.0,
            grid_imported=0.0,
            grid_exported=2.5,
            battery_soe_start=15.0,
            battery_soe_end=16.5
        )
        
        economic = EconomicData(
            buy_price=1.5,
            sell_price=0.8,
            grid_cost=-2.0,  # Negative because we're exporting
            battery_cycle_cost=0.05,
            hourly_cost=-1.95,
            grid_only_cost=4.5,
            solar_only_cost=2.5,
            hourly_savings=6.45
        )
        
        decision = DecisionData(
            strategic_intent="SOLAR_STORAGE",
            battery_action=1.5
        )
        
        return HourlyData(
            hour=10,
            energy=energy,
            timestamp=datetime(2025, 7, 13, 10, 0),
            data_source="predicted",
            economic=economic,
            decision=decision
        )
    
    def test_flatten_hourly_data_conversion(self, sample_hourly_data):
        """Test that flatten_hourly_data correctly converts core models to API format."""
        battery_capacity = 30.0
        
        # Convert to API format
        api_data = flatten_hourly_data(sample_hourly_data, battery_capacity)
        
        # Check canonical field names are used
        assert "solarProduction" in api_data
        assert "homeConsumption" in api_data
        assert "gridImported" in api_data
        assert "gridExported" in api_data
        assert "batteryCharged" in api_data
        assert "batteryDischarged" in api_data
        
        # Check economic fields
        assert "gridOnlyCost" in api_data
        assert "hourlyCost" in api_data  # Use canonical name
        assert "hourlySavings" in api_data  # Use canonical name (total optimization savings)
        assert "solarSavings" in api_data  # Solar-only vs grid-only savings
        assert "batteryCycleCost" in api_data
        
        # Verify solarSavings calculation is correct
        if "gridOnlyCost" in api_data and "solarOnlyCost" in api_data:
            expected_solar_savings = api_data["gridOnlyCost"] - api_data["solarOnlyCost"]
            assert abs(api_data["solarSavings"] - expected_solar_savings) < 0.01
        
        # Check values are correctly converted
        assert api_data["solarProduction"] == 5.0
        assert api_data["homeConsumption"] == 3.0
        assert api_data["gridOnlyCost"] == 4.5
        assert api_data["batteryCycleCost"] == 0.05
        
        # Check battery SOC conversion (SOE -> SOC percentage)
        expected_soc_start = (15.0 / battery_capacity) * 100
        expected_soc_end = (16.5 / battery_capacity) * 100
        assert api_data["batterySocStart"] == expected_soc_start
        assert api_data["batterySocEnd"] == expected_soc_end
    
    def test_api_conversion_required_fields(self, sample_hourly_data):
        """Test that all required API fields are present after conversion."""
        api_data = flatten_hourly_data(sample_hourly_data, 30.0)
        
        # Fields that frontend components expect
        required_fields = [
            "hour", "solarProduction", "homeConsumption", "gridImported", "gridExported",
            "batteryCharged", "batteryDischarged", "batterySocStart", "batterySocEnd",
            "buyPrice", "sellPrice", "gridOnlyCost", "hourlyCost", "hourlySavings", "solarSavings",
            "batteryCycleCost", "batteryAction", "dataSource"
        ]
        
        for field in required_fields:
            assert field in api_data, f"Required field {field} missing from API conversion"
    
    def test_api_conversion_preserves_data_types(self, sample_hourly_data):
        """Test that API conversion preserves correct data types."""
        api_data = flatten_hourly_data(sample_hourly_data, 30.0)
        
        # Numeric fields should be float or int
        numeric_fields = ["solarProduction", "homeConsumption", "buyPrice", "gridOnlyCost"]
        for field in numeric_fields:
            assert isinstance(api_data[field], int | float), f"Field {field} should be numeric"
        
        # String fields should be string
        assert isinstance(api_data["dataSource"], str)
        assert isinstance(api_data["strategicIntent"], str)
        
        # Hour should be int
        assert isinstance(api_data["hour"], int)
