"""CONTROL_MODEL must correctly classify every controller's real hardware model."""

from core.bess.growatt_min_controller import GrowattMinController
from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.huawei_controller import HuaweiController
from core.bess.solax_controller import SolaxController
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController
from core.bess.solis_modbus_controller import SolisModbusController
from core.bess.tests.helpers import make_battery_settings


def _make(cls, **kwargs):
    battery_settings = make_battery_settings()
    return cls(battery_settings=battery_settings, **kwargs)


def test_growatt_min_is_tou_register():
    controller = _make(GrowattMinController)
    assert controller.CONTROL_MODEL == "tou_register"


def test_solax_modbus_growatt_tou_mode_is_tou_register():
    controller = _make(SolaxModbusGrowattController, control_mode="tou")
    assert controller.CONTROL_MODEL == "tou_register"


def test_solax_modbus_growatt_vpp_mode_is_vpp_power():
    controller = _make(SolaxModbusGrowattController, control_mode="vpp")
    assert controller.CONTROL_MODEL == "vpp_power"


def test_solax_controller_is_vpp_power():
    controller = _make(SolaxController)
    assert controller.CONTROL_MODEL == "vpp_power"


def test_growatt_sph_is_period_list():
    controller = _make(GrowattSphController)
    assert controller.CONTROL_MODEL == "period_list"


def test_solis_modbus_is_period_list():
    controller = _make(SolisModbusController)
    assert controller.CONTROL_MODEL == "period_list"


def test_huawei_is_period_list():
    controller = _make(HuaweiController)
    assert controller.CONTROL_MODEL == "period_list"
