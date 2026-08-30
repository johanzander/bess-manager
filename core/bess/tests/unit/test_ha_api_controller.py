"""Tests for ha_api_controller HTTP request handling, retry logic, and sensor access.

Uses unittest.mock to patch the requests.Session methods on the controller,
exercising the real _api_request / _service_call_with_retry / _get_raw_state
code paths without needing a live Home Assistant instance.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from core.bess.exceptions import SystemConfigurationError
from core.bess.ha_api_controller import (
    HomeAssistantAPIController,
    solcast_detailed_hourly_to_quarterly,
)
from core.bess.runtime_failure_tracker import RuntimeFailureTracker
from core.bess.settings_store import SettingsStore


def _session_method_mock(name, return_value=None, side_effect=None):
    """Create a mock for a requests.Session method that has __name__."""
    m = MagicMock(return_value=return_value, side_effect=side_effect)
    m.__name__ = name
    return m


def _settings_store(sensors: dict | None = None) -> SettingsStore:
    """A bare SettingsStore carrying just a flat sensor map, for constructing
    a HomeAssistantAPIController directly without a full settings section."""
    store = SettingsStore()
    store.data["sensors"] = dict(sensors or {})
    return store


@pytest.fixture
def ctrl():
    """Controller with sensors configured for common operations."""
    c = HomeAssistantAPIController(
        ha_url="http://ha.local:8123",
        token="test-token",
        settings_store=_settings_store(
            {
                "battery_soc": "sensor.battery_soc",
                "battery_charge_stop_soc": "number.charge_stop_soc",
                "battery_discharge_stop_soc": "number.discharge_stop_soc",
                "battery_charging_power_rate": "number.charging_power_rate",
                "battery_discharging_power_rate": "number.discharging_power_rate",
                "battery_charge_power": "sensor.charge_power",
                "battery_discharge_power": "sensor.discharge_power",
                "grid_charge": "switch.grid_charge",
                "discharge_inhibit": "binary_sensor.discharge_inhibit",
            }
        ),
        service_domain="growatt_server",
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

    def test_suppressed_failure_is_not_recorded(self, ctrl):
        """Issue #583: suppress_retry_warnings marks a failure as expected (the
        Nordpool tomorrow-price call before the market publishes). A failure not
        worth a log line is not worth a user-visible runtime-failure entry."""
        ctrl.max_attempts = 2
        ctrl.retry_base_delay = 0
        error = requests.ConnectionError("refused")
        ctrl.session.get = _session_method_mock("get", side_effect=error)
        with patch("core.bess.ha_api_controller.time.sleep"):
            with pytest.raises(requests.ConnectionError):
                ctrl._api_request(
                    "get",
                    "/api/states/sensor.test",
                    operation="Call nordpool.get_prices_for_date",
                    category="other",
                    suppress_retry_warnings=True,
                )
        assert ctrl.failure_tracker.get_active_failures() == []

    def test_test_mode_does_not_block_at_api_request_level(self, ctrl):
        ctrl.test_mode = True
        ctrl.session.post = _session_method_mock(
            "post", return_value=_mock_response(None)
        )
        ctrl._api_request(
            "post", "/api/services/switch/turn_on", json={"entity_id": "switch.x"}
        )
        ctrl.session.post.assert_called_once()

    def test_test_mode_allows_read_operations(self, ctrl):
        ctrl.test_mode = True
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "50"})
        )
        result = ctrl._api_request("get", "/api/states/sensor.battery_soc")
        assert result == {"state": "50"}

    def test_404_logs_error_by_default(self, ctrl, caplog):
        ctrl.session.get = _session_method_mock("get", return_value=_mock_404())
        with caplog.at_level(logging.DEBUG, logger="core.bess.ha_api_controller"):
            with pytest.raises(requests.HTTPError):
                ctrl._api_request("get", "/api/states/sensor.missing")
        assert any(r.levelno == logging.ERROR for r in caplog.records)

    def test_404_logs_debug_when_optional(self, ctrl, caplog):
        ctrl.session.get = _session_method_mock("get", return_value=_mock_404())
        with caplog.at_level(logging.DEBUG, logger="core.bess.ha_api_controller"):
            with pytest.raises(requests.HTTPError):
                ctrl._api_request("get", "/api/states/sensor.missing", optional=True)
        assert not any(r.levelno == logging.ERROR for r in caplog.records)
        assert any(r.levelno == logging.DEBUG for r in caplog.records)


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

    def test_input_number_domain_categorized_as_battery_control(self, ctrl):
        """Regression test for #372: input_number writes must be classified
        the same as number writes, or a failed write to a user-configured
        input_number.* entity silently degrades to the generic 'other'
        category in the runtime failure alert UI."""
        with patch.object(ctrl, "_api_request", return_value=None) as mock:
            ctrl._service_call_with_retry(
                "input_number", "set_value", entity_id="input_number.x", value=1
            )
            assert mock.call_args.kwargs["category"] == "battery_control"


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


# ── Signed grid power split (issue #475) ──────────────────────────────────────
#
# Platforms like Solis expose grid power as a single signed sensor rather than
# separate import/export entities. When import_power and export_power are
# both configured to the same entity_id and grid_power_polarity is set, the
# single raw reading must be split by sign into the two internal keys instead
# of being returned unmodified from two independent reads.


@pytest.fixture
def signed_grid_ctrl():
    """Controller with import_power and export_power sharing one signed entity."""
    c = HomeAssistantAPIController(
        ha_url="http://ha.local:8123",
        token="test-token",
        settings_store=_settings_store(
            {
                "import_power": "sensor.solis_grid_power_net",
                "export_power": "sensor.solis_grid_power_net",
            }
        ),
        grid_power_polarity="import_positive",
    )
    c.max_attempts = 1
    c.retry_base_delay = 0
    return c


class TestSignedGridPowerSplit:
    def test_positive_raw_is_import_only(self, signed_grid_ctrl):
        signed_grid_ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "1500"})
        )
        assert signed_grid_ctrl.get_import_power() == 1500.0
        assert signed_grid_ctrl.get_export_power() == 0.0

    def test_negative_raw_is_export_only(self, signed_grid_ctrl):
        signed_grid_ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "-1500"})
        )
        assert signed_grid_ctrl.get_import_power() == 0.0
        assert signed_grid_ctrl.get_export_power() == 1500.0

    def test_unavailable_raw_returns_none(self, signed_grid_ctrl):
        signed_grid_ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "unavailable"})
        )
        assert signed_grid_ctrl.get_import_power() is None
        assert signed_grid_ctrl.get_export_power() is None

    def test_export_positive_polarity_splits_positive_raw_to_export(self):
        """Huawei's power_meter_active_power (#438): positive = export."""
        c = HomeAssistantAPIController(
            ha_url="http://ha.local:8123",
            token="test-token",
            settings_store=_settings_store(
                {
                    "import_power": "sensor.huawei_power_meter_active_power",
                    "export_power": "sensor.huawei_power_meter_active_power",
                }
            ),
            grid_power_polarity="export_positive",
        )
        c.max_attempts = 1
        c.retry_base_delay = 0
        c.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "1500"})
        )
        assert c.get_export_power() == 1500.0
        assert c.get_import_power() == 0.0

    def test_export_positive_polarity_splits_negative_raw_to_import(self):
        c = HomeAssistantAPIController(
            ha_url="http://ha.local:8123",
            token="test-token",
            settings_store=_settings_store(
                {
                    "import_power": "sensor.huawei_power_meter_active_power",
                    "export_power": "sensor.huawei_power_meter_active_power",
                }
            ),
            grid_power_polarity="export_positive",
        )
        c.max_attempts = 1
        c.retry_base_delay = 0
        c.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "-1500"})
        )
        assert c.get_import_power() == 1500.0
        assert c.get_export_power() == 0.0

    def test_separate_entities_unaffected_by_polarity(self, ctrl):
        """A platform with two distinct entities must read them independently,
        even if grid_power_polarity somehow ended up set (defense against a
        future platform reusing the field incorrectly)."""
        ctrl.sensors = {
            **ctrl.sensors,
            "import_power": "sensor.import",
            "export_power": "sensor.export",
        }
        ctrl.grid_power_polarity = "import_positive"
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "42"})
        )
        assert ctrl.get_import_power() == 42.0
        assert ctrl.get_export_power() == 42.0


# ── Signed battery power split (issue #542) ───────────────────────────────────
#
# Native SolaX (solax_modbus) and Huawei LUNA2000 (huawei_solar) expose battery
# power as ONE signed register, positive = charging:
#   SolaX:  battery_power_charge            — REGISTER_S16, reg 0x16
#   Huawei: storage_charge_discharge_power  — I32Register, reg 37765
# Neither integration has a discharge counterpart, so battery_charge_power and
# battery_discharge_power both resolve to that single entity and the raw
# reading must be split by sign — same mechanism as the grid split above.


@pytest.fixture
def signed_battery_ctrl():
    """Controller with battery charge/discharge sharing one signed entity."""
    c = HomeAssistantAPIController(
        ha_url="http://ha.local:8123",
        token="test-token",
        settings_store=_settings_store(
            {
                "battery_charge_power": "sensor.solax_battery_power_charge",
                "battery_discharge_power": "sensor.solax_battery_power_charge",
            }
        ),
        battery_power_polarity="charge_positive",
    )
    c.max_attempts = 1
    c.retry_base_delay = 0
    return c


class TestSignedBatteryPowerSplit:
    def test_positive_raw_is_charge_only(self, signed_battery_ctrl):
        signed_battery_ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "2400"})
        )
        assert signed_battery_ctrl.get_battery_charge_power() == 2400.0
        assert signed_battery_ctrl.get_battery_discharge_power() == 0.0

    def test_negative_raw_is_discharge_only(self, signed_battery_ctrl):
        signed_battery_ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "-2400"})
        )
        assert signed_battery_ctrl.get_battery_charge_power() == 0.0
        assert signed_battery_ctrl.get_battery_discharge_power() == 2400.0

    def test_idle_raw_is_neither(self, signed_battery_ctrl):
        signed_battery_ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "0"})
        )
        assert signed_battery_ctrl.get_battery_charge_power() == 0.0
        assert signed_battery_ctrl.get_battery_discharge_power() == 0.0

    def test_unavailable_raw_returns_none(self, signed_battery_ctrl):
        signed_battery_ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "unavailable"})
        )
        assert signed_battery_ctrl.get_battery_charge_power() is None
        assert signed_battery_ctrl.get_battery_discharge_power() is None

    def test_net_battery_power_follows_the_split(self, signed_battery_ctrl):
        """get_net_battery_power derives from the two getters, so a discharging
        signed sensor must yield a negative net — not charge-minus-charge = 0."""
        signed_battery_ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "-2400"})
        )
        assert signed_battery_ctrl.get_net_battery_power() == -2400.0

    def test_separate_entities_unaffected_by_polarity(self, ctrl):
        """Platforms with two real entities (Growatt, Solis) must keep reading
        them independently even if battery_power_polarity is somehow set."""
        ctrl.sensors = {
            **ctrl.sensors,
            "battery_charge_power": "sensor.charge",
            "battery_discharge_power": "sensor.discharge",
        }
        ctrl.battery_power_polarity = "charge_positive"
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "42"})
        )
        assert ctrl.get_battery_charge_power() == 42.0
        assert ctrl.get_battery_discharge_power() == 42.0


class TestSignedPowerOnSettingsPersistedWithoutThePair:
    """Issue #604: a Huawei install whose settings predate the pairing.

    The reporter's persisted config mapped ONLY battery_charge_power to
    sensor.batteries_charge_discharge_power — the counterpart key was written
    by discovery, which had not run since the pairing was added. The signed
    split is gated on the pair, so it stayed off: a 375 W discharge was
    reported as -375 W of *charging* and discharge power came back None, with
    no error anywhere. Built on a real SettingsStore in the persisted
    per-platform shape, because that is where the pairing has to survive.
    """

    def _ctrl(self, sensors: dict) -> HomeAssistantAPIController:
        store = SettingsStore()
        store.data["inverter"] = {"platform": "huawei_solar_luna2000"}
        store.data["sensors"] = {
            "platform": "huawei_solar_luna2000",
            "huawei_solar_luna2000": sensors,
        }
        c = HomeAssistantAPIController(
            ha_url="http://ha.local:8123",
            token="test-token",
            settings_store=store,
            battery_power_polarity=store.get_battery_power_polarity(),
            grid_power_polarity=store.get_grid_power_polarity(),
        )
        c.max_attempts = 1
        c.retry_base_delay = 0
        return c

    def test_discharging_reads_as_discharge_not_negative_charge(self):
        ctrl = self._ctrl(
            {"battery_charge_power": "sensor.batteries_charge_discharge_power"}
        )
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "-375"})
        )
        assert ctrl.get_battery_charge_power() == 0.0
        assert ctrl.get_battery_discharge_power() == 375.0
        assert ctrl.get_net_battery_power() == -375.0

    def test_charging_still_reads_as_charge(self):
        ctrl = self._ctrl(
            {"battery_charge_power": "sensor.batteries_charge_discharge_power"}
        )
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "1693"})
        )
        assert ctrl.get_battery_charge_power() == 1693.0
        assert ctrl.get_battery_discharge_power() == 0.0

    def test_exporting_reads_as_export_not_negative_import(self):
        """Same staleness one layer up: the grid pair on the power meter."""
        ctrl = self._ctrl({"import_power": "sensor.power_meter_active_power"})
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "2000"})
        )
        # huawei_solar_luna2000 is export_positive (#438)
        assert ctrl.get_export_power() == 2000.0
        assert ctrl.get_import_power() == 0.0


class TestUnknownBatteryPolarityRaises:
    """An unrecognised polarity must fail loudly, not silently invert.

    ``charge_positive`` is the only value ``PLATFORM_BATTERY_POWER_POLARITY``
    can hold today, so this branch is unreachable from any shipped platform —
    it exists so that a future typo'd or unimplemented entry surfaces as an
    error instead of reporting every charge as a discharge and vice versa.
    """

    def _ctrl(self, polarity: str):
        c = HomeAssistantAPIController(
            ha_url="http://ha.local:8123",
            token="test-token",
            settings_store=_settings_store(
                {
                    "battery_charge_power": "sensor.signed_battery_power",
                    "battery_discharge_power": "sensor.signed_battery_power",
                }
            ),
            battery_power_polarity=polarity,
        )
        c.max_attempts = 1
        c.retry_base_delay = 0
        c.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "-2400"})
        )
        return c

    def test_charge_getter_raises_on_unknown_polarity(self):
        ctrl = self._ctrl("discharge_positive")
        with pytest.raises(ValueError, match="discharge_positive"):
            ctrl.get_battery_charge_power()

    def test_discharge_getter_raises_on_unknown_polarity(self):
        ctrl = self._ctrl("discharge_positive")
        with pytest.raises(ValueError, match="discharge_positive"):
            ctrl.get_battery_discharge_power()


class TestSignedSplitInSensorDiagnostics:
    """``get_method_sensor_info`` must report what the getters return.

    It reads ``/api/states/{entity_id}`` directly, so on a platform whose
    charge and discharge (or import and export) keys resolve to one signed
    entity it would otherwise report the same raw signed value on both rows —
    e.g. -800 for both "Battery Charging Power" and "Battery Discharging
    Power" on a native SolaX discharging at 800 W.
    """

    def test_battery_rows_report_the_split_not_the_raw_value(self, signed_battery_ctrl):
        signed_battery_ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "-800"})
        )
        charge = signed_battery_ctrl.get_method_sensor_info("get_battery_charge_power")
        discharge = signed_battery_ctrl.get_method_sensor_info(
            "get_battery_discharge_power"
        )
        assert charge["status"] == "ok"
        assert discharge["status"] == "ok"
        assert charge["current_value"] == "0"
        assert discharge["current_value"] == "800"

    def test_grid_rows_report_the_split_not_the_raw_value(self, signed_grid_ctrl):
        signed_grid_ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "-1500"})
        )
        imp = signed_grid_ctrl.get_method_sensor_info("get_import_power")
        exp = signed_grid_ctrl.get_method_sensor_info("get_export_power")
        assert imp["current_value"] == "0"
        assert exp["current_value"] == "1500"

    def test_separate_entities_still_report_the_raw_state(self, ctrl):
        """Two real entities must pass the state through untouched — including
        its original string form, which callers have always received."""
        ctrl.sensors = {
            **ctrl.sensors,
            "battery_charge_power": "sensor.charge",
            "battery_discharge_power": "sensor.discharge",
        }
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "-800"})
        )
        info = ctrl.get_method_sensor_info("get_battery_discharge_power")
        assert info["current_value"] == "-800"

    def test_precision_is_not_degraded(self, signed_battery_ctrl):
        """The split must not round or reformat a legitimate reading — the
        default %g would turn 12345.678 into 12345.7, and anything above 1e6
        into scientific notation."""
        signed_battery_ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "12345.678"})
        )
        info = signed_battery_ctrl.get_method_sensor_info("get_battery_charge_power")
        assert info["current_value"] == "12345.678"

        signed_battery_ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "2000000"})
        )
        info = signed_battery_ctrl.get_method_sensor_info("get_battery_charge_power")
        assert info["current_value"] == "2000000"

    def test_unknown_polarity_reports_the_real_reason(self):
        """The ValueError must not be swallowed by the surrounding handler and
        reported as a connectivity failure — that would hide precisely the loud
        failure the raise exists to produce."""
        c = HomeAssistantAPIController(
            ha_url="http://ha.local:8123",
            token="test-token",
            settings_store=_settings_store(
                {
                    "battery_charge_power": "sensor.signed_battery_power",
                    "battery_discharge_power": "sensor.signed_battery_power",
                }
            ),
            battery_power_polarity="discharge_positive",
        )
        c.max_attempts = 1
        c.retry_base_delay = 0
        c.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "-800"})
        )
        info = c.get_method_sensor_info("get_battery_charge_power")
        assert info["status"] == "error"
        assert "discharge_positive" in info["error"]
        assert "Failed to check entity" not in info["error"]

    def test_unrelated_method_is_untouched(self, signed_battery_ctrl):
        """Only the four split getters are rewritten; every other row keeps
        reporting the entity's own state."""
        signed_battery_ctrl.sensors = {
            **signed_battery_ctrl.sensors,
            "battery_soc": "sensor.soc",
        }
        signed_battery_ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "47.5"})
        )
        info = signed_battery_ctrl.get_method_sensor_info("get_battery_soc")
        assert info["current_value"] == "47.5"


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("solax_modbus_native", "charge_positive"),
        ("huawei_solar_luna2000", "charge_positive"),
        ("growatt_server_min", ""),
        ("growatt_server_sph", ""),
        ("solax_modbus_growatt_min", ""),
        ("solax_modbus_growatt_sph", ""),
        ("solis_modbus", ""),
        ("", ""),
    ],
)
def test_battery_power_polarity_per_platform(platform: str, expected: str) -> None:
    """Only the two one-signed-register platforms carry a polarity (#542).

    Growatt (both cloud and via solax_modbus) and Solis publish two real
    entities, so they must resolve to "" and keep reading them independently.
    """
    store = SettingsStore()
    store.data["inverter"] = {"platform": platform}
    assert store.get_battery_power_polarity() == expected


# ── Phase current discovery (issue #120) ─────────────────────────────────────


def _current_state(entity_id: str) -> dict:
    """A minimal /api/states entry for a current-measuring sensor."""
    return {"entity_id": entity_id, "attributes": {"device_class": "current"}}


class TestPhaseCurrentDiscovery:
    def setup_method(self):
        self.ctrl = HomeAssistantAPIController(
            ha_url="http://ha.local:8123", token="test-token"
        )

    def test_current_l1_naming_is_discovered(self):
        """Tibber Pulse / Shelly 3EM style naming — the pre-existing case."""
        states = [
            _current_state("sensor.tibber_pulse_current_l1"),
            _current_state("sensor.tibber_pulse_current_l2"),
            _current_state("sensor.tibber_pulse_current_l3"),
        ]
        assert self.ctrl.discover_current_sensors(states) == {
            "current_l1": "sensor.tibber_pulse_current_l1",
            "current_l2": "sensor.tibber_pulse_current_l2",
            "current_l3": "sensor.tibber_pulse_current_l3",
        }

    def test_power_meter_phase_abc_naming_is_discovered(self):
        """issue #120: huawei_solar names the three-phase meter's currents
        'Phase A/B/C current' (register keys active_grid_a/b/c_current), so
        they land as sensor.power_meter_phase_a_current — never matching the
        current_l1/l2/l3 substrings the discovery used to require."""
        states = [
            _current_state("sensor.power_meter_phase_a_current"),
            _current_state("sensor.power_meter_phase_b_current"),
            _current_state("sensor.power_meter_phase_c_current"),
        ]
        assert self.ctrl.discover_current_sensors(states) == {
            "current_l1": "sensor.power_meter_phase_a_current",
            "current_l2": "sensor.power_meter_phase_b_current",
            "current_l3": "sensor.power_meter_phase_c_current",
        }

    def test_inverter_phase_currents_are_not_discovered(self):
        """huawei_solar gives the *inverter's* own AC output currents the same
        display name ('Phase A current') as the meter's, so they differ only
        by device prefix. Binding fuse protection to the inverter's output
        instead of the house feed would silently protect the wrong circuit."""
        states = [
            _current_state("sensor.inverter_phase_a_current"),
            _current_state("sensor.inverter_phase_b_current"),
            _current_state("sensor.inverter_phase_c_current"),
        ]
        assert self.ctrl.discover_current_sensors(states) == {}

    def test_meter_phases_win_when_both_devices_are_present(self):
        """The realistic Huawei install: inverter and power meter both expose
        'Phase A/B/C current'. Only the meter's may be selected."""
        states = [
            _current_state("sensor.inverter_phase_a_current"),
            _current_state("sensor.inverter_phase_b_current"),
            _current_state("sensor.inverter_phase_c_current"),
            _current_state("sensor.power_meter_phase_a_current"),
            _current_state("sensor.power_meter_phase_b_current"),
            _current_state("sensor.power_meter_phase_c_current"),
        ]
        assert self.ctrl.discover_current_sensors(states) == {
            "current_l1": "sensor.power_meter_phase_a_current",
            "current_l2": "sensor.power_meter_phase_b_current",
            "current_l3": "sensor.power_meter_phase_c_current",
        }

    def test_non_current_device_class_is_ignored(self):
        states = [
            {
                "entity_id": "sensor.power_meter_phase_a_voltage",
                "attributes": {"device_class": "voltage"},
            }
        ]
        assert self.ctrl.discover_current_sensors(states) == {}

    def test_all_three_phases_come_from_one_device(self):
        """A sub-circuit meter must not supply some phases and the grid meter
        the rest. "meter" is a bare substring, so a heat-pump or EV submeter
        also passes the gate; per-phase first-match-wins would then blend two
        devices into one reading set and compute a house current that exists
        nowhere. Fuse protection is only meaningful measured at one point.
        """
        states = [
            _current_state("sensor.heatpump_meter_phase_a_current"),
            _current_state("sensor.power_meter_phase_a_current"),
            _current_state("sensor.power_meter_phase_b_current"),
            _current_state("sensor.power_meter_phase_c_current"),
        ]
        result = self.ctrl.discover_current_sensors(states)
        assert result == {
            "current_l1": "sensor.power_meter_phase_a_current",
            "current_l2": "sensor.power_meter_phase_b_current",
            "current_l3": "sensor.power_meter_phase_c_current",
        }

    def test_selection_does_not_depend_on_state_ordering(self):
        """/api/states order is arbitrary and changes between HA restarts;
        which meter backs fuse protection must not."""
        entities = [
            "sensor.heatpump_meter_phase_a_current",
            "sensor.heatpump_meter_phase_b_current",
            "sensor.heatpump_meter_phase_c_current",
            "sensor.power_meter_phase_a_current",
            "sensor.power_meter_phase_b_current",
            "sensor.power_meter_phase_c_current",
        ]
        forward = self.ctrl.discover_current_sensors(
            [_current_state(e) for e in entities]
        )
        reverse = self.ctrl.discover_current_sensors(
            [_current_state(e) for e in reversed(entities)]
        )
        expected = {
            "current_l1": "sensor.power_meter_phase_a_current",
            "current_l2": "sensor.power_meter_phase_b_current",
            "current_l3": "sensor.power_meter_phase_c_current",
        }
        assert forward == expected
        assert reverse == expected

    def test_grid_meter_wins_over_an_equally_complete_submeter(self):
        """Between two complete meter groups the house feed must win.

        Both pass the "meter" gate and carry all three phases, so only the
        name separates them. Sorting on the id alone would pick
        ``easee_meter`` (lexicographically first) — an EV-charger clamp
        carrying a fraction of the house current, so the main fuse trips
        without BESS ever throttling.
        """
        entities = [
            "sensor.easee_meter_phase_a_current",
            "sensor.easee_meter_phase_b_current",
            "sensor.easee_meter_phase_c_current",
            "sensor.power_meter_phase_a_current",
            "sensor.power_meter_phase_b_current",
            "sensor.power_meter_phase_c_current",
        ]
        assert self.ctrl.discover_current_sensors(
            [_current_state(e) for e in entities]
        ) == {
            "current_l1": "sensor.power_meter_phase_a_current",
            "current_l2": "sensor.power_meter_phase_b_current",
            "current_l3": "sensor.power_meter_phase_c_current",
        }

    def test_complete_meter_group_beats_a_single_phase_clamp(self):
        """Phase count outranks the naming convention.

        A lone ``current_l1`` clamp on an EV charger uses the explicitly
        preferred convention, but returning it alone makes the wizard derive
        detected_phase_count = 1 and configure single-phase fuse protection
        on a three-phase house.
        """
        entities = [
            "sensor.wallbox_current_l1",
            "sensor.power_meter_phase_a_current",
            "sensor.power_meter_phase_b_current",
            "sensor.power_meter_phase_c_current",
        ]
        assert self.ctrl.discover_current_sensors(
            [_current_state(e) for e in entities]
        ) == {
            "current_l1": "sensor.power_meter_phase_a_current",
            "current_l2": "sensor.power_meter_phase_b_current",
            "current_l3": "sensor.power_meter_phase_c_current",
        }

    def test_explicit_l1_l2_l3_naming_wins_over_meter_phase_naming(self):
        """An install with both a dedicated household clamp meter and a
        Huawei smart meter keeps the explicit current_l1/l2/l3 set, so
        upgrading does not silently repoint fuse protection."""
        states = [
            _current_state("sensor.power_meter_phase_a_current"),
            _current_state("sensor.power_meter_phase_b_current"),
            _current_state("sensor.power_meter_phase_c_current"),
            _current_state("sensor.tibber_pulse_current_l1"),
            _current_state("sensor.tibber_pulse_current_l2"),
            _current_state("sensor.tibber_pulse_current_l3"),
        ]
        assert self.ctrl.discover_current_sensors(states) == {
            "current_l1": "sensor.tibber_pulse_current_l1",
            "current_l2": "sensor.tibber_pulse_current_l2",
            "current_l3": "sensor.tibber_pulse_current_l3",
        }

    def test_single_phase_install_still_discovers_its_one_phase(self):
        states = [_current_state("sensor.pulse_current_l1")]
        assert self.ctrl.discover_current_sensors(states) == {
            "current_l1": "sensor.pulse_current_l1"
        }

    def test_ha_collision_suffix_does_not_split_one_meter(self):
        """HA appends _2 to an entity id that collides with an existing one,
        per entity — so one phase of an otherwise uniform set can carry it.
        Grouping on the raw id would split the meter in two and return the
        larger half, leaving a phase unmapped on a three-phase house."""
        states = [
            _current_state("sensor.tibber_pulse_current_l1"),
            _current_state("sensor.tibber_pulse_current_l2"),
            _current_state("sensor.tibber_pulse_current_l3_2"),
        ]
        assert self.ctrl.discover_current_sensors(states) == {
            "current_l1": "sensor.tibber_pulse_current_l1",
            "current_l2": "sensor.tibber_pulse_current_l2",
            "current_l3": "sensor.tibber_pulse_current_l3_2",
        }

    def test_a_group_without_l1_is_not_returned(self):
        """PowerMonitor reads current_l1 unconditionally, so a set missing it
        raises on every quarter. Reporting nothing found leaves the user with
        an unconfigured sensor to map, not throttling that always fails."""
        states = [
            _current_state("sensor.power_meter_phase_b_current"),
            _current_state("sensor.power_meter_phase_c_current"),
        ]
        assert self.ctrl.discover_current_sensors(states) == {}

    def test_a_two_phase_group_is_not_returned(self):
        """The wizard accepts a detected phase count of 1 or 3 only."""
        states = [
            _current_state("sensor.power_meter_phase_a_current"),
            _current_state("sensor.power_meter_phase_b_current"),
        ]
        assert self.ctrl.discover_current_sensors(states) == {}

    def test_a_complete_group_wins_over_an_unusable_one(self):
        states = [
            _current_state("sensor.heatpump_meter_phase_b_current"),
            _current_state("sensor.heatpump_meter_phase_c_current"),
            _current_state("sensor.power_meter_phase_a_current"),
            _current_state("sensor.power_meter_phase_b_current"),
            _current_state("sensor.power_meter_phase_c_current"),
        ]
        assert self.ctrl.discover_current_sensors(states) == {
            "current_l1": "sensor.power_meter_phase_a_current",
            "current_l2": "sensor.power_meter_phase_b_current",
            "current_l3": "sensor.power_meter_phase_c_current",
        }

    def test_line_to_line_currents_are_not_read_as_a_phase(self):
        """A meter exposing phase-to-phase currents names them phase_ab. As a
        bare substring that matches phase_a, and a line-to-line current fed
        into fuse protection is not the phase load at all."""
        states = [
            _current_state("sensor.power_meter_phase_ab_current"),
            _current_state("sensor.power_meter_phase_bc_current"),
            _current_state("sensor.power_meter_phase_ca_current"),
        ]
        assert self.ctrl.discover_current_sensors(states) == {}


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
        ctrl.sensors = {**ctrl.sensors, "grid_charge": "select.grid_charge_mode"}
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

    def test_set_charge_stop_soc_input_number_entity(self, ctrl):
        """Regression test for #372: a user-overridden input_number.* entity
        must be written via input_number.set_value, not number.set_value —
        the latter is scoped to the number platform and silently fails
        against an input_number entity."""
        ctrl.sensors = {
            **ctrl.sensors,
            "battery_charge_stop_soc": "input_number.charge_stop_soc",
        }
        with patch.object(ctrl, "_service_call_with_retry") as mock:
            ctrl.set_charge_stop_soc(90)
            assert mock.call_args[0][:2] == ("input_number", "set_value")
            assert mock.call_args[1]["value"] == 90

    def test_set_charge_stop_soc_number_entity_still_uses_number_domain(self, ctrl):
        with patch.object(ctrl, "_service_call_with_retry") as mock:
            ctrl.set_charge_stop_soc(90)
            assert mock.call_args[0][:2] == ("number", "set_value")


class TestSetGrowattExportLimit:
    """Export-limit curtailment writes (registers 122/123, #269)."""

    @pytest.fixture
    def export_ctrl(self, ctrl):
        ctrl.sensors = {
            **ctrl.sensors,
            "growatt_export_limit_mode": "select.limit_grid_export",
            "growatt_export_limit_value": "number.grid_export_limit",
        }
        return ctrl

    def test_curtail_writes_meter_1_and_zero_percent(self, export_ctrl):
        with patch.object(export_ctrl, "_service_call_with_retry") as mock:
            export_ctrl.set_growatt_export_limit(curtail=True)
            calls = mock.call_args_list
            assert ("select", "select_option") in [c[0] for c in calls]
            assert ("number", "set_value") in [c[0] for c in calls]
            select_call = next(c for c in calls if c[0] == ("select", "select_option"))
            assert select_call[1]["option"] == "Meter 1"
            number_call = next(c for c in calls if c[0] == ("number", "set_value"))
            assert number_call[1]["value"] == 0

    def test_release_writes_disabled(self, export_ctrl):
        with patch.object(export_ctrl, "_service_call_with_retry") as mock:
            export_ctrl.set_growatt_export_limit(curtail=False)
            select_call = next(
                c for c in mock.call_args_list if c[0] == ("select", "select_option")
            )
            assert select_call[1]["option"] == "Disabled"
            # Release does not touch the percentage register — only the mode.
            assert ("number", "set_value") not in [c[0] for c in mock.call_args_list]


class TestSetTouSegmentViaEntities:
    """Regression test for #362: begin/end must use time.set_value, not
    select.select_option, when the resolved entity is HA domain `time.*`
    (the only domain solax_modbus's Growatt plugin exposes for TOU
    begin/end — select.select_option against it is a silent HA no-op)."""

    @pytest.fixture
    def tou_ctrl(self, ctrl):
        ctrl.sensors = {
            **ctrl.sensors,
            "tou_time_1_enabled": "select.pv_growatt_time_1_active",
            "tou_time_1_begin": "time.pv_growatt_time_1_begin",
            "tou_time_1_end": "time.pv_growatt_time_1_end",
            "tou_time_1_mode": "select.pv_growatt_time_1_mode",
            "tou_time_1_update": "button.pv_growatt_time_1_update",
        }
        return ctrl

    def test_begin_end_written_via_time_set_value(self, tou_ctrl):
        with patch.object(tou_ctrl, "_service_call_with_retry") as mock:
            tou_ctrl.set_tou_segment_via_entities(
                segment_id=1,
                batt_mode="grid_first",
                start_time="07:00",
                end_time="08:59",
                enabled=True,
            )

        calls_by_entity = {
            call.kwargs["entity_id"]: call
            for call in mock.call_args_list
            if "entity_id" in call.kwargs
        }

        begin_call = calls_by_entity["time.pv_growatt_time_1_begin"]
        assert begin_call.args[:2] == ("time", "set_value")
        assert begin_call.kwargs["time"] == "07:00:00"

        end_call = calls_by_entity["time.pv_growatt_time_1_end"]
        assert end_call.args[:2] == ("time", "set_value")
        assert end_call.kwargs["time"] == "08:59:00"

    def test_mode_and_enabled_still_use_select_option(self, tou_ctrl):
        with patch.object(tou_ctrl, "_service_call_with_retry") as mock:
            tou_ctrl.set_tou_segment_via_entities(
                segment_id=1,
                batt_mode="grid_first",
                start_time="07:00",
                end_time="08:59",
                enabled=True,
            )

        calls_by_entity = {
            call.kwargs["entity_id"]: call
            for call in mock.call_args_list
            if "entity_id" in call.kwargs
        }

        mode_call = calls_by_entity["select.pv_growatt_time_1_mode"]
        assert mode_call.args[:2] == ("select", "select_option")
        assert mode_call.kwargs["option"] == "Grid First"

        enabled_call = calls_by_entity["select.pv_growatt_time_1_active"]
        assert enabled_call.args[:2] == ("select", "select_option")
        assert enabled_call.kwargs["option"] == "Enabled"


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
        ctrl.sensors = {**ctrl.sensors, "grid_charge": "select.grid_charge_mode"}
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
            settings_store=_settings_store({"bad_sensor": ""}),
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


# ── sensors as a live settings_store view (issue #334) ────────────────────────


class TestSensorsLiveView:
    def test_sensors_reflects_settings_store_without_refresh_call(self):
        """`.sensors` must read through to settings_store on every access —
        no manually-synced cache, so no refresh call is ever needed."""
        from core.bess.settings_store import SettingsStore

        store = SettingsStore()
        store.data["sensors"] = {"battery_soc": "sensor.battery_soc"}
        c = HomeAssistantAPIController(
            ha_url="http://ha.local:8123", token="t", settings_store=store
        )
        assert c.sensors == {"battery_soc": "sensor.battery_soc"}

        # Settings mutate externally (e.g. an inverter platform switch) with
        # no call back into the controller at all.
        store.data["sensors"] = {"battery_soc": "sensor.battery_soc_v2"}

        assert c.sensors == {"battery_soc": "sensor.battery_soc_v2"}


class TestConsumptionOverlayBlocksStateGating:
    """The `blocks` attribute is the data; `state` is incidental.

    The documented template example sets `state` from an `input_boolean`,
    which reads as the literal string "unknown" if that helper is ever
    missing or renamed -- even though `blocks` renders just fine. Gating
    solely on `state` would make that documented example a schedule-stopper.
    """

    @pytest.fixture
    def overlay_ctrl(self) -> HomeAssistantAPIController:
        c = HomeAssistantAPIController(
            ha_url="http://ha.local:8123",
            token="test-token",
            settings_store=_settings_store(
                {"consumption_overlay": "sensor.bess_consumption_overlay"}
            ),
            service_domain="growatt_server",
        )
        c.max_attempts = 1
        c.retry_base_delay = 0
        c.failure_tracker = RuntimeFailureTracker()
        return c

    def test_blocks_are_read_even_when_state_is_unknown(
        self, overlay_ctrl: HomeAssistantAPIController
    ) -> None:
        with patch.object(
            overlay_ctrl,
            "_api_request",
            return_value={
                "state": "unknown",
                "attributes": {"blocks": []},
            },
        ):
            assert overlay_ctrl.get_consumption_overlay_blocks() == []

    def test_blocks_are_read_even_when_state_is_unavailable(
        self, overlay_ctrl: HomeAssistantAPIController
    ) -> None:
        with patch.object(
            overlay_ctrl,
            "_api_request",
            return_value={
                "state": "unavailable",
                "attributes": {"blocks": []},
            },
        ):
            assert overlay_ctrl.get_consumption_overlay_blocks() == []

    def test_missing_blocks_attribute_with_unknown_state_reports_the_state(
        self, overlay_ctrl: HomeAssistantAPIController
    ) -> None:
        from core.bess.exceptions import ConsumptionOverlayError

        with patch.object(
            overlay_ctrl,
            "_api_request",
            return_value={"state": "unknown", "attributes": {}},
        ):
            with pytest.raises(ConsumptionOverlayError, match="is unknown"):
                overlay_ctrl.get_consumption_overlay_blocks()

    def test_missing_blocks_attribute_with_a_real_state_reports_missing_blocks(
        self, overlay_ctrl: HomeAssistantAPIController
    ) -> None:
        from core.bess.exceptions import ConsumptionOverlayError

        with patch.object(
            overlay_ctrl,
            "_api_request",
            return_value={"state": "ok", "attributes": {}},
        ):
            with pytest.raises(ConsumptionOverlayError, match="no 'blocks'"):
                overlay_ctrl.get_consumption_overlay_blocks()


class TestGetDeviceMaps:
    """The registry maps feed banner grouping. A registry query failure must
    surface as an explicit ``SystemConfigurationError`` (the banner call site
    decides how to degrade), and successful queries build both maps and cache
    them for the TTL."""

    def test_raises_on_registry_query_failure(
        self, ctrl: HomeAssistantAPIController, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = MagicMock()
        ws.side_effect = RuntimeError("auth failed")
        monkeypatch.setattr(ctrl, "_ws_query", ws)
        with pytest.raises(SystemConfigurationError, match="device/entity registries"):
            ctrl.get_device_maps()

    def test_builds_maps_from_registries(
        self, ctrl: HomeAssistantAPIController, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = MagicMock()
        ws.return_value = [
            [
                {"entity_id": "sensor.a", "device_id": "dev-1"},
                {"entity_id": "sensor.b", "device_id": "dev-1"},
                {"entity_id": "sensor.unmapped"},
            ],
            [
                {"id": "dev-1", "name": "Power Inverter"},
                {"id": "dev-2"},
            ],
        ]
        monkeypatch.setattr(ctrl, "_ws_query", ws)
        entity_to_device, device_names = ctrl.get_device_maps()
        assert entity_to_device == {"sensor.a": "dev-1", "sensor.b": "dev-1"}
        assert device_names == {"dev-1": "Power Inverter", "dev-2": "dev-2"}

    def test_caches_maps_within_ttl(
        self, ctrl: HomeAssistantAPIController, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = MagicMock()
        ws.return_value = [[], []]
        monkeypatch.setattr(ctrl, "_ws_query", ws)
        first = ctrl.get_device_maps()
        second = ctrl.get_device_maps()
        assert ws.call_count == 1
        assert second is first


class TestSolcastDetailedHourlyToQuarterly:
    """The pure Solcast parse, shared with scripts/knee_oracle.py.

    Module-level so a forecast replayed from a debug bundle is parsed by the
    same code that parsed it live (#602/#687/#381).
    """

    def test_expands_hours_to_96_quarters(self) -> None:
        quarterly = solcast_detailed_hourly_to_quarterly(
            [{"period_start": "2026-08-07T12:00:00+02:00", "pv_estimate": 4.0}]
        )

        assert len(quarterly) == 96
        assert quarterly[48:52] == pytest.approx([1.0] * 4)

    def test_missing_hours_stay_zero(self) -> None:
        """Solcast omits pre-dawn hours; absence means no sun, not no data."""
        quarterly = solcast_detailed_hourly_to_quarterly(
            [{"period_start": "2026-08-07T12:00:00+02:00", "pv_estimate": 4.0}]
        )

        assert quarterly[:48] == pytest.approx([0.0] * 48)
        assert quarterly[52:] == pytest.approx([0.0] * 44)

    def test_hour_is_read_naively_from_the_payload_offset(self) -> None:
        """Pinned because it is surprising and a reimplementation got it wrong.

        The hour is taken from the string as written, with no conversion to
        local time. A copy that helpfully called `astimezone` would agree only
        while the feed serialises in local time and shift by the UTC offset
        otherwise -- silently moving sunrise in anything replaying this.
        """
        quarterly = solcast_detailed_hourly_to_quarterly(
            [{"period_start": "2026-08-07T06:00:00+00:00", "pv_estimate": 2.0}]
        )

        assert quarterly[24:28] == pytest.approx([0.5] * 4)  # hour 6, not hour 8
        assert quarterly[32:36] == pytest.approx([0.0] * 4)

    def test_accepts_datetime_period_start(self) -> None:
        from datetime import datetime

        quarterly = solcast_detailed_hourly_to_quarterly(
            [{"period_start": datetime(2026, 8, 7, 9), "pv_estimate": 1.2}]
        )

        assert quarterly[36:40] == pytest.approx([0.3] * 4)
