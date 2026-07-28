"""Behavior tests for Huawei EMMA/SUN2000 control."""

from unittest.mock import MagicMock

from core.bess.huawei_emma_controller import HuaweiEmmaController
from core.bess.settings import BatterySettings


def _controller() -> HuaweiEmmaController:
    return HuaweiEmmaController(
        BatterySettings(
            min_soc=12,
            max_soc=96,
            max_charge_power_kw=8.5,
            max_discharge_power_kw=7.25,
        )
    )


def test_writes_native_huawei_emma_tou_periods() -> None:
    controller = _controller()
    ha = MagicMock()
    controller._periods = [
        {"start_time": "01:00", "end_time": "02:00", "flag": "+"},
        {"start_time": "18:00", "end_time": "20:00", "flag": "-"},
    ]

    assert controller.write_to_hardware(ha, 0, []) == (2, 0)

    ha.write_huawei_emma_tou_periods.assert_called_once_with(
        [
            {
                "start_time": "01:00",
                "end_time": "02:00",
                "action": "charge",
                "days": [True] * 7,
            },
            {
                "start_time": "18:00",
                "end_time": "20:00",
                "action": "discharge",
                "days": [True] * 7,
            },
        ]
    )
    ha.set_grid_charge.assert_called_once_with(True)


def test_initialization_writes_soc_and_absolute_power_limits() -> None:
    controller = _controller()
    ha = MagicMock()
    ha.get_charge_stop_soc.return_value = 90
    ha.get_discharge_stop_soc.return_value = 10

    controller.initialize_hardware(ha)

    ha.set_charge_stop_soc.assert_called_once_with(96)
    ha.set_discharge_stop_soc.assert_called_once_with(12)
    ha.set_huawei_maximum_charging_power.assert_called_once_with(8500)
    ha.set_huawei_maximum_discharging_power.assert_called_once_with(7250)


def test_period_control_is_a_noop_for_native_period_list() -> None:
    controller = _controller()
    ha = MagicMock()

    assert controller.apply_period(ha, grid_charge=True, discharge_rate=73) == (
        True,
        "",
    )

    ha.set_grid_charge.assert_not_called()
    ha.set_discharging_power_rate.assert_not_called()
    ha.set_huawei_maximum_discharging_power.assert_not_called()
