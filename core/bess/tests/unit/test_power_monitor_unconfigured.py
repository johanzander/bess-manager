import pytest  # type: ignore

from core.bess.power_monitor import HomePowerMonitor
from core.bess.settings import BatterySettings, HomeSettings


@pytest.fixture
def unconfigured_controller():
    class UnconfiguredController:
        """Mock controller matching the real HomeAssistantAPIController's
        behavior when phase-current sensors are not mapped: validate_methods_sensors
        reports status "not_configured" (see ha_api_controller.py:938-963),
        and the method itself would raise if ever called directly."""

        def __init__(self):
            self.sensors = {}

        def validate_methods_sensors(self, method_list):
            return [
                {
                    "method_name": method,
                    "name": method,
                    "sensor_key": method,
                    "entity_id": "Not configured",
                    "status": "not_configured",
                    "error": f"No entity ID configured for sensor '{method}'",
                }
                for method in method_list
            ]

        def get_l1_current(self):
            raise AssertionError("should not be called — sensor is unmapped")

        def get_l2_current(self):
            raise AssertionError("should not be called — sensor is unmapped")

        def get_l3_current(self):
            raise AssertionError("should not be called — sensor is unmapped")

        def get_charging_power_rate(self):
            raise AssertionError("should not be called — sensor is unmapped")

    return UnconfiguredController()


def test_check_health_unconfigured_sensors_when_enabled(unconfigured_controller):
    """Power monitoring enabled + phase sensors unmapped -> health check must
    report ERROR, not silently report OK (the bug: real bess-manager debug
    bundle from 2026-08-07 showed 'Overall Status: OK, Warnings: 0' while
    the feature crashed every 5-minute cycle)."""
    monitor = HomePowerMonitor(
        unconfigured_controller,
        HomeSettings(power_monitoring_enabled=True, phase_count=3),
        BatterySettings(),
    )
    health = monitor.check_health()
    assert len(health) == 1
    assert health[0]["status"] == "ERROR"
    for check in health[0]["checks"]:
        assert check["status"] == "ERROR"
        assert "not configured" in check["error"].lower()


def test_check_health_disabled_still_ok(unconfigured_controller):
    """Sanity: disabled power monitoring must remain unaffected (existing behavior)."""
    monitor = HomePowerMonitor(
        unconfigured_controller,
        HomeSettings(power_monitoring_enabled=False),
        BatterySettings(),
    )
    health = monitor.check_health()
    assert health[0]["status"] == "OK"
