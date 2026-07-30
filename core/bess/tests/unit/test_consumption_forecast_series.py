"""Tests for the ha_consumption_series consumption-forecast strategy.

Mirrors the price-manager entity pattern: one HA entity, `raw_today` /
`raw_tomorrow` attributes of {start, value} timestamped records. Unlike
prices, this must normalize whatever record interval the user's HA template
produces (15 or 60 minutes) onto the DP's quarter-hour grid, and fail
explicitly — never silently fall back — on a missing, stale, malformed, or
horizon-short series (rules.md's no-silent-fallback policy).
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from core.bess import time_utils
from core.bess.exceptions import ConsumptionForecastUnavailableError
from core.bess.ha_api_controller import HomeAssistantAPIController
from core.bess.runtime_failure_tracker import RuntimeFailureTracker


def _session_method_mock(name, return_value=None, side_effect=None):
    m = MagicMock(return_value=return_value, side_effect=side_effect)
    m.__name__ = name
    return m


def _mock_response(json_data):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.content = b'{"ok": true}'
    resp.headers = {"content-type": "application/json"}
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def ctrl():
    c = HomeAssistantAPIController(
        ha_url="http://ha.local:8123",
        token="test-token",
        sensor_config={"consumption_forecast_series": "sensor.house_load_forecast"},
    )
    c.max_attempts = 1
    c.retry_base_delay = 0
    c.failure_tracker = RuntimeFailureTracker()
    return c


def _quarter_hour_records(target_date, kwh_per_period=0.5, count=96):
    """96 records at 15-minute spacing, value = kWh for that period."""
    start = datetime.combine(target_date, datetime.min.time())
    return [
        {
            "start": (start + timedelta(minutes=15 * i)).isoformat(),
            "value": kwh_per_period,
        }
        for i in range(count)
    ]


def _hourly_records(target_date, kwh_per_hour=2.0, count=24):
    """24 records at 60-minute spacing, value = kWh for that hour."""
    start = datetime.combine(target_date, datetime.min.time())
    return [
        {"start": (start + timedelta(hours=i)).isoformat(), "value": kwh_per_hour}
        for i in range(count)
    ]


class TestQuarterHourRecords:
    def test_returns_96_periods_at_native_resolution(self, ctrl):
        today = time_utils.today()
        attrs = {"raw_today": _quarter_hour_records(today, kwh_per_period=0.5)}
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"attributes": attrs})
        )
        result = ctrl.get_consumption_forecast_series()
        assert len(result) == 96
        assert result[0] == pytest.approx(0.5)

    def test_preserves_shaped_evening_peak(self, ctrl):
        today = time_utils.today()
        records = _quarter_hour_records(today, kwh_per_period=0.3)
        # Shape an evening peak at period 80 (20:00) — this is the whole point
        # of the seam: expressing a load the trimmed-mean baseline can't.
        for i in range(80, 84):
            records[i]["value"] = 4.0
        attrs = {"raw_today": records}
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"attributes": attrs})
        )
        result = ctrl.get_consumption_forecast_series()
        assert result[80] == pytest.approx(4.0)
        assert result[0] == pytest.approx(0.3)


class TestHourlyRecordsUpsampled:
    def test_hourly_value_divided_across_four_quarter_periods(self, ctrl):
        today = time_utils.today()
        attrs = {"raw_today": _hourly_records(today, kwh_per_hour=2.0)}
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"attributes": attrs})
        )
        result = ctrl.get_consumption_forecast_series()
        assert len(result) == 96
        assert result[0:4] == pytest.approx([0.5, 0.5, 0.5, 0.5])


class TestTomorrow:
    def test_reads_raw_tomorrow_attribute(self, ctrl):
        tomorrow = time_utils.today() + timedelta(days=1)
        attrs = {"raw_tomorrow": _quarter_hour_records(tomorrow, kwh_per_period=0.7)}
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"attributes": attrs})
        )
        result = ctrl.get_consumption_forecast_series_tomorrow()
        assert len(result) == 96
        assert result[0] == pytest.approx(0.7)


class TestFailureModes:
    def test_unconfigured_entity_raises(self):
        ctrl = HomeAssistantAPIController(
            ha_url="http://ha.local:8123", token="test-token", sensor_config={}
        )
        with pytest.raises(ConsumptionForecastUnavailableError):
            ctrl.get_consumption_forecast_series()

    def test_missing_attributes_raises(self, ctrl):
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"state": "unavailable"})
        )
        with pytest.raises(ConsumptionForecastUnavailableError):
            ctrl.get_consumption_forecast_series()

    def test_stale_data_wrong_date_raises(self, ctrl):
        stale_date = time_utils.today() - timedelta(days=2)
        attrs = {"raw_today": _quarter_hour_records(stale_date)}
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"attributes": attrs})
        )
        with pytest.raises(ConsumptionForecastUnavailableError):
            ctrl.get_consumption_forecast_series()

    def test_malformed_record_missing_value_raises(self, ctrl):
        today = time_utils.today()
        records = _quarter_hour_records(today)
        del records[10]["value"]
        attrs = {"raw_today": records}
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"attributes": attrs})
        )
        with pytest.raises(ConsumptionForecastUnavailableError):
            ctrl.get_consumption_forecast_series()

    def test_short_of_horizon_raises(self, ctrl):
        today = time_utils.today()
        attrs = {"raw_today": _quarter_hour_records(today, count=40)}
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"attributes": attrs})
        )
        with pytest.raises(ConsumptionForecastUnavailableError):
            ctrl.get_consumption_forecast_series()

    def test_unsupported_interval_raises(self, ctrl):
        today = time_utils.today()
        start = datetime.combine(today, datetime.min.time())
        records = [
            {"start": (start + timedelta(minutes=30 * i)).isoformat(), "value": 1.0}
            for i in range(48)
        ]
        attrs = {"raw_today": records}
        ctrl.session.get = _session_method_mock(
            "get", return_value=_mock_response({"attributes": attrs})
        )
        with pytest.raises(ConsumptionForecastUnavailableError):
            ctrl.get_consumption_forecast_series()
