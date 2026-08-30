"""Tests for ha_recorder_helper - recorder-backed per-period history reads (#722).

These pin the return contract ha_recorder_helper must match so it can replace
the historical-read half of influxdb_helper in PR 2: same
``{"status", "data": {period: {sensor_key: value}}}`` shape, same 15-minute
period model, ``sensor.``-prefixed keys.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from core.bess import ha_recorder_helper, time_utils
from core.bess.ha_api_controller import HomeAssistantAPIController

UTC = ZoneInfo("UTC")
DAY = date(2026, 8, 20)


@pytest.fixture(autouse=True)
def _utc_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reason in plain UTC - period math only needs internal consistency."""
    monkeypatch.setattr(time_utils, "TIMEZONE", UTC)


def _iso(hour: int, minute: int = 0, day: int = 20) -> str:
    return datetime(2026, 8, day, hour, minute, tzinfo=UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _entry(state: str, ts_iso: str, entity_id: str | None = None) -> dict:
    entry = {"state": state, "last_changed": ts_iso, "last_updated": ts_iso}
    if entity_id:
        entry["entity_id"] = entity_id
    return entry


class FakeController(HomeAssistantAPIController):
    """A stand-in for the real controller — only ``get_history_period`` is used.

    Subclasses the concrete controller (rather than a Protocol) so the helper
    can be typed against ``HomeAssistantAPIController`` directly;
    ``__init__`` is deliberately not chained.
    """

    def __init__(
        self,
        payload: list | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._payload = payload if payload is not None else []
        self._raises = raises
        self.calls: list[tuple] = []

    def get_history_period(
        self, entity_ids: list[str], start_time: str, end_time: str
    ) -> list[list[dict]]:
        self.calls.append((tuple(entity_ids), start_time, end_time))
        if self._raises is not None:
            raise self._raises
        return self._payload


# --------------------------------------------------------------------------- #
# get_sensor_data_batch - cumulative counters                                 #
# --------------------------------------------------------------------------- #


class TestGetSensorDataBatch:
    def test_last_value_before_each_period_boundary(self) -> None:
        fc = FakeController(
            [
                [
                    _entry("10.0", _iso(0), "sensor.imp"),
                    _entry("11.0", _iso(1)),
                    _entry("12.0", _iso(2)),
                ]
            ]
        )

        result = ha_recorder_helper.get_sensor_data_batch(fc, ["imp"], DAY)

        assert result["status"] == "success"
        data = result["data"]
        assert data[0]["sensor.imp"] == 10.0  # period 0 ends 00:14:59
        assert data[4]["sensor.imp"] == 11.0  # period 4 = 01:00-01:14
        assert data[8]["sensor.imp"] == 12.0  # period 8 = 02:00-02:14
        assert data[95]["sensor.imp"] == 12.0  # last known carries forward

    def test_queries_sensor_prefixed_entity_ids(self) -> None:
        fc = FakeController([[_entry("1.0", _iso(0), "sensor.imp")]])

        ha_recorder_helper.get_sensor_data_batch(fc, ["imp"], DAY)

        assert fc.calls[0][0] == ("sensor.imp",)
        assert isinstance(fc.calls[0][1], str) and fc.calls[0][1]
        assert isinstance(fc.calls[0][2], str) and fc.calls[0][2]

    def test_state_before_window_start_fills_all_periods(self) -> None:
        # HA prepends the state as of the window start - a sparse counter that
        # last changed yesterday still yields one sample, at an earlier ts.
        fc = FakeController([[_entry("55.0", _iso(18, day=19), "sensor.soc")]])

        result = ha_recorder_helper.get_sensor_data_batch(fc, ["soc"], DAY)

        data = result["data"]
        assert len(data) == 96
        assert data[0]["sensor.soc"] == 55.0
        assert data[95]["sensor.soc"] == 55.0

    def test_non_numeric_states_are_skipped(self) -> None:
        fc = FakeController(
            [
                [
                    _entry("unknown", _iso(0), "sensor.x"),
                    _entry("unavailable", _iso(1)),
                    _entry("5.0", _iso(2)),
                ]
            ]
        )

        data = ha_recorder_helper.get_sensor_data_batch(fc, ["x"], DAY)["data"]

        assert 0 not in data  # no numeric sample at/before period 0
        assert data[8]["sensor.x"] == 5.0

    def test_all_entities_empty_is_an_error(self) -> None:
        fc = FakeController([[], []])

        result = ha_recorder_helper.get_sensor_data_batch(fc, ["a", "b"], DAY)

        assert result["status"] == "error"
        assert "No recorder history" in result["message"]

    def test_empty_sensor_list_is_an_error_without_calling_ha(self) -> None:
        fc = FakeController()

        result = ha_recorder_helper.get_sensor_data_batch(fc, [], DAY)

        assert result["status"] == "error"
        assert fc.calls == []

    def test_controller_exception_becomes_error_status(self) -> None:
        fc = FakeController(raises=RuntimeError("connection refused"))

        result = ha_recorder_helper.get_sensor_data_batch(fc, ["imp"], DAY)

        assert result["status"] == "error"
        assert "connection refused" in result["message"]


# --------------------------------------------------------------------------- #
# get_power_sensor_data_batch - instantaneous W -> kWh per period             #
# --------------------------------------------------------------------------- #


class TestGetPowerSensorDataBatch:
    def test_period_mean_watts_converted_to_kwh(self) -> None:
        fc = FakeController(
            [
                [
                    _entry("2000", _iso(0, 0), "sensor.p"),
                    _entry("4000", _iso(0, 5)),
                    _entry("1000", _iso(0, 20)),
                ]
            ]
        )

        data = ha_recorder_helper.get_power_sensor_data_batch(fc, ["p"], DAY)["data"]

        # period 0: mean(2000, 4000) = 3000 W -> 3000 * 0.25 / 1000
        assert data[0]["sensor.p"] == pytest.approx(0.75)
        # period 1: single 1000 W reading at 00:20 -> 0.25
        assert data[1]["sensor.p"] == pytest.approx(0.25)

    def test_implausible_spike_is_dropped_from_the_mean(self) -> None:
        fc = FakeController(
            [
                [
                    _entry("500000", _iso(0, 0), "sensor.p"),
                    _entry("3000", _iso(0, 5)),
                ]
            ]
        )

        data = ha_recorder_helper.get_power_sensor_data_batch(fc, ["p"], DAY)["data"]

        assert data[0]["sensor.p"] == pytest.approx(0.75)  # only the 3000 W reading

    def test_empty_sensor_list_is_an_error(self) -> None:
        fc = FakeController()

        result = ha_recorder_helper.get_power_sensor_data_batch(fc, [], DAY)

        assert result["status"] == "error"
        assert fc.calls == []

    def test_no_history_is_an_error(self) -> None:
        fc = FakeController([[]])

        result = ha_recorder_helper.get_power_sensor_data_batch(fc, ["p"], DAY)

        assert result["status"] == "error"
        assert "No recorder history" in result["message"]
