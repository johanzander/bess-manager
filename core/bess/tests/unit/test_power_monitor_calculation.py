"""Tests for power monitor charging power calculation.

This test suite verifies that the fuse protection algorithm correctly calculates
available charging power based on phase loads and battery constraints.
"""

import pytest  # type: ignore

from core.bess.power_monitor import HomePowerMonitor
from core.bess.settings import BatterySettings, HomeSettings


class MockController:
    """Mock Home Assistant controller for testing."""

    def __init__(self, l1_current=0.0, l2_current=0.0, l3_current=0.0):
        """Initialize mock controller with phase currents."""
        self.l1_current = l1_current
        self.l2_current = l2_current
        self.l3_current = l3_current
        self.grid_charge = False
        self.charging_power_rate = 0

    def get_l1_current(self):
        return self.l1_current

    def get_l2_current(self):
        return self.l2_current

    def get_l3_current(self):
        return self.l3_current

    def grid_charge_enabled(self):
        return self.grid_charge

    def get_charging_power_rate(self):
        return self.charging_power_rate

    def set_charging_power_rate(self, rate):
        self.charging_power_rate = rate

    def validate_methods_sensors(self, method_list):
        return [
            {
                "method_name": method,
                "sensor_key": f"mock_{method}",
                "entity_id": f"sensor.mock_{method}",
                "status": "ok",
                "error": None,
                "current_value": 0.0,
            }
            for method in method_list
        ]


@pytest.fixture
def standard_settings():
    """Standard settings matching user's configuration."""
    home = HomeSettings(
        max_fuse_current=25,  # 25A fuse
        voltage=230,  # 230V
        safety_margin=0.95,  # 95% safety margin
    )
    battery = BatterySettings(
        max_charge_power_kw=15.0,  # 15kW max charge power
        charging_power_rate=98,  # Default 98% target
    )
    return home, battery


def test_available_power_calculation_user_scenario(standard_settings):
    """Test the exact scenario from user's logs.

    User has:
    - 25A fuse, 230V, 95% safety margin
    - 15kW max battery charge power
    - Current loads: L1=1541W, L2=1449W, L3=1840W (most loaded)
    - Target charging: 98%

    Expected behavior:
    - Max power per phase with safety: 230V * 25A * 0.95 = 5,462.5W
    - Available on phase 3: 5,462.5W - 1,840W = 3,622.5W
    - Max battery power per phase: 15kW / 3 = 5,000W
    - Available as % of battery max: (3,622.5 / 5,000) * 100 = 72.45%
    - Recommended: min(72.45%, 98%) = 72.45%
    """
    home, battery = standard_settings

    # Current loads from user's logs (convert to amperes)
    controller = MockController(
        l1_current=1541 / 230,  # ~6.7A
        l2_current=1449 / 230,  # ~6.3A
        l3_current=1840 / 230,  # ~8.0A (most loaded)
    )

    monitor = HomePowerMonitor(controller, home, battery)

    # Calculate available charging power
    available_pct = monitor.calculate_available_charging_power()

    # Verify the calculation is correct
    expected_available_pct = 72.45  # (3622.5W / 5000W) * 100
    assert (
        abs(available_pct - expected_available_pct) < 0.1
    ), f"Expected ~72.45%, got {available_pct:.2f}%"

    # OLD (BUGGY) algorithm would give 66.3%
    # NEW (FIXED) algorithm gives 72.45%
    # This is a ~6% improvement = ~0.9kW more charging power

    # Verify actual charging power in watts
    actual_charge_power_kw = (available_pct / 100) * battery.max_charge_power_kw
    expected_charge_power_kw = 10.87  # 72.45% of 15kW
    assert (
        abs(actual_charge_power_kw - expected_charge_power_kw) < 0.1
    ), f"Expected ~10.87kW, got {actual_charge_power_kw:.2f}kW"

    # Verify per-phase calculation doesn't exceed fuse limit
    charge_power_per_phase_w = (actual_charge_power_kw * 1000) / 3  # ~3,623W
    total_power_phase3 = 1840 + charge_power_per_phase_w  # ~5,463W
    max_allowed = home.voltage * home.max_fuse_current * home.safety_margin  # 5,462.5W

    assert (
        total_power_phase3 <= max_allowed + 1
    ), f"Phase 3 would exceed fuse limit: {total_power_phase3:.0f}W > {max_allowed:.0f}W"


def test_zero_household_load_allows_full_charging(standard_settings):
    """With no household load, should allow up to battery max or fuse limit."""
    home, battery = standard_settings

    controller = MockController(l1_current=0.0, l2_current=0.0, l3_current=0.0)

    monitor = HomePowerMonitor(controller, home, battery)
    available_pct = monitor.calculate_available_charging_power()

    # Available power per phase: 5,462.5W (full capacity with safety margin)
    # Max battery power per phase: 5,000W
    # Available %: (5,462.5 / 5,000) * 100 = 109.25%
    # But limited by target charging (98%)
    assert (
        abs(available_pct - 98.0) < 0.1
    ), f"Expected 98% (target limit), got {available_pct:.2f}%"


def test_high_household_load_limits_charging(standard_settings):
    """High household load should significantly limit charging power."""
    home, battery = standard_settings

    # Simulate high household load: 4,000W on phase 3
    controller = MockController(
        l1_current=3000 / 230,  # ~13A
        l2_current=3000 / 230,  # ~13A
        l3_current=4000 / 230,  # ~17.4A (most loaded)
    )

    monitor = HomePowerMonitor(controller, home, battery)
    available_pct = monitor.calculate_available_charging_power()

    # Available power on phase 3: 5,462.5W - 4,000W = 1,462.5W
    # Max battery power per phase: 5,000W
    # Available %: (1,462.5 / 5,000) * 100 = 29.25%
    expected_pct = 29.25
    assert (
        abs(available_pct - expected_pct) < 0.5
    ), f"Expected ~{expected_pct}%, got {available_pct:.2f}%"


def test_near_fuse_limit_prevents_charging(standard_settings):
    """When near fuse limit, should allow minimal or no charging."""
    home, battery = standard_settings

    # Simulate load near safety limit: 5,200W on phase 3
    controller = MockController(
        l1_current=5000 / 230,  # ~21.7A
        l2_current=5000 / 230,  # ~21.7A
        l3_current=5200 / 230,  # ~22.6A (near 23.75A safety limit)
    )

    monitor = HomePowerMonitor(controller, home, battery)
    available_pct = monitor.calculate_available_charging_power()

    # Available power on phase 3: 5,462.5W - 5,200W = 262.5W
    # Max battery power per phase: 5,000W
    # Available %: (262.5 / 5,000) * 100 = 5.25%
    expected_pct = 5.25
    assert (
        abs(available_pct - expected_pct) < 0.5
    ), f"Expected ~{expected_pct}%, got {available_pct:.2f}%"


def test_balanced_phases_uses_most_loaded(standard_settings):
    """Calculation should use the most loaded phase, not average."""
    home, battery = standard_settings

    # Balanced low load on L1 and L2, high load on L3
    controller = MockController(
        l1_current=1000 / 230,  # ~4.3A
        l2_current=1000 / 230,  # ~4.3A
        l3_current=3000 / 230,  # ~13A (most loaded)
    )

    monitor = HomePowerMonitor(controller, home, battery)
    available_pct = monitor.calculate_available_charging_power()

    # Should be based on L3 (3,000W), not average (1,667W)
    # Available on L3: 5,462.5W - 3,000W = 2,462.5W
    # As % of battery max per phase: (2,462.5 / 5,000) * 100 = 49.25%
    expected_pct = 49.25
    assert (
        abs(available_pct - expected_pct) < 0.5
    ), f"Expected ~{expected_pct}%, got {available_pct:.2f}%"


def test_calculation_improvement_vs_old_algorithm(standard_settings):
    """Verify the fix provides more charging power than old algorithm.

    This test documents the improvement from the bug fix.
    """
    home, battery = standard_settings

    # User's actual scenario
    controller = MockController(
        l1_current=1541 / 230, l2_current=1449 / 230, l3_current=1840 / 230
    )

    monitor = HomePowerMonitor(controller, home, battery)
    new_available_pct = monitor.calculate_available_charging_power()

    # Old (buggy) algorithm would calculate:
    # max_load_pct = (1840 / 5462.5) * 100 = 33.7%
    # available_pct = 100 - 33.7 = 66.3%
    old_buggy_result = 66.3

    # New (fixed) algorithm calculates:
    # available_pct = ((5462.5 - 1840) / 5000) * 100 = 72.45%
    new_correct_result = 72.45

    assert (
        abs(new_available_pct - new_correct_result) < 0.1
    ), f"Expected {new_correct_result}%, got {new_available_pct:.2f}%"

    # Verify improvement
    improvement_pct = new_available_pct - old_buggy_result
    improvement_kw = (improvement_pct / 100) * battery.max_charge_power_kw

    assert improvement_pct > 5, f"Expected >5% improvement, got {improvement_pct:.2f}%"
    assert (
        improvement_kw > 0.8
    ), f"Expected >0.8kW improvement, got {improvement_kw:.2f}kW"


def test_different_battery_sizes(standard_settings):
    """Test that calculation works correctly with different battery max power."""
    home, _ = standard_settings

    # Test with smaller battery (10kW max)
    battery_small = BatterySettings(max_charge_power_kw=10.0, charging_power_rate=98)

    controller = MockController(
        l1_current=1541 / 230, l2_current=1449 / 230, l3_current=1840 / 230
    )

    monitor = HomePowerMonitor(controller, home, battery_small)
    available_pct = monitor.calculate_available_charging_power()

    # Available power: 3,622.5W
    # Max battery per phase: 10kW / 3 = 3,333W
    # Available %: (3,622.5 / 3,333) * 100 = 108.7%
    # Limited by target (98%)
    assert (
        abs(available_pct - 98.0) < 0.5
    ), f"Expected 98% (target limit), got {available_pct:.2f}%"


def test_different_safety_margins():
    """Test that different safety margins affect available power correctly."""
    battery = BatterySettings(max_charge_power_kw=15.0, charging_power_rate=98)

    # Test with 98% safety margin (less conservative)
    home_98 = HomeSettings(max_fuse_current=25, voltage=230, safety_margin=0.98)

    controller = MockController(
        l1_current=1541 / 230, l2_current=1449 / 230, l3_current=1840 / 230
    )

    monitor_98 = HomePowerMonitor(controller, home_98, battery)
    available_pct_98 = monitor_98.calculate_available_charging_power()

    # Max per phase: 230 * 25 * 0.98 = 5,635W
    # Available: 5,635 - 1,840 = 3,795W
    # As %: (3,795 / 5,000) * 100 = 75.9%
    assert (
        abs(available_pct_98 - 75.9) < 0.5
    ), f"Expected ~75.9%, got {available_pct_98:.2f}%"

    # Test with 90% safety margin (more conservative)
    home_90 = HomeSettings(max_fuse_current=25, voltage=230, safety_margin=0.90)

    monitor_90 = HomePowerMonitor(controller, home_90, battery)
    available_pct_90 = monitor_90.calculate_available_charging_power()

    # Max per phase: 230 * 25 * 0.90 = 5,175W
    # Available: 5,175 - 1,840 = 3,335W
    # As %: (3,335 / 5,000) * 100 = 66.7%
    assert (
        abs(available_pct_90 - 66.7) < 0.5
    ), f"Expected ~66.7%, got {available_pct_90:.2f}%"

    # More safety margin should give more available power
    assert (
        available_pct_98 > available_pct_90
    ), "Higher safety margin should allow more charging"
