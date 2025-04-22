"""Shared test fixtures and utilities for battery system integration tests."""

import logging

import pytest

from bess import BatterySystemManager
from bess.price_manager import MockSource

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockHomeAssistantController:
    """Mock Home Assistant controller for testing."""

    def __init__(self) -> None:
        """Initialize with default settings."""
        self.settings = {
            "grid_charge": False,
            "discharge_rate": 0,
            "battery_soc": 50,
            "consumption": 4.5,
            "charge_power": 0,
            "discharge_power": 0,
            "l1_current": 10.0,
            "l2_current": 8.0,
            "l3_current": 12.0,
            "charge_stop_soc": 100,
            "discharge_stop_soc": 10,
            "charging_power_rate": 40,
            "test_mode": False,
            "tou_settings": [],
            "battery_charge_today": 0.0,
            "battery_discharge_today": 0.0,
            "solar_generation_today": 0.0,
            "self_consumption_today": 0.0,
            "export_to_grid_today": 0.0,
            "load_consumption_today": 0.0,
            "import_from_grid_today": 0.0,
            "grid_to_battery_today": 0.0,
            "ev_energy_today": 0.0,
        }

        # Configurable forecasts for testing
        self.consumption_forecast = [4.5] * 24
        self.solar_forecast = [0.0] * 24

    # Required methods for Home Assistant Controller interface
    def get_battery_soc(self):
        """Get the current battery state of charge."""
        return self.settings["battery_soc"]

    def get_current_consumption(self):
        """Get the current home consumption."""
        return self.settings["consumption"]

    def get_estimated_consumption(self):
        """Get estimated hourly consumption for 24 hours."""
        return self.consumption_forecast

    def get_solcast_forecast(self, day_offset=0, confidence_level="estimate"):
        """Get solar forecast data from Solcast integration."""
        return self.solar_forecast

    def grid_charge_enabled(self):
        """Check if grid charging is enabled."""
        return self.settings["grid_charge"]

    def set_grid_charge(self, enabled):
        """Enable or disable grid charging."""
        self.settings["grid_charge"] = enabled

    def get_solar_generation(self):
        """Get the current solar generation value."""
        return self.settings.get("solar_value", 0.0)

    def get_battery_charge_power(self):
        """Get the current battery charge power."""
        return self.settings["charge_power"]

    def get_battery_discharge_power(self):
        """Get the current battery discharge power."""
        return self.settings["discharge_power"]

    def get_charging_power_rate(self):
        """Get the current charging power rate."""
        return self.settings["charging_power_rate"]

    def set_charging_power_rate(self, rate):
        """Set the charging power rate."""
        self.settings["charging_power_rate"] = rate

    def get_discharging_power_rate(self):
        """Get the current discharging power rate."""
        return self.settings["discharge_rate"]

    def set_discharging_power_rate(self, rate):
        """Set the discharging power rate."""
        self.settings["discharge_rate"] = rate

    def get_charge_stop_soc(self):
        """Get the SOC (state of charge) at which charging stops."""
        return self.settings["charge_stop_soc"]

    def set_charge_stop_soc(self, soc):
        """Set the SOC (state of charge) at which charging stops."""
        self.settings["charge_stop_soc"] = soc

    def get_discharge_stop_soc(self):
        """Get the SOC (state of charge) at which discharging stops."""
        return self.settings["discharge_stop_soc"]

    def set_discharge_stop_soc(self, soc):
        """Set the SOC (state of charge) at which discharging stops."""
        self.settings["discharge_stop_soc"] = soc

    def set_test_mode(self, enabled):
        """Enable or disable test mode."""
        self.settings["test_mode"] = enabled

    def get_l1_current(self):
        """Get the current on line 1."""
        return self.settings["l1_current"]

    def get_l2_current(self):
        """Get the current on line 2."""
        return self.settings["l2_current"]

    def get_l3_current(self):
        """Get the current on line 3."""
        return self.settings["l3_current"]

    def disable_all_TOU_settings(self):
        """Clear all TOU settings."""
        self.settings["tou_settings"] = []

    def set_inverter_time_segment(self, **kwargs):
        """Store TOU setting."""
        self.settings["tou_settings"].append(kwargs)

    def get_battery_charge_today(self):
        """Get total battery charging for today in kWh."""
        return self.settings["battery_charge_today"]

    def get_battery_discharge_today(self):
        """Get total battery discharging for today in kWh."""
        return self.settings["battery_discharge_today"]

    def get_solar_generation_today(self):
        """Get total solar generation for today in kWh."""
        return self.settings["solar_generation_today"]

    def get_self_consumption_today(self):
        """Get total solar self-consumption for today in kWh."""
        return self.settings["self_consumption_today"]

    def get_export_to_grid_today(self):
        """Get total export to grid for today in kWh."""
        return self.settings["export_to_grid_today"]

    def get_load_consumption_today(self):
        """Get total home load consumption for today in kWh."""
        return self.settings["load_consumption_today"]

    def get_import_from_grid_today(self):
        """Get total import from grid for today in kWh."""
        return self.settings["import_from_grid_today"]

    def get_grid_to_battery_today(self):
        """Get total grid to battery charging for today in kWh."""
        return self.settings["grid_to_battery_today"]

    def get_ev_energy_today(self):
        """Get total EV charging energy for today in kWh."""
        return self.settings["ev_energy_today"]

    def get_nordpool_prices_today(self) -> list[float]:
        """Get the current Nordpool prices for today."""
        return [1.0] * 24


# MOCK CONTROLLER FIXTURE
@pytest.fixture
def mock_controller():
    """Provide a configured mock Home Assistant controller."""
    return MockHomeAssistantController()


# PRICE DATA FIXTURES
@pytest.fixture
def price_data_2024_08_16():
    """Raw price data from 2024-08-16 with high price spread."""
    return [
        0.9827,
        0.8419,
        0.0321,
        0.0097,
        0.0098,
        0.9136,
        1.4433,
        1.5162,
        1.4029,
        1.1346,
        0.8558,
        0.6485,
        0.2895,
        0.1363,
        0.1253,
        0.6200,
        0.8880,
        1.1662,
        1.5163,
        2.5908,
        2.7325,
        1.9312,
        1.5121,
        1.3056,
    ]


@pytest.fixture
def price_data_2025_01_05():
    """Raw price data from 2025-01-05 with insufficient price spread."""
    return [
        0.780,
        0.790,
        0.800,
        0.830,
        0.950,
        0.970,
        1.160,
        1.170,
        1.220,
        1.280,
        1.210,
        1.300,
        1.200,
        1.130,
        0.980,
        0.740,
        0.730,
        0.950,
        0.920,
        0.740,
        0.530,
        0.530,
        0.500,
        0.400,
    ]


@pytest.fixture
def price_data_2025_01_12():
    """Raw price data from 2025-01-12 with evening peak."""
    return [
        0.357,
        0.301,
        0.289,
        0.349,
        0.393,
        0.405,
        0.412,
        0.418,
        0.447,
        0.605,
        0.791,
        0.919,
        0.826,
        0.779,
        1.066,
        1.332,
        1.492,
        1.583,
        1.677,
        1.612,
        1.514,
        1.277,
        0.829,
        0.481,
    ]


@pytest.fixture
def price_data_2025_01_13():
    """Raw price data from 2025-01-13 with night low."""
    return [
        0.477,
        0.447,
        0.450,
        0.438,
        0.433,
        0.422,
        0.434,
        0.805,
        1.180,
        0.654,
        0.454,
        0.441,
        0.433,
        0.425,
        0.410,
        0.399,
        0.402,
        0.401,
        0.379,
        0.347,
        0.067,
        0.023,
        0.018,
        0.000,
    ]


# TEST CASE PARAMETER FIXTURES
@pytest.fixture
def test_case_2024_08_16():
    """Test parameters for 2024-08-16 case."""
    return {
        "battery_soc": 10,  # Starting battery level
        "consumption": [5.2] * 24,  # Consumption pattern
        "expected_savings": 42.51,  # Expected cost savings
        "expected_charge": 27.0,  # Expected charged energy
        "expected_discharge": 27.0,  # Expected discharged energy
    }


@pytest.fixture
def test_case_2025_01_05():
    """Test parameters for 2025-01-05 case."""
    return {
        "battery_soc": 10,  # Starting battery level
        "consumption": [5.2] * 24,  # Consumption pattern
        "expected_savings": 0.0,  # Expected cost savings
        "expected_charge": 0.0,  # Expected charged energy
        "expected_discharge": 0.0,  # Expected discharged energy
    }


@pytest.fixture
def test_case_2025_01_12():
    """Test parameters for 2025-01-12 case."""
    return {
        "battery_soc": 10,  # Starting battery level
        "consumption": [5.2] * 24,  # Consumption pattern
        "expected_savings": 22.54,  # Expected cost savings
        "expected_charge": 27.0,  # Expected charged energy
        "expected_discharge": 27.0,  # Expected discharged energy
    }


@pytest.fixture
def test_case_2025_01_13():
    """Test parameters for 2025-01-13 case."""
    return {
        "battery_soc": 10,  # Starting battery level
        "consumption": [5.2] * 24,  # Consumption pattern
        "expected_savings": 1.20,  # Expected cost savings
        "expected_charge": 6.0,  # Expected charged energy
        "expected_discharge": 5.2,  # Expected discharged energy
    }


@pytest.fixture
def mock_controller_with_params():
    """Provide a configurable mock controller with preset test parameters."""

    def _create(consumption=None, battery_soc=None):
        controller = MockHomeAssistantController()
        if consumption:
            controller.consumption_forecast = consumption
        if battery_soc is not None:
            controller.settings["battery_soc"] = battery_soc
        return controller

    return _create


# SYSTEM CONFIGURATION FIXTURES
@pytest.fixture
def base_system(mock_controller):
    """Provide a clean system instance with mock controller."""

    return BatterySystemManager(controller=mock_controller)


@pytest.fixture
def configured_system(mock_controller):
    """Configure a system instance for a specific test case."""

    def _configure(test_case, price_data):
        # Create system with mock controller
        system = BatterySystemManager(controller=mock_controller)

        # Apply test case configuration
        mock_controller.settings["battery_soc"] = test_case["battery_soc"]
        mock_controller.consumption_forecast = test_case["consumption"]

        # Explicitly set consumption predictions on the energy manager
        # This is the key fix - ensure the energy manager uses the correct consumption values
        system._energy_manager.set_consumption_predictions(test_case["consumption"])  # noqa: SLF001

        system.price_settings.use_actual_price = False

        # Create a mock price source with the test data
        system._price_manager.source = MockSource(price_data)  # noqa: SLF001

        return system

    return _configure


@pytest.fixture
def test_solar_adaptation_prices():
    """Price pattern for solar adaptation test with clear low/high periods."""
    return [
        0.2,
        0.2,
        0.2,  # Low prices hours 0-2
        0.3,
        0.4,
        0.5,  # Medium prices hours 3-5
        0.6,
        0.7,
        0.8,  # Higher prices hours 6-8
        1.2,
        1.4,
        1.6,  # Peak prices hours 9-11
        0.8,
        0.7,
        0.6,  # Decreasing prices hours 12-14
        0.5,
        0.4,
        0.3,  # Lower prices hours 15-17
        0.3,
        0.4,
        0.5,  # Evening hours 18-20
        0.3,
        0.2,
        0.2,  # Night hours 21-23
    ]


@pytest.fixture
def test_solar_adaptation_case():
    """Test case parameters for solar adaptation test."""
    return {
        "battery_soc": 20,  # Starting with 20% SOC
        "consumption": [5.2] * 24,  # Consistent consumption pattern
        "expected_savings": 30.0,  # Not actually checked in this test
        "expected_charge": 15.0,  # Not actually checked in this test
        "expected_discharge": 12.0,  # Not actually checked in this test
    }


@pytest.fixture
def system_with_test_prices(
    configured_system,
    mock_controller,
    test_solar_adaptation_case,
    test_solar_adaptation_prices,
):
    """Provide a system configured with test prices for solar adaptation testing."""
    # Create system using the configured_system factory
    system = configured_system(
        test_solar_adaptation_case, test_solar_adaptation_prices)

    # Make sure our system uses the same controller instance as the test will use
    system._controller = mock_controller  # noqa: SLF001

    # Additional specific configurations for solar tests
    system.battery_settings.total_capacity = 30.0
    system.battery_settings.min_soc = 10.0
    system.battery_settings.cycle_cost = 0.5

    # Ensure the energy manager knows about our settings too
    system._energy_manager.total_capacity = 30.0  # noqa: SLF001
    system._energy_manager.min_soc = 10.0  # noqa: SLF001
    system._energy_manager.reserved_capacity = 3.0  # 10% of 30 kWh  # noqa: SLF001

    return system
