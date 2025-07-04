"""Shared test fixtures and utilities for battery system integration tests."""

import logging
import os
import sys
from datetime import datetime

import pytest

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from core.bess.battery_system_manager import BatterySystemManager  # noqa: E402
from core.bess.models import (  # noqa: E402
    EconomicData,
    EnergyData,
    HourlyData,
    StrategyData,
)


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

        # Call tracking for integration tests
        self.calls = {
            "grid_charge": [],
            "discharge_rate": [],
            "charge_rate": [],
            "tou_segments": [],
        }

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

    def get_solar_forecast(self, day_offset=0, confidence_level="estimate"):
        """Get solar forecast data from Solcast integration."""
        return self.solar_forecast

    def grid_charge_enabled(self):
        """Check if grid charging is enabled."""
        return self.settings["grid_charge"]

    def set_grid_charge(self, enabled):
        """Enable or disable grid charging."""
        self.settings["grid_charge"] = enabled
        self.calls["grid_charge"].append(enabled)

    def get_solar_generation(self):
        """Get the current solar generation value."""
        return self.settings.get("solar_value", 0.0)

    def get_battery_charge_power(self):
        """Get the current battery charge power."""
        return self.settings["charge_power"]

    def get_battery_discharge_power(self):
        """Get the current battery discharge power."""
        return self.settings["discharge_power"]

    def set_discharging_power_rate(self, rate):
        """Set the discharging power rate."""
        self.settings["discharge_rate"] = rate
        self.calls["discharge_rate"].append(rate)

    def get_l1_current(self):
        """Get L1 phase current."""
        return self.settings["l1_current"]

    def get_l2_current(self):
        """Get L2 phase current."""
        return self.settings["l2_current"]

    def get_l3_current(self):
        """Get L3 phase current."""
        return self.settings["l3_current"]

    def get_charge_stop_soc(self):
        """Get charge stop SOC setting."""
        return self.settings["charge_stop_soc"]

    def get_discharge_stop_soc(self):
        """Get discharge stop SOC setting."""
        return self.settings["discharge_stop_soc"]

    def get_charging_power_rate(self):
        """Get charging power rate setting."""
        return self.settings["charging_power_rate"]

    def is_test_mode(self):
        """Check if test mode is enabled."""
        return self.settings["test_mode"]

    def get_tou_settings(self):
        """Get TOU settings."""
        return self.settings["tou_settings"]

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

    # Additional methods for integration tests
    def set_charging_power_rate(self, rate):
        """Set battery charge power rate."""
        self.settings["charge_rate"] = rate
        self.calls["charge_rate"].append(rate)
        return True

    def set_inverter_time_segment(
        self, segment_id, batt_mode, start_time, end_time, enabled
    ):
        """Set TOU time segment on inverter."""
        self.calls["tou_segments"].append(
            {
                "segment_id": segment_id,
                "batt_mode": batt_mode,
                "start_time": start_time,
                "end_time": end_time,
                "enabled": enabled,
            }
        )
        return True

    def read_inverter_time_segments(self):
        """Read current TOU segments from inverter."""
        return []

    def get_sensor_status(self, sensor_name):
        """Get sensor status for health checks."""
        return {"state": "available", "last_updated": datetime.now()}


class MockSensorCollector:
    """Mock sensor collector for integration tests - replaces InfluxDB dependency."""

    def __init__(self, controller, battery_capacity_kwh):
        """Initialize mock sensor collector."""
        self.controller = controller
        self.battery_capacity = battery_capacity_kwh

    def collect_hour_flows(self, hour):
        """Return realistic energy flow data for the given hour."""
        # Use controller's existing forecasts (which tests can configure)
        solar = (
            self.controller.solar_forecast[hour]
            if hour < len(self.controller.solar_forecast)
            else 0.0
        )
        consumption = (
            self.controller.consumption_forecast[hour]
            if hour < len(self.controller.consumption_forecast)
            else 4.0
        )

        # Simple energy balance calculation
        solar_excess = max(0, solar - consumption)
        grid_import = max(0, consumption - solar)

        return {
            "battery_soc": self.controller.get_battery_soc(),
            "battery_soe": self.controller.get_battery_soc()
            * self.battery_capacity
            / 100,
            "system_production": solar,
            "load_consumption": consumption,
            "import_from_grid": grid_import,
            "export_to_grid": solar_excess,
            "battery_charged": 0.0,
            "battery_discharged": 0.0,
            "strategic_intent": "IDLE",
        }

    def reconstruct_historical_flows(self, start_hour, end_hour):
        """Mock historical reconstruction - return empty for testing."""
        return {}


# MOCK CONTROLLER FIXTURE
@pytest.fixture
def mock_controller():
    """Provide a configured mock Home Assistant controller."""
    return MockHomeAssistantController()


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


# RAW PRICE DATA FIXTURES (keep these - used by scenario files and tests)
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


# SIMPLE TEST DATA FIXTURES (for unit tests)
@pytest.fixture
def sample_price_data(price_data_2024_08_16):
    """
    Provide sample price data for unit tests.
    Uses the 2024-08-16 data for consistency with original unit tests.
    """
    base_prices = price_data_2024_08_16
    return {"buy_price": base_prices, "sell_price": [p * 0.7 for p in base_prices]}


@pytest.fixture
def sample_consumption_data():
    """
    Provide sample consumption data for unit tests.
    Uses constant 5.2 kWh per hour, matching original unit tests.
    """
    return [5.2] * 24


@pytest.fixture
def sample_solar_data():
    """
    Provide sample solar production data for unit tests.
    Uses representative solar curve (zero at night, peak at noon).
    """
    return [
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.8,
        2.3,
        3.7,
        4.8,
        5.5,
        5.8,
        5.8,
        5.3,
        4.4,
        3.3,
        1.9,
        0.9,
        0.1,
        0.0,
        0.0,
        0.0,
        0.0,
    ]


# SYSTEM CONFIGURATION FIXTURES
@pytest.fixture
def base_system(mock_controller):
    """Provide a clean system instance with mock controller."""
    return BatterySystemManager(controller=mock_controller)


@pytest.fixture
def arbitrage_prices():
    """Price data that creates clear arbitrage opportunities for integration tests."""
    return [
        # Night - very cheap (arbitrage opportunity)
        0.10,
        0.10,
        0.10,
        # Early morning - rising
        0.20,
        0.30,
        0.40,
        # Day - moderate
        0.60,
        0.80,
        1.00,
        # Peak hours - expensive (discharge opportunity)
        1.50,
        1.80,
        2.00,
        # Afternoon - falling
        1.50,
        1.20,
        1.00,
        # Evening - moderate
        0.80,
        0.60,
        0.40,
        # Evening peak - moderate
        0.50,
        0.60,
        0.70,
        # Late night - cheap again
        0.30,
        0.20,
        0.10,
    ]


@pytest.fixture
def realistic_consumption_pattern():
    """Realistic consumption pattern for integration tests."""
    return [
        4.5,
        4.2,
        4.0,
        3.8,
        3.5,
        3.2,  # Night hours 0-5
        3.8,
        4.5,
        5.2,
        6.0,
        6.5,
        7.0,  # Morning rise 6-11
        7.2,
        6.8,
        6.5,
        6.2,
        5.8,
        5.5,  # Afternoon 12-17
        5.8,
        6.2,
        6.5,
        5.8,
        5.2,
        4.8,  # Evening 18-23
    ]


@pytest.fixture
def realistic_solar_pattern():
    """Realistic solar pattern for integration tests."""
    return [
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,  # Night 0-5
        0.5,
        2.0,
        4.0,
        6.0,
        8.0,
        9.0,  # Morning rise 6-11
        9.5,
        9.0,
        8.0,
        6.5,
        4.5,
        2.5,  # Afternoon 12-17
        1.0,
        0.2,
        0.0,
        0.0,
        0.0,
        0.0,  # Evening/Night 18-23
    ]


@pytest.fixture
def battery_system_integration(mock_controller, monkeypatch):
    """Create BatterySystemManager for integration tests with minimal external mocking."""
    from core.bess.price_manager import MockSource

    # Mock only external dependencies
    monkeypatch.setattr(
        "core.bess.sensor_collector.SensorCollector", MockSensorCollector
    )

    # Use MockSource for price data (replaces external price API)
    price_source = MockSource([1.0] * 24)

    # Create system with real internal components
    system = BatterySystemManager(controller=mock_controller, price_source=price_source)

    return system


@pytest.fixture
def battery_system_with_arbitrage(mock_controller, arbitrage_prices, monkeypatch):
    """Create BatterySystemManager with arbitrage price opportunities."""
    from core.bess.price_manager import MockSource

    # Mock external dependencies
    monkeypatch.setattr(
        "core.bess.sensor_collector.SensorCollector", MockSensorCollector
    )

    # Use arbitrage prices
    price_source = MockSource(arbitrage_prices)

    system = BatterySystemManager(controller=mock_controller, price_source=price_source)

    return system


@pytest.fixture
def sample_new_hourly_data():
    """Provide sample HourlyData object for testing."""
    energy_data = EnergyData(
        solar_generated=5.0,
        home_consumed=3.0,
        grid_imported=0.0,
        grid_exported=2.0,
        battery_charged=0.0,
        battery_discharged=0.0,
        battery_soc_start=50.0,
        battery_soc_end=50.0,
    )

    economic_data = EconomicData(
        buy_price=1.2,
        sell_price=0.8,
        hourly_cost=0.0,
        hourly_savings=2.4,
        battery_cycle_cost=0.0,
    )

    strategy_data = StrategyData(strategic_intent="IDLE", battery_action=0.0)

    return HourlyData(
        hour=12,
        energy=energy_data,
        economic=economic_data,
        strategy=strategy_data,
        timestamp=datetime(2025, 7, 2, 12, 0, 0),
        data_source="predicted",
    )


# Aliases for backward compatibility with new test files
@pytest.fixture
def battery_system(battery_system_integration):
    """Alias for integration test compatibility."""
    return battery_system_integration
