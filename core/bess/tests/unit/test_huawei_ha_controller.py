"""Tests for Huawei service-call helpers on HomeAssistantAPIController."""

from unittest.mock import patch

import pytest

from core.bess.exceptions import SystemConfigurationError
from core.bess.ha_api_controller import HomeAssistantAPIController


@pytest.fixture
def controller() -> HomeAssistantAPIController:
    ctrl = HomeAssistantAPIController(
        ha_url="http://ha.local",
        token="tok",
        sensor_config={"huawei_working_mode": "select.huawei_working_mode"},
        huawei_device_id="dev-123",
    )
    ctrl.test_mode = False
    return ctrl


class TestHuaweiServiceCalls:
    def test_set_huawei_working_mode_calls_select_select_option(
        self, controller: HomeAssistantAPIController
    ) -> None:
        with patch.object(controller, "_api_request") as mock_request:
            mock_request.return_value = {}
            controller.set_huawei_working_mode("time_of_use_luna2000")
            args, kwargs = mock_request.call_args
            assert args[0] == "post"
            assert args[1] == "/api/services/select/select_option"
            assert kwargs["json"]["entity_id"] == "select.huawei_working_mode"
            assert kwargs["json"]["option"] == "time_of_use_luna2000"

    def test_write_huawei_tou_periods_includes_device_id(
        self, controller: HomeAssistantAPIController
    ) -> None:
        with patch.object(controller, "_api_request") as mock_request:
            mock_request.return_value = {}
            controller.write_huawei_tou_periods("06:00-08:00/1234567/+")
            args, kwargs = mock_request.call_args
            assert args[1] == "/api/services/huawei_solar/set_tou_periods"
            assert kwargs["json"]["device_id"] == "dev-123"
            assert kwargs["json"]["periods"] == "06:00-08:00/1234567/+"

    def test_write_huawei_tou_periods_raises_without_device_id(self) -> None:
        ctrl = HomeAssistantAPIController(
            ha_url="http://ha.local", token="tok", sensor_config={}
        )
        with pytest.raises(SystemConfigurationError):
            ctrl.write_huawei_tou_periods("06:00-08:00/1234567/+")

    def test_get_huawei_working_mode_options_returns_attribute_list(
        self, controller: HomeAssistantAPIController
    ) -> None:
        with patch.object(controller, "_api_request") as mock_request:
            mock_request.return_value = {
                "state": "maximise_self_consumption",
                "attributes": {
                    "options": [
                        "adaptive",
                        "fixed_charge_discharge",
                        "maximise_self_consumption",
                        "time_of_use_luna2000",
                        "fully_fed_to_grid",
                    ]
                },
            }
            options = controller.get_huawei_working_mode_options()
            assert "time_of_use_luna2000" in options
            assert "time_of_use_lg" not in options

    def test_get_huawei_working_mode_options_empty_when_no_response(
        self, controller: HomeAssistantAPIController
    ) -> None:
        with patch.object(controller, "_api_request") as mock_request:
            mock_request.return_value = None
            assert controller.get_huawei_working_mode_options() == []


class TestHuaweiEmmaServiceCalls:
    def test_set_tou_periods_uses_native_huawei_emma_service(self) -> None:
        ctrl = HomeAssistantAPIController(
            ha_url="http://ha.local",
            token="tok",
            sensor_config={},
            huawei_emma_config_entry_id="emma-entry",
        )
        periods = [
            {
                "start_time": "00:00",
                "end_time": "06:00",
                "action": "charge",
                "days": [True] * 7,
            }
        ]
        with patch.object(ctrl, "_api_request", return_value={}) as request:
            ctrl.write_huawei_emma_tou_periods(periods)

        args, kwargs = request.call_args
        assert args[1] == ("/api/services/huawei_emma_management/set_tou_periods")
        assert kwargs["json"]["config_entry_id"] == "emma-entry"
        assert kwargs["json"]["periods"] == periods

    def test_reads_structured_periods_from_active_schedule_sensor(self) -> None:
        ctrl = HomeAssistantAPIController(
            ha_url="http://ha.local",
            token="tok",
            sensor_config={
                "huawei_emma_tou_schedule": (
                    "sensor.huawei_emma_a02_tou_1_active_schedule"
                )
            },
        )
        response = {
            "state": "2 periods",
            "attributes": {
                "periods": [
                    {
                        "start_time": 0,
                        "end_time": 360,
                        "action": 0,
                        "days": [True] * 7,
                    },
                    {
                        "start_time": 360,
                        "end_time": 1439,
                        "action": "discharge",
                        "days": [True] * 7,
                    },
                ]
            },
        }
        with patch.object(ctrl, "_api_request", return_value=response):
            assert ctrl.read_huawei_emma_tou_periods() == [
                {
                    "start_time": "00:00",
                    "end_time": "06:00",
                    "action": "charge",
                    "days": [True] * 7,
                },
                {
                    "start_time": "06:00",
                    "end_time": "23:59",
                    "action": "discharge",
                    "days": [True] * 7,
                },
            ]

    def test_signed_emma_power_entities_are_split_by_direction(self) -> None:
        shared_battery = "sensor.huawei_emma_battery_charge_discharge_power"
        shared_grid = "sensor.huawei_emma_feed_in_power"
        ctrl = HomeAssistantAPIController(
            ha_url="http://ha.local",
            token="tok",
            sensor_config={
                "battery_charge_power": shared_battery,
                "battery_discharge_power": shared_battery,
                "import_power": shared_grid,
                "export_power": shared_grid,
            },
        )
        states = {
            shared_battery: "-2400",
            shared_grid: "1300",
        }
        with patch.object(
            ctrl,
            "_get_raw_state",
            side_effect=lambda key: states[ctrl.sensors[key]],
        ):
            assert ctrl.get_battery_charge_power() == 0
            assert ctrl.get_battery_discharge_power() == 2400
            assert ctrl.get_import_power() == 1300
            assert ctrl.get_export_power() == 0
