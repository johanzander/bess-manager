"""Unit tests for the inverter simulator: ControlCommand, derive_control_command,
mode_to_power, and simulate. All hand-computed; no optimizer invocation."""

from core.bess.simulation.inverter_simulator import (
    derive_control_command,
)
from core.bess.tests.helpers import make_battery_settings

# ---------------------------------------------------------------------------
# Task 1: ControlCommand + derive_control_command
# ---------------------------------------------------------------------------


def test_derive_command_export_arbitrage_scales_discharge():
    bs = make_battery_settings(max_discharge_power_kw=10.0)
    # planned discharge of 5 kW -> grid_first, discharge ~50%
    cmd = derive_control_command(
        "EXPORT_ARBITRAGE", battery_action_kw=-5.0, settings=bs
    )
    assert cmd.battery_mode == "grid_first"
    assert cmd.discharge_rate_pct == 50
    assert cmd.grid_charge is False


def test_derive_command_solar_storage_is_load_first_no_discharge():
    bs = make_battery_settings()
    cmd = derive_control_command("SOLAR_STORAGE", battery_action_kw=0.4, settings=bs)
    assert cmd.battery_mode == "load_first"
    assert cmd.discharge_rate_pct == 0
    assert cmd.grid_charge is False


def test_derive_command_grid_charging_enables_grid_charge():
    bs = make_battery_settings()
    cmd = derive_control_command("GRID_CHARGING", battery_action_kw=4.0, settings=bs)
    assert cmd.battery_mode == "battery_first"
    assert cmd.grid_charge is True
