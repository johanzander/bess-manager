"""_mode_display_fields() is the single source of truth for what mode-
related fields a period gets, branching on CONTROL_MODEL. No batt_mode
fiction, no static stubs -- see design spec section 1."""

import pytest

from core.bess.growatt_min_controller import GrowattMinController
from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.settings import BatterySettings
from core.bess.solax_controller import SolaxController
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController


@pytest.fixture
def battery_settings() -> BatterySettings:
    return BatterySettings(
        total_capacity=50.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        min_soc=10.0,
        max_soc=95.0,
        cycle_cost_per_kwh=0.05,
    )


def test_tou_register_returns_batt_mode_only(battery_settings):
    controller = GrowattMinController(battery_settings=battery_settings)
    fields = controller._mode_display_fields(
        intent="SOLAR_EXPORT",
        grid_charge=False,
        discharge_rate=0,
        block_passive_charging=True,
    )
    assert fields == {"batt_mode": "load_first"}


def test_vpp_power_growatt_returns_vpp_fields_not_batt_mode(battery_settings):
    controller = SolaxModbusGrowattController(
        battery_settings=battery_settings, control_mode="vpp"
    )
    fields = controller._mode_display_fields(
        intent="SOLAR_EXPORT",
        grid_charge=False,
        discharge_rate=0,
        block_passive_charging=True,
    )
    assert "batt_mode" not in fields
    assert fields["vpp_power_pct"] == 0
    assert fields["vpp_remote_control"] is True  # grid-first hold, #355


def test_vpp_power_solax_returns_vpp_fields_reflecting_its_own_behavior(
    battery_settings,
):
    controller = SolaxController(battery_settings=battery_settings)
    fields = controller._mode_display_fields(
        intent="SOLAR_EXPORT",
        grid_charge=False,
        discharge_rate=0,
        block_passive_charging=True,  # SolaX ignores this -- see TODO.md gap
    )
    assert "batt_mode" not in fields
    assert fields["vpp_power_pct"] == 0
    assert fields["vpp_remote_control"] is False  # self-use passthrough, NOT a hold


def test_period_list_returns_no_mode_fields(battery_settings):
    controller = GrowattSphController(battery_settings=battery_settings)
    fields = controller._mode_display_fields(
        intent="GRID_CHARGING",
        grid_charge=True,
        discharge_rate=0,
        block_passive_charging=False,
    )
    assert fields == {}
