"""Tests for demo mode (test_mode) write blocking in _service_call_with_retry.

Verifies that the deny-by-default gate in _service_call_with_retry blocks
ALL write operations in test_mode, regardless of service domain. This is
the sole write-blocking mechanism — _api_request has no test_mode check.
"""

from unittest.mock import patch

import pytest

from core.bess.ha_api_controller import HomeAssistantAPIController


@pytest.fixture
def controller():
    ctrl = HomeAssistantAPIController(
        ha_url="http://localhost:8123",
        token="test-token",
    )
    ctrl.test_mode = True
    return ctrl


class TestDenyByDefaultBlocking:
    """_service_call_with_retry blocks all non-safe-read operations in test_mode."""

    @pytest.mark.parametrize(
        "domain,service",
        [
            # Growatt MIN (cloud) — TOU segment writes
            ("growatt_server", "update_time_segment"),
            # Growatt SPH (cloud) — AC charge/discharge schedule writes
            ("growatt_server", "write_ac_charge_times"),
            ("growatt_server", "write_ac_discharge_times"),
            # solax_modbus Growatt — TOU via entity writes
            ("select", "select_option"),
            ("button", "press"),
            # SolaX VPP — power control
            ("number", "set_value"),
            # All platforms — grid charge toggle
            ("switch", "turn_on"),
            ("switch", "turn_off"),
            # Deny-by-default: unknown services must also be blocked
            ("some_future_integration", "write_something"),
        ],
    )
    def test_blocks_write_operations(self, controller, domain, service):
        result = controller._service_call_with_retry(
            domain, service, entity_id="select.tou_1_mode", option="Battery First"
        )
        assert result is None

    @pytest.mark.parametrize(
        "domain,service",
        [
            ("growatt_server", "update_time_segment"),
            ("growatt_server", "write_ac_charge_times"),
            ("growatt_server", "write_ac_discharge_times"),
            ("select", "select_option"),
            ("button", "press"),
            ("number", "set_value"),
            ("switch", "turn_on"),
        ],
    )
    def test_no_http_call_made(self, controller, domain, service):
        with patch.object(controller, "_api_request") as mock_api:
            controller._service_call_with_retry(
                domain, service, entity_id="select.tou_1_mode"
            )
            mock_api.assert_not_called()


class TestSafeReadsAllowed:
    """Safe read operations pass through even in test_mode."""

    @pytest.mark.parametrize(
        "domain,service",
        [
            ("growatt_server", "read_time_segments"),
            ("growatt_server", "read_ac_charge_times"),
            ("growatt_server", "read_ac_discharge_times"),
            ("nordpool", "get_prices_for_date"),
        ],
    )
    def test_safe_reads_call_api(self, controller, domain, service):
        with patch.object(
            controller, "_api_request", return_value={"result": "ok"}
        ) as mock_api:
            result = controller._service_call_with_retry(
                domain, service, return_response=True
            )
            mock_api.assert_called_once()
            assert result == {"result": "ok"}


class TestNormalModePassthrough:
    """When test_mode is False, all operations reach _api_request."""

    def test_write_reaches_api_request(self):
        ctrl = HomeAssistantAPIController(
            ha_url="http://localhost:8123", token="test-token"
        )
        ctrl.test_mode = False
        with patch.object(ctrl, "_api_request", return_value=None) as mock_api:
            ctrl._service_call_with_retry(
                "select",
                "select_option",
                entity_id="select.tou_1_mode",
                option="Battery First",
            )
            mock_api.assert_called_once()
