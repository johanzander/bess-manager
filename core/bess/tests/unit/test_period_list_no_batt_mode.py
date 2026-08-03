"""period_list controllers must never fabricate a batt_mode label --
their real hardware model has no per-period mode concept at all.

Also covers the two vpp_power controllers (SolaxController,
SolaxModbusGrowattController in "vpp" mode) whose empty-groups default
stub previously leaked the same "load_first" fabrication -- vpp_power
has no batt_mode concept either, only vpp_power_pct/vpp_remote_control."""

import pytest

from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.huawei_controller import HuaweiController
from core.bess.settings import BatterySettings
from core.bess.solax_controller import SolaxController
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController
from core.bess.solis_modbus_controller import SolisModbusController


@pytest.fixture
def battery_settings() -> BatterySettings:
    return BatterySettings(
        total_capacity=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        min_soc=15.0,
        max_soc=95.0,
    )


@pytest.mark.parametrize(
    "controller_cls", [GrowattSphController, SolisModbusController, HuaweiController]
)
def test_default_stub_has_no_batt_mode(controller_cls, battery_settings):
    controller = controller_cls(battery_settings=battery_settings)
    segments = controller.get_all_tou_segments()
    assert len(segments) == 1
    assert "batt_mode" not in segments[0]


@pytest.mark.parametrize(
    "controller_cls", [GrowattSphController, SolisModbusController]
)
def test_built_period_list_has_no_batt_mode(controller_cls, battery_settings):
    controller = controller_cls(battery_settings=battery_settings)
    controller.strategic_intents = ["GRID_CHARGING"] * 4 + ["LOAD_SUPPORT"] * 4
    controller._build_period_list_schedule()
    segments = controller.get_all_tou_segments()
    assert segments
    assert all("batt_mode" not in s for s in segments)


def test_huawei_built_period_list_has_no_batt_mode(battery_settings):
    controller = HuaweiController(battery_settings=battery_settings)
    controller.strategic_intents = ["GRID_CHARGING"] * 4 + ["LOAD_SUPPORT"] * 4
    controller._build_huawei_periods()
    segments = controller.get_all_tou_segments()
    assert segments
    assert all("batt_mode" not in s for s in segments)


def test_solax_default_stub_has_no_batt_mode(battery_settings):
    controller = SolaxController(battery_settings=battery_settings)
    segments = controller.get_all_tou_segments()
    assert len(segments) == 1
    assert "batt_mode" not in segments[0]


def test_solax_modbus_growatt_vpp_default_stub_has_no_batt_mode(battery_settings):
    controller = SolaxModbusGrowattController(
        battery_settings=battery_settings, control_mode="vpp"
    )
    assert controller.CONTROL_MODEL == "vpp_power"
    segments = controller.get_all_tou_segments()
    assert len(segments) == 1
    assert "batt_mode" not in segments[0]
