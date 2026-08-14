"""Tests for Huawei service-call helpers on HomeAssistantAPIController."""

from unittest.mock import patch

import pytest

from core.bess.exceptions import SystemConfigurationError
from core.bess.ha_api_controller import HomeAssistantAPIController
from core.bess.settings_store import SettingsStore


def _settings_store(sensors: dict) -> SettingsStore:
    store = SettingsStore()
    store.data["sensors"] = dict(sensors)
    return store


@pytest.fixture
def controller() -> HomeAssistantAPIController:
    ctrl = HomeAssistantAPIController(
        ha_url="http://ha.local",
        token="tok",
        settings_store=_settings_store(
            {"huawei_working_mode": "select.huawei_working_mode"}
        ),
        huawei_device_id="dev-123",
        service_domain="huawei_solar",
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
        ctrl = HomeAssistantAPIController(ha_url="http://ha.local", token="tok")
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


class TestReadHuaweiTouPeriods:
    """The TOU period readback reads the huawei_solar sensor's attributes.

    HuaweiSolarTOUSensorEntity (wlcrs/huawei_solar sensor.py:2510) publishes
    the configured periods as {"Period 1": "<text>", ...} extra state
    attributes, in the same text format huawei_solar.set_tou_periods accepts.
    """

    @pytest.fixture
    def controller(self) -> HomeAssistantAPIController:
        ctrl = HomeAssistantAPIController(
            ha_url="http://ha.local",
            token="tok",
            settings_store=_settings_store(
                {
                    "huawei_tou_periods": (
                        "sensor.batteries_tou_charging_and_discharging_periods"
                    )
                }
            ),
            huawei_device_id="dev-123",
            service_domain="huawei_solar",
        )
        ctrl.test_mode = False
        return ctrl

    def test_returns_period_lines_in_period_number_order(
        self, controller: HomeAssistantAPIController
    ) -> None:
        with patch.object(controller, "_api_request") as mock_request:
            mock_request.return_value = {
                "state": "11",
                "attributes": {
                    "Period 10": "20:00-20:59/1234567/-",
                    "Period 2": "18:00-18:59/1234567/-",
                    "Period 1": "02:00-05:59/1234567/+",
                    "Period 11": "21:00-21:59/1234567/-",
                    "friendly_name": "Batteries TOU periods",
                    "icon": "mdi:calendar-text",
                },
            }
            assert controller.read_huawei_tou_periods() == [
                "02:00-05:59/1234567/+",
                "18:00-18:59/1234567/-",
                "20:00-20:59/1234567/-",
                "21:00-21:59/1234567/-",
            ]

    def test_no_periods_configured_reads_as_empty(
        self, controller: HomeAssistantAPIController
    ) -> None:
        with patch.object(controller, "_api_request") as mock_request:
            mock_request.return_value = {
                "state": "0",
                "attributes": {"friendly_name": "Batteries TOU periods"},
            }
            assert controller.read_huawei_tou_periods() == []

    def test_unreadable_entity_raises_rather_than_reporting_empty(
        self, controller: HomeAssistantAPIController
    ) -> None:
        """An empty inverter and an unreadable entity must not look alike.

        Same distinction #551/#552 drew for Growatt MIN: [] means "no periods
        programmed", and a failed read arrives as an exception. Reporting []
        for a failed read would let BESS conclude its schedule matches nothing
        and silently skip a needed write.
        """
        with patch.object(controller, "_api_request") as mock_request:
            mock_request.return_value = None
            with pytest.raises(SystemConfigurationError):
                controller.read_huawei_tou_periods()

    def test_unavailable_state_raises(
        self, controller: HomeAssistantAPIController
    ) -> None:
        with patch.object(controller, "_api_request") as mock_request:
            mock_request.return_value = {"state": "unavailable", "attributes": {}}
            with pytest.raises(SystemConfigurationError):
                controller.read_huawei_tou_periods()


class TestHuaweiSuffixMap:
    def test_tou_period_sensor_is_discoverable(self) -> None:
        """The LUNA2000 TOU register key, verified against
        huawei-solar-lib register_names.py:402."""
        assert (
            HomeAssistantAPIController.HUAWEI_SUFFIX_MAP[
                "storage_huawei_luna2000_time_of_use_charging_and_discharging_periods"
            ]
            == "huawei_tou_periods"
        )
