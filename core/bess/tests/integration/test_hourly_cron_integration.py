"""
Integration test for hourly cron job functionality.

Updated for new BatterySystemManager API.
"""

import logging
from datetime import datetime

import pytest

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.price_manager import MockSource
from core.bess.settings import BatterySettings

logger = logging.getLogger(__name__)


class MockHistoricalDataStore:
    """Mock historical data store for tests."""
    
    def __init__(self, battery_capacity_kwh):
        self.battery_capacity = battery_capacity_kwh
    
    def has_data_for_hour(self, hour):
        return False  # No historical data in tests
    
    def get_completed_hours(self):
        return []
    
    def get_hour_event(self, hour):
        return None
    
    def record_hour_completion(self, event):
        pass
    
    def get_latest_battery_state(self):
        return 50.0, 15.0  # 50% SOC, 15 kWh


class MockSensorCollector:
    """Mock sensor collector that doesn't require InfluxDB."""
    
    def __init__(self, ha_controller, battery_capacity_kwh):
        self.ha_controller = ha_controller
        self.battery_capacity = battery_capacity_kwh
    
    def collect_hour_flows(self, hour):
        """Return mock flows for any hour."""
        return {
            "battery_soc": 50.0,
            "battery_soe": 15.0,
            "system_production": 0.0,
            "load_consumption": 4.0,
            "import_from_grid": 4.0,
            "export_to_grid": 0.0,
            "battery_charged": 0.0,
            "battery_discharged": 0.0,
            "strategic_intent": "IDLE"
        }
    
    def reconstruct_historical_flows(self, start_hour, end_hour):
        """Return empty dict - no historical data in tests."""
        return {}


class MockDailyViewBuilder:
    """Mock daily view builder for tests."""
    
    def __init__(self, historical_store, schedule_store, battery_capacity, cycle_cost):
        pass
    
    def log_complete_daily_schedule(self, daily_view):
        """Mock logging method."""
        pass

    def build_daily_view(self, current_hour, buy_price, sell_price=None):
        """Return minimal mock daily view."""
        from core.bess.daily_view_builder import DailyView, HourlyData
        
        hourly_data = []
        for hour in range(24):
            price = buy_price[hour] if isinstance(buy_price, list) and hour < len(buy_price) else 1.0
            hourly_data.append(HourlyData(
                hour=hour, data_source="predicted", 
                solar_generated=0, home_consumed=4,
                grid_imported=4, grid_exported=0,
                battery_charged=0, battery_discharged=0,
                battery_soc_start=50, battery_soc_end=50,
                buy_price=price, sell_price=price * 0.6,
                hourly_cost=4.0, hourly_savings=0.0
            ))
        
        return DailyView(
            date=datetime.now(), current_hour=current_hour,
            hourly_data=hourly_data, total_daily_savings=0,
            actual_savings_so_far=0, predicted_remaining_savings=0,
            actual_hours_count=0, predicted_hours_count=24,
            data_sources=["predicted"] * 24
        )


class MockGrowattController:
    """Mock controller with all required methods."""

    def __init__(self):
        self.grid_charge_calls = []
        self.discharge_rate_calls = []
        self.tou_segment_calls = []
        self.current_settings = {
            "grid_charge": False,
            "discharge_rate": 0,
            "battery_soc": 45.0,
        }

    def get_battery_soc(self):
        return self.current_settings["battery_soc"]

    def get_estimated_consumption(self):
        return [4.5] * 24

    def get_solar_forecast(self):
        return [3.0 if 8 <= h <= 16 else 0.0 for h in range(24)]

    def grid_charge_enabled(self):
        return self.current_settings["grid_charge"]

    def get_discharging_power_rate(self):
        return self.current_settings["discharge_rate"]

    def get_charging_power_rate(self):
        return 100

    def set_grid_charge(self, enable):
        self.grid_charge_calls.append(enable)
        self.current_settings["grid_charge"] = enable
        logger.info(f"[MOCK] Set grid charge: {enable}")

    def set_discharging_power_rate(self, rate):
        self.discharge_rate_calls.append(rate)
        self.current_settings["discharge_rate"] = rate
        logger.info(f"[MOCK] Set discharge rate: {rate}%")

    def set_charging_power_rate(self, rate):
        logger.info(f"[MOCK] Set charging rate: {rate}%")

    def set_inverter_time_segment(self, segment_id, batt_mode, start_time, end_time, enabled):
        segment_call = {
            "segment_id": segment_id,
            "batt_mode": batt_mode,
            "start_time": start_time,
            "end_time": end_time,
            "enabled": enabled,
        }
        self.tou_segment_calls.append(segment_call)
        logger.info(f"[MOCK] Set TOU segment {segment_id}: {start_time}-{end_time} ({batt_mode})")

    def read_inverter_time_segments(self):
        return []

    def reset_call_history(self):
        self.grid_charge_calls.clear()
        self.discharge_rate_calls.clear()
        self.tou_segment_calls.clear()


@pytest.fixture
def test_prices():
    """Test price pattern for arbitrage."""
    return [
        0.2, 0.2, 0.2,  # Cheap night 0-2
        0.3, 0.4, 0.5,  # Rising 3-5
        0.6, 0.7, 0.8,  # Morning 6-8
        1.2, 1.4, 1.6,  # Peak 9-11
        0.8, 0.7, 0.6,  # Falling 12-14
        0.5, 0.4, 0.3,  # Afternoon 15-17
        0.3, 0.4, 0.5,  # Evening 18-20
        0.3, 0.2, 0.2,  # Night 21-23
    ]


@pytest.fixture
def simple_system(test_prices):
    """Create system with mock controller and test prices."""
    controller = MockGrowattController()
    controller.current_settings["battery_soc"] = 20.0

    # Create price source
    price_source = MockSource(test_prices)

    # Create system with proper initialization
    system = BatterySystemManager(controller=controller, price_source=price_source)
    
    # Replace components with mocks
    system.sensor_collector = MockSensorCollector(controller, system.battery_settings.total_capacity)
    system.historical_store = MockHistoricalDataStore(system.battery_settings.total_capacity)
    system.daily_view_builder = MockDailyViewBuilder(None, None, system.battery_settings.total_capacity, 0.4)
    
    # Store controller for tests
    system._test_controller = controller
    
    return system


def simulate_hourly_cron_job(system, controller, hour):
    """Simulate hourly cron job."""
    logger.info(f"\n{'='*60}")
    logger.info(f"SIMULATING HOURLY CRON JOB - HOUR {hour:02d}:00")
    logger.info(f"{'='*60}")

    # Force different initial settings to ensure calls
    controller.current_settings["grid_charge"] = not controller.current_settings["grid_charge"]
    controller.current_settings["discharge_rate"] = 100 if controller.current_settings["discharge_rate"] < 50 else 0

    # Run schedule update
    success = system.update_battery_schedule(hour)
    
    if not success:
        logger.error(f"Schedule update failed for hour {hour}")
        return None, {}

    # Get current settings
    current_settings = system._schedule_manager.get_hourly_settings(hour)
    
    logger.info(f"Applied settings for hour {hour:02d}: {current_settings}")
    
    return None, current_settings


def test_basic_schedule_creation(simple_system):
    """Test basic schedule creation works."""
    system = simple_system
    controller = system._test_controller

    # Create tomorrow's schedule
    success = system.update_battery_schedule(0, prepare_next_day=True)
    assert success, "Should create tomorrow's schedule"

    # Verify TOU segments were created
    assert len(controller.tou_segment_calls) > 0, "Should create TOU segments"
    logger.info(f"✓ Created {len(controller.tou_segment_calls)} TOU segments")


def test_hourly_updates(simple_system):
    """Test hourly schedule updates."""
    system = simple_system
    controller = system._test_controller

    # Create initial schedule
    success = system.update_battery_schedule(0, prepare_next_day=True)
    assert success, "Should create initial schedule"

    # Reset call history
    controller.reset_call_history()

    # Test hourly updates
    test_hours = [6, 10, 18]
    
    for hour in test_hours:
        # Force different settings
        controller.current_settings["grid_charge"] = True
        controller.current_settings["discharge_rate"] = 50

        grid_calls_before = len(controller.grid_charge_calls)
        discharge_calls_before = len(controller.discharge_rate_calls)

        success = system.update_battery_schedule(hour)
        assert success, f"Should update schedule for hour {hour}"

        # Check calls were made
        grid_calls_after = len(controller.grid_charge_calls)
        discharge_calls_after = len(controller.discharge_rate_calls)

        assert grid_calls_after > grid_calls_before, f"Should make grid calls for hour {hour}"
        assert discharge_calls_after > discharge_calls_before, f"Should make discharge calls for hour {hour}"

    logger.info("✓ Hourly updates work correctly")


def test_schedule_comparison_logic(simple_system):
    """Test that schedules are only applied when needed."""
    system = simple_system
    controller = system._test_controller

    # Create initial schedule
    success = system.update_battery_schedule(8, prepare_next_day=False)
    assert success, "Should create schedule"
    
    initial_tou_calls = len(controller.tou_segment_calls)

    # Update again with same conditions - should not change TOU
    success = system.update_battery_schedule(8, prepare_next_day=False)
    assert success, "Should update schedule"
    
    final_tou_calls = len(controller.tou_segment_calls)
    
    # TOU calls should be minimal since schedule didn't change
    new_tou_calls = final_tou_calls - initial_tou_calls
    assert new_tou_calls <= 5, f"Should not make excessive TOU calls: {new_tou_calls}"
    
    logger.info("✓ Schedule comparison logic working")


def test_settings_retrieval(simple_system):
    """Test that settings can be retrieved correctly."""
    system = simple_system
    
    # Create schedule
    success = system.update_battery_schedule(0, prepare_next_day=True)
    assert success, "Should create schedule"
    
    # Test settings retrieval
    settings = system.get_settings()
    assert "battery" in settings
    assert "home" in settings  
    assert "price" in settings
    
    logger.info("✓ Settings retrieval works")


def test_daily_view_creation(simple_system):
    """Test daily view creation."""
    system = simple_system
    
    # Create schedule first
    success = system.update_battery_schedule(12, prepare_next_day=False) 
    assert success, "Should create schedule"
    
    # Get daily view
    daily_view = system.get_current_daily_view()
    assert daily_view is not None, "Should return daily view"
    assert len(daily_view.hourly_data) == 24, "Should have 24 hours"
    
    logger.info("✓ Daily view creation works")


def test_full_day_simulation(simple_system):
    """Test full day simulation."""
    system = simple_system
    controller = system._test_controller

    logger.info("=== FULL DAY SIMULATION ===")

    # Create initial schedule
    success = system.update_battery_schedule(0, prepare_next_day=True)
    assert success, "Should create tomorrow's schedule"

    # Track decisions
    hourly_decisions = []
    test_hours = [0, 6, 12, 18]

    for hour in test_hours:
        _, settings = simulate_hourly_cron_job(system, controller, hour)
        
        if settings:  # Only record if we got settings
            hourly_decisions.append({
                "hour": hour,
                "grid_charge": settings.get("grid_charge", False),
                "discharge_rate": settings.get("discharge_rate", 0),
            })

    # Verify we got some decisions
    assert len(hourly_decisions) > 0, "Should have some hourly decisions"
    
    logger.info("Hour | Grid Charge | Discharge %")
    logger.info("-" * 35)
    for decision in hourly_decisions:
        logger.info(f"{decision['hour']:4d} | {decision['grid_charge']!s:11} | {decision['discharge_rate']:9d}")

    logger.info("✓ Full day simulation completed")