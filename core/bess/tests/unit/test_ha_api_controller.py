"""Tests for ha_api_controller HTTP request handling, retry logic, and sensor access.

Uses unittest.mock to patch the requests.Session methods on the controller,
exercising the real _api_request / _service_call_with_retry / _get_raw_state
code paths without needing a live Home Assistant instance.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from core.bess.ha_api_controller import HomeAssistantAPIController
from core.bess.runtime_failure_tracker import RuntimeFailureTracker


def _session_method_mock(name, return_value=None, side_effect=None):
    """Create a mock for a requests.Session method that has __name__."""
    m = MagicMock(return_value=return_value, side_effect=side_effect)
    m.__name__ = name
    return m


@pytest.fixture
def ctrl():
    """Controller with sensors configured for common operations."""
    c = HomeAssistantAPIController(
        ha_url="http://ha.local:8123",
        token="test-token",
        sensor_config={
            "battery_soc": "sensor.battery_soc",
            "battery_charge_stop_soc": "number.charge_stop_soc",
            "battery_discharge_stop_soc": "number.discharge_stop_soc",
            "battery_charging_power_rate": "number.charging_power_rate",
            "battery_discharging_power_rate": "number.discharging_power_rate",
            "battery_charge_power": "sensor.charge_power",
            "battery_discharge_power": "sensor.discharge_power",
            "grid_charge": "switch.grid_charge",
            "discharge_inhibit": "binary_sensor.discharge_inhibit",
        },
    )
    c.max_attempts = 1
    c.retry_base_delay = 0
    c.failure_tracker = RuntimeFailureTracker()
    return c


def _mock_response(json_data=None, status_code=200, content_type="application/json"):
    """Create a mock requests.Response with all attributes run_request accesses."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.content = b'{"ok": true}' if json_data else b""
    resp.headers = {"content-type": content_type}
    resp.text = str(json_data)
    resp.raise_for_status = MagicMock()
    return resp


def _mock_404():
    """Create a mock 404 response that triggers raise_for_status."""
    resp = _mock_response(status_code=404)
    http_error = requests.HTTPError(response=resp)
    resp.raise_for_status.side_effect = http_error
    return resp


# ── _api_request ─────────────────────────────────────────────────────────────


class TestApiRequest:
    def test_get_returns_json(self, ctrl):
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "50"})
        )
        result = ctrl._api_request("get", "/api/states/sensor.battery_soc")
        assert result == {"state": "50"}

    def test_post_returns_none_for_empty_body(self, ctrl):
        resp = _mock_response(None)
        resp.content = b""
        ctrl.session.post = _session_method_mock("post", return_value=resp)
        result = ctrl._api_request("post", "/api/services/switch/turn_on")
        assert result is None

    def test_404_raises_immediately(self, ctrl):
        ctrl.max_attempts = 3
        ctrl.session.get = _session_method_mock("get", return_value=_mock_404())
        with pytest.raises(requests.HTTPError):
            ctrl._api_request("get", "/api/states/sensor.missing")
        assert ctrl.session.get.call_count == 1

    def test_retries_on_connection_error(self, ctrl):
        ctrl.max_attempts = 3
        ctrl.retry_base_delay = 0
        error = requests.ConnectionError("refused")
        success_resp = _mock_response({"state": "ok"})
        ctrl.session.get = _session_method_mock(
            "get", side_effect=[error, error, success_resp]
        )
        with patch("core.bess.ha_api_controller.time.sleep"):
            result = ctrl._api_request("get", "/api/states/sensor.test")
        assert result == {"state": "ok"}
        assert ctrl.session.get.call_count == 3

    def test_records_failure_on_final_retry(self, ctrl):
        ctrl.max_attempts = 2
        ctrl.retry_base_delay = 0
        error = requests.ConnectionError("refused")
        ctrl.session.get = _session_method_mock("get", side_effect=error)
        with patch("core.bess.ha_api_controller.time.sleep"):
            with pytest.raises(requests.ConnectionError):
                ctrl._api_request(
                    "get",
                    "/api/states/sensor.test",
                    operation="Read SOC",
                    category="sensor_read",
                )
        failures = ctrl.failure_tracker.get_active_failures()
        assert len(failures) == 1
        assert "Read SOC" in failures[0].operation

    def test_test_mode_blocks_write_operations(self, ctrl):
        ctrl.test_mode = True
        ctrl.session.post = _session_method_mock("post")
        result = ctrl._api_request(
            "post", "/api/services/switch/turn_on", json={"entity_id": "switch.x"}
        )
        assert result is None
        ctrl.session.post.assert_not_called()

    def test_test_mode_allows_read_operations(self, ctrl):
        ctrl.test_mode = True
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "50"})
        )
        result = ctrl._api_request("get", "/api/states/sensor.battery_soc")
        assert result == {"state": "50"}


# ── _service_call_with_retry ─────────────────────────────────────────────────


class TestServiceCallWithRetry:
    def test_builds_correct_path(self, ctrl):
        with patch.object(ctrl, "_api_request", return_value=None) as mock:
            ctrl._service_call_with_retry("switch", "turn_on", entity_id="switch.x")
            args = mock.call_args
            assert "/api/services/switch/turn_on" in args[0][1]

    def test_safe_read_adds_return_response(self, ctrl):
        with patch.object(ctrl, "_api_request", return_value={"result": "ok"}) as mock:
            ctrl._service_call_with_retry(
                "growatt_server",
                "read_time_segments",
                return_response=True,
            )
            path = mock.call_args[0][1]
            assert "return_response=true" in path

    def test_test_mode_blocks_all_except_safe_reads(self, ctrl):
        ctrl.test_mode = True
        result = ctrl._service_call_with_retry(
            "select", "select_option", entity_id="select.tou_1", option="Grid First"
        )
        assert result is None

    def test_test_mode_allows_safe_reads(self, ctrl):
        ctrl.test_mode = True
        with patch.object(ctrl, "_api_request", return_value={"data": []}) as mock:
            result = ctrl._service_call_with_retry(
                "growatt_server",
                "read_time_segments",
                return_response=True,
            )
            mock.assert_called_once()
            assert result == {"data": []}


# ── _get_raw_state / _get_sensor_value / _get_binary_state ───────────────────


class TestSensorReading:
    def test_get_raw_state_returns_value(self, ctrl):
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "75.5"})
        )
        result = ctrl._get_raw_state("battery_soc")
        assert result == "75.5"

    def test_get_raw_state_unavailable_returns_none(self, ctrl):
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "unavailable"})
        )
        result = ctrl._get_raw_state("battery_soc")
        assert result is None

    def test_get_raw_state_unknown_returns_none(self, ctrl):
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "unknown"})
        )
        result = ctrl._get_raw_state("battery_soc")
        assert result is None

    def test_get_raw_state_unconfigured_returns_none(self, ctrl):
        result = ctrl._get_raw_state("nonexistent_sensor")
        assert result is None

    def test_get_raw_state_http_error_returns_none(self, ctrl):
        ctrl.session.get = _session_method_mock(
            "get", side_effect=requests.ConnectionError("fail")
        )
        result = ctrl._get_raw_state("battery_soc")
        assert result is None

    def test_get_sensor_value_converts_float(self, ctrl):
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "42.7"})
        )
        result = ctrl.get_battery_soc()
        assert result == 42.7

    def test_get_sensor_value_returns_none_for_non_numeric(self, ctrl):
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "not_a_number"})
        )
        result = ctrl.get_battery_soc()
        assert result is None

    def test_get_binary_state_on(self, ctrl):
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "on"})
        )
        assert ctrl.get_discharge_inhibit_active() is True

    def test_get_binary_state_off(self, ctrl):
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "off"})
        )
        assert ctrl.get_discharge_inhibit_active() is False

    def test_discharge_inhibit_unconfigured(self):
        c = HomeAssistantAPIController(ha_url="http://ha.local:8123", token="t")
        assert c.get_discharge_inhibit_active() is False


# ── set_* / grid_charge ─────────────────────────────────────────────────────


class TestSetOperations:
    def test_set_grid_charge_switch_on(self, ctrl):
        with patch.object(ctrl, "_service_call_with_retry") as mock:
            ctrl.set_grid_charge(True)
            mock.assert_called_once()
            assert mock.call_args[0] == ("switch", "turn_on")

    def test_set_grid_charge_switch_off(self, ctrl):
        with patch.object(ctrl, "_service_call_with_retry") as mock:
            ctrl.set_grid_charge(False)
            assert mock.call_args[0] == ("switch", "turn_off")

    def test_set_grid_charge_select_entity(self, ctrl):
        ctrl.sensors["grid_charge"] = "select.grid_charge_mode"
        with patch.object(ctrl, "_service_call_with_retry") as mock:
            ctrl.set_grid_charge(True)
            assert mock.call_args[0] == ("select", "select_option")
            assert mock.call_args[1]["option"] == "Enabled"

    def test_set_discharging_power_rate(self, ctrl):
        with patch.object(ctrl, "_service_call_with_retry") as mock:
            ctrl.set_discharging_power_rate(75)
            mock.assert_called_once()
            assert mock.call_args[1]["value"] == 75

    def test_set_charge_stop_soc(self, ctrl):
        with patch.object(ctrl, "_service_call_with_retry") as mock:
            ctrl.set_charge_stop_soc(90)
            assert mock.call_args[1]["value"] == 90


class TestGridChargeEnabled:
    def test_switch_on(self, ctrl):
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "on"})
        )
        assert ctrl.grid_charge_enabled() is True

    def test_switch_off(self, ctrl):
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "off"})
        )
        assert ctrl.grid_charge_enabled() is False

    def test_select_entity_enabled(self, ctrl):
        ctrl.sensors["grid_charge"] = "select.grid_charge_mode"
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "Enabled"})
        )
        assert ctrl.grid_charge_enabled() is True

    def test_unconfigured_returns_false(self):
        c = HomeAssistantAPIController(ha_url="http://ha.local:8123", token="t")
        assert c.grid_charge_enabled() is False


# ── Entity resolution ────────────────────────────────────────────────────────


class TestEntityResolution:
    def test_configured_sensor_resolves(self, ctrl):
        entity_id, method = ctrl._resolve_entity_id("battery_soc")
        assert entity_id == "sensor.battery_soc"
        assert method == "configured"

    def test_unconfigured_raises(self, ctrl):
        with pytest.raises(ValueError):
            ctrl._resolve_entity_id("nonexistent")

    def test_empty_entity_raises(self):
        c = HomeAssistantAPIController(
            ha_url="http://ha.local:8123",
            token="t",
            sensor_config={"bad_sensor": ""},
        )
        with pytest.raises(ValueError, match="Empty entity ID"):
            c._resolve_entity_id("bad_sensor")


class TestGetMethodSensorInfo:
    def test_known_method(self, ctrl):
        info = ctrl.get_method_sensor_info("get_battery_soc")
        assert info["sensor_key"] == "battery_soc"
        assert info["entity_id"] == "sensor.battery_soc"

    def test_unknown_method(self, ctrl):
        info = ctrl.get_method_sensor_info("nonexistent_method")
        assert info["status"] == "unknown_method"

    def test_unconfigured_sensor(self):
        c = HomeAssistantAPIController(ha_url="http://ha.local:8123", token="t")
        info = c.get_method_sensor_info("get_battery_soc")
        assert info["status"] == "not_configured"


class TestGetEntityStateRaw:
    def test_returns_full_state(self, ctrl):
        ctrl.session.get = _session_method_mock(
            "get",
            return_value=_mock_response({"state": "50", "attributes": {"unit": "%"}}),
        )
        result = ctrl.get_entity_state_raw("sensor.battery_soc")
        assert result["state"] == "50"


# ── run_request helper ───────────────────────────────────────────────────────


class TestRunRequest:
    def test_returns_response(self):
        from core.bess.ha_api_controller import run_request

        mock_method = _session_method_mock(
            "get", return_value=_mock_response({"ok": True})
        )
        result = run_request(mock_method, "http://test")
        assert result.status_code == 200

    def test_propagates_exception(self):
        from core.bess.ha_api_controller import run_request

        mock_method = _session_method_mock(
            "get", side_effect=requests.ConnectionError("fail")
        )
        with pytest.raises(requests.ConnectionError):
            run_request(mock_method, "http://test")
