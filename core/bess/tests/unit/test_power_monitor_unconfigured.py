import pytest  # type: ignore

from core.bess.power_monitor import HomePowerMonitor
from core.bess.settings import BatterySettings, HomeSettings


@pytest.fixture
def unconfigured_controller():
    class UnconfiguredController:
        """Mock controller with no sensors configured."""

        def __init__(self):
            self.sensors = {}

        def validate_methods_sensors(self, method_list):
            # Simulate all methods as unconfigured
            return [
                {
                    "method_name": method,
                    "sensor_key": None,
                    "entity_id": None,
                    "status": "error",
                    "error": f"No entity ID configured for {method}",
                    "current_value": None,
                }
                for method in method_list
            ]

        def get_l1_current(self):
            raise NotImplementedError("No entity ID configured for get_l1_current")

        def get_l2_current(self):
            raise NotImplementedError("No entity ID configured for get_l2_current")

        def get_l3_current(self):
            raise NotImplementedError("No entity ID configured for get_l3_current")

    return UnconfiguredController()


def test_check_health_unconfigured_sensors(unconfigured_controller):
    monitor = HomePowerMonitor(
        unconfigured_controller, HomeSettings(), BatterySettings()
    )
    health = monitor.check_health()
    assert isinstance(health, list)
    assert health[0]["status"] == "ERROR" or any(
        check["status"] == "ERROR" for check in health[0]["checks"]
    )
    for check in health[0]["checks"]:
        if check["status"] == "ERROR":
            assert "No entity ID configured" in (
                check["error"] or ""
            ) or "Failed to calculate available charging power" in (
                check["error"] or ""
            )
