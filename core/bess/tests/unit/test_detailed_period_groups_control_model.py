"""get_detailed_period_groups() feeds the Schedule Overview table shown
in issue #415's screenshot -- must stop fabricating a mode label."""

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


def test_vpp_solar_export_group_has_no_mode_and_correct_vpp_fields(battery_settings):
    controller = SolaxModbusGrowattController(
        battery_settings=battery_settings, control_mode="vpp"
    )
    groups = controller.get_detailed_period_groups(
        intents=["SOLAR_EXPORT"] * 4,
        actions=[0.0] * 4,
    )
    assert len(groups) == 1
    group = groups[0]
    assert "mode" not in group
    assert group["vpp_power_pct"] == 0
    assert group["vpp_remote_control"] is True
    assert group["intent"] == "SOLAR_EXPORT"
