"""Unit tests for the inverter simulator: ControlCommand, derive_control_command,
mode_to_power, and simulate. All hand-computed; no optimizer invocation."""

from core.bess.simulation.inverter_simulator import (
    ControlCommand,
    derive_control_command,
    mode_to_power,
    simulate,
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


# ---------------------------------------------------------------------------
# Task 2: mode_to_power
# ---------------------------------------------------------------------------


def test_grid_first_discharges_to_grid_at_rate():
    bs = make_battery_settings(
        max_discharge_power_kw=10.0
    )  # 10kW * 0.25h = 2.5kWh/period
    cmd = ControlCommand("grid_first", discharge_rate_pct=50, grid_charge=False)
    # plenty of stored energy, 50% rate -> 5 kW discharge
    p = mode_to_power(cmd, solar=0.0, home=0.0, soe=15.0, settings=bs, dt=0.25)
    assert p == -5.0


def test_load_first_no_discharge_no_surplus_returns_zero():
    bs = make_battery_settings()
    cmd = ControlCommand("load_first", discharge_rate_pct=0, grid_charge=False)
    # No surplus (home >= solar): load_first holds battery, power = 0
    p = mode_to_power(cmd, solar=0.2, home=1.9, soe=3.0, settings=bs, dt=0.25)
    assert p == 0.0


def test_mode_to_power_load_first_stores_all_surplus():
    """Task 4c: load_first + no discharge + surplus -> return all-surplus charge power."""
    bs = make_battery_settings(max_charge_power_kw=10.0)
    cmd = ControlCommand("load_first", 0, False)
    assert (
        mode_to_power(cmd, solar=1.6, home=0.2, soe=5.0, settings=bs, dt=0.25)
        == (1.6 - 0.2) / 0.25
    )


def test_mode_to_power_grid_first_no_discharge_holds_and_exports():
    """Task 4c: grid_first + discharge_rate 0 -> returns 0.0 (export via energy balance)."""
    bs = make_battery_settings()
    cmd = ControlCommand("grid_first", 0, False)
    assert mode_to_power(cmd, solar=1.6, home=0.2, soe=5.0, settings=bs, dt=0.25) == 0.0


def test_load_support_discharges_to_cover_home_deficit():
    bs = make_battery_settings(max_discharge_power_kw=10.0)
    cmd = ControlCommand("load_first", discharge_rate_pct=100, grid_charge=False)
    # home 1.0 kWh, no solar -> need 1.0 kWh delivered over 0.25h = 4 kW, within rate & energy
    p = mode_to_power(cmd, solar=0.0, home=1.0, soe=15.0, settings=bs, dt=0.25)
    assert p == -4.0


def test_battery_first_charges_at_max_rate():
    bs = make_battery_settings(max_charge_power_kw=10.0)
    cmd = ControlCommand("battery_first", discharge_rate_pct=0, grid_charge=True)
    p = mode_to_power(cmd, solar=0.0, home=0.0, soe=5.0, settings=bs, dt=0.25)
    assert p == 10.0


# ---------------------------------------------------------------------------
# Task 3: simulate
# ---------------------------------------------------------------------------


def test_simulate_idle_day_costs_grid_import_only():
    bs = make_battery_settings()
    n = 4
    commands = [ControlCommand("load_first", 0, False)] * n  # idle/store
    solar = [0.0] * n
    home = [1.0] * n
    buy = [2.0] * n
    sell = [1.0] * n
    res = simulate(
        commands, solar, home, buy, sell, initial_soe=3.0, settings=bs, dt=0.25
    )
    # no solar, no battery action -> all home from grid: 4 * 1.0 kWh * 2.0 = 8.0
    assert res.realized_cost == 8.0
    assert len(res.period_data) == n
    assert res.period_data[0].energy.battery_soe_start == 3.0
