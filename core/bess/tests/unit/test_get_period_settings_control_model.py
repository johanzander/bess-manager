"""get_period_settings() must stop always returning batt_mode -- issue #415."""

import pytest

from core.bess.dp_schedule import DPSchedule
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


def test_vpp_mode_grid_charging_display_matches_throttled_charge_rate(
    battery_settings: BatterySettings,
) -> None:
    """#754: vpp_power_pct must match the plan's actual (possibly
    fuse-throttled) charge_rate, not always show 100 -- otherwise the
    write path and the displayed period disagree about what was commanded.
    """
    controller = SolaxModbusGrowattController(
        battery_settings=battery_settings, control_mode="vpp"
    )
    controller.strategic_intents = ["GRID_CHARGING"] * 96
    actions = [0.0] * 96
    actions[25] = 0.4  # 1.6 kW, throttled well below 5.0 kW max_charge_power_kw
    controller.current_schedule = DPSchedule(
        actions=actions,
        state_of_energy=[25.0] * 97,
        prices=[0.1] * 96,
        original_dp_results={"strategic_intent": controller.strategic_intents},
    )

    settings = controller.get_period_settings(period=25)  # 06:15

    assert settings["charge_rate"] == 32
    assert settings["vpp_power_pct"] == settings["charge_rate"]
    assert settings["vpp_remote_control"] is True
