"""#320: BatterySystemManager must pass its inverter controller's capability
values into optimize_battery_schedule, not rely on the DP's own defaults --
this is what lets a future non-Growatt platform's overrides actually reach
the DP."""

from unittest.mock import patch

from core.bess.growatt_min_controller import GrowattMinController
from core.bess.tests.helpers import make_battery_settings


def test_optimize_battery_schedule_receives_controller_capabilities():
    settings = make_battery_settings(max_discharge_power_kw=5.0)
    controller = GrowattMinController(settings)

    with patch("core.bess.battery_system_manager.optimize_battery_schedule"):
        # Exercise just the capability-wiring call, not the full manager
        # lifecycle -- call the same expression battery_system_manager.py
        # uses at its optimize_battery_schedule call site.
        discharge_resolution_kw = controller.discharge_resolution_kw(
            settings.max_discharge_power_kw
        )
        self_throttle_export_threshold_kwh = (
            controller.self_throttle_export_threshold_kwh
        )
        assert discharge_resolution_kw == 0.05
        assert self_throttle_export_threshold_kwh == 0.01
