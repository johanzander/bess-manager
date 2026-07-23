"""Tests for BatterySystemManager's inverter controller platform factory."""

import pytest

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.huawei_controller import HuaweiController
from core.bess.price_manager import MockSource


@pytest.fixture
def system(mock_controller):
    return BatterySystemManager(
        controller=mock_controller,
        price_source=MockSource([1.0] * 96),
        addon_options={"inverter": {"platform": "huawei_solar_luna2000"}},
    )


class TestCreateInverterController:
    def test_create_inverter_controller_huawei(self, system):
        controller = system._create_inverter_controller()
        assert isinstance(controller, HuaweiController)
