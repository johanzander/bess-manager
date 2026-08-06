"""Regression test for #469: log_detailed_schedule() crashed with
KeyError('batt_mode') for VPP-mode Growatt controllers.

get_detailed_period_groups() only populates "batt_mode" for
CONTROL_MODEL == "tou_register" groups; vpp_power groups carry
"vpp_power_pct"/"vpp_remote_control" instead (inverter_controller.py
_mode_display_fields). GrowattMinController.log_detailed_schedule()
hardcoded group["batt_mode"], which SolaxModbusGrowattController in VPP
mode never sets -- reproduced live via the ci-growatt-vpp E2E scenario.
"""

from core.bess.settings import BatterySettings
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController


def battery_settings():
    return BatterySettings(
        total_capacity=50.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        min_soc=10.0,
        max_soc=95.0,
        cycle_cost_per_kwh=0.05,
    )


def test_log_detailed_schedule_does_not_crash_in_vpp_mode():
    controller = SolaxModbusGrowattController(
        battery_settings=battery_settings(), control_mode="vpp"
    )
    controller.strategic_intents = ["SOLAR_EXPORT"] * 4

    controller.log_detailed_schedule()
