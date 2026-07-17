"""Tests for #320: platform-capability methods on InverterController.

Both default to today's hardcoded Growatt behavior (percent-of-max discharge
grid, 0.01 kWh self-throttle threshold) so this is a pure addition -- no
existing platform's behavior changes until a future platform overrides one.
"""

from core.bess.growatt_min_controller import GrowattMinController
from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.tests.helpers import make_battery_settings


def test_discharge_resolution_kw_defaults_to_one_percent_of_max():
    settings = make_battery_settings(max_discharge_power_kw=5.0)
    controller = GrowattMinController(settings)
    assert controller.discharge_resolution_kw(5.0) == 0.05


def test_self_throttle_export_threshold_kwh_defaults_to_one_hundredth():
    settings = make_battery_settings()
    controller = GrowattMinController(settings)
    assert controller.self_throttle_export_threshold_kwh == 0.01


def test_sph_inherits_the_same_defaults():
    settings = make_battery_settings(max_discharge_power_kw=10.0)
    controller = GrowattSphController(settings)
    assert controller.discharge_resolution_kw(10.0) == 0.1
    assert controller.self_throttle_export_threshold_kwh == 0.01
