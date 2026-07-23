"""Tests for Huawei service-call helpers on HomeAssistantAPIController."""

from unittest.mock import MagicMock, patch

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
