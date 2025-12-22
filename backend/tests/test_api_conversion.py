"""Tests for API conversion functionality.

This test validates the backend API layer conversion from core models to API responses.
This is separate from core tests to maintain proper architecture boundaries.
"""

from datetime import datetime

import pytest
from api_dataclasses import APIDashboardHourlyData

from core.bess.models import DecisionData, EconomicData, EnergyData, PeriodData


class TestAPIConversion:
    """Test API conversion from core models to API responses."""

    @pytest.fixture
    def sample_hourly_data(self):
        """Create sample core PeriodData for testing."""
        energy = EnergyData(
            solar_production=5.0,
            home_consumption=3.0,
            battery_charged=1.5,
            battery_discharged=0.0,
            grid_imported=0.0,
            grid_exported=2.5,
            battery_soe_start=15.0,
            battery_soe_end=16.5,
        )

        economic = EconomicData(
            buy_price=1.5,
            sell_price=0.8,
            grid_cost=-2.0,  # Negative because we're exporting
            battery_cycle_cost=0.05,
            hourly_cost=-1.95,
            grid_only_cost=4.5,
            solar_only_cost=2.5,
            hourly_savings=6.45,
        )

        decision = DecisionData(strategic_intent="SOLAR_STORAGE", battery_action=1.5)

        return PeriodData(
            period=10,
            energy=energy,
            timestamp=datetime(2025, 7, 13, 10, 0),
            data_source="predicted",
            economic=economic,
            decision=decision,
        )

    def test_flatten_hourly_data_conversion(self, sample_hourly_data):
        """Test that APIDashboardHourlyData correctly converts core models to API format."""
        battery_capacity = 30.0
        currency = "SEK"

        # Convert to API format
        api_data = APIDashboardHourlyData.from_internal(
            sample_hourly_data, battery_capacity, currency
        )

        # Check canonical field names exist (using attribute access for dataclass)
        assert hasattr(api_data, "solarProduction")
        assert hasattr(api_data, "homeConsumption")
        assert hasattr(api_data, "gridImported")
        assert hasattr(api_data, "gridExported")
        assert hasattr(api_data, "batteryCharged")
        assert hasattr(api_data, "batteryDischarged")

        # Check economic fields
        assert hasattr(api_data, "gridOnlyCost")
        assert hasattr(api_data, "hourlyCost")
        assert hasattr(api_data, "hourlySavings")
        assert hasattr(api_data, "solarSavings")

        # Check values are correctly converted (FormattedValue.value)
        assert api_data.solarProduction.value == 5.0
        assert api_data.homeConsumption.value == 3.0
        assert api_data.gridOnlyCost.value == 4.5

        # Check battery SOC conversion (SOE -> SOC percentage)
        expected_soc_start = (15.0 / battery_capacity) * 100
        expected_soc_end = (16.5 / battery_capacity) * 100
        assert abs(api_data.batterySocStart.value - expected_soc_start) < 0.01
        assert abs(api_data.batterySocEnd.value - expected_soc_end) < 0.01

    def test_api_conversion_required_fields(self, sample_hourly_data):
        """Test that all required API fields are present after conversion."""
        api_data = APIDashboardHourlyData.from_internal(sample_hourly_data, 30.0, "SEK")

        # Fields that frontend components expect
        required_fields = [
            "period",
            "solarProduction",
            "homeConsumption",
            "gridImported",
            "gridExported",
            "batteryCharged",
            "batteryDischarged",
            "batterySocStart",
            "batterySocEnd",
            "buyPrice",
            "sellPrice",
            "gridOnlyCost",
            "hourlyCost",
            "hourlySavings",
            "solarSavings",
            "batteryAction",
            "dataSource",
        ]

        for field in required_fields:
            assert hasattr(
                api_data, field
            ), f"Required field {field} missing from API conversion"

    def test_api_conversion_preserves_data_types(self, sample_hourly_data):
        """Test that API conversion preserves correct data types."""
        api_data = APIDashboardHourlyData.from_internal(sample_hourly_data, 30.0, "SEK")

        # FormattedValue fields should have numeric values
        from api_dataclasses import FormattedValue

        formatted_fields = [
            "solarProduction",
            "homeConsumption",
            "buyPrice",
            "gridOnlyCost",
        ]
        for field in formatted_fields:
            field_value = getattr(api_data, field)
            assert isinstance(
                field_value, FormattedValue
            ), f"Field {field} should be FormattedValue"
            assert isinstance(
                field_value.value, int | float
            ), f"Field {field}.value should be numeric"

        # String fields should be string
        assert isinstance(api_data.dataSource, str)
        assert isinstance(api_data.strategicIntent, str)

        # Period should be int
        assert isinstance(api_data.period, int)
