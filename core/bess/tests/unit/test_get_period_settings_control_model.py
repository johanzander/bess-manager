"""get_period_settings() must stop always returning batt_mode -- issue #415."""

import pytest

from core.bess.settings import BatterySettings
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController


@pytest.fixture
def battery_settings():
    return BatterySettings(
        total_capacity=50.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        min_soc=10.0,
        max_soc=95.0,
        cycle_cost_per_kwh=0.05,
    )


def test_vpp_mode_solar_export_period_has_no_batt_mode_and_correct_vpp_fields(
    battery_settings,
):
    controller = SolaxModbusGrowattController(
        battery_settings=battery_settings, control_mode="vpp"
    )
    controller.strategic_intents = ["SOLAR_EXPORT"] * 96
    settings = controller.get_period_settings(period=25)  # 06:15
    assert "batt_mode" not in settings
    assert settings["vpp_power_pct"] == 0
    assert settings["vpp_remote_control"] is True  # grid-first hold, matches issue #415
    assert settings["strategic_intent"] == "SOLAR_EXPORT"
