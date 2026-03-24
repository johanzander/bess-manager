"""Tests for core.bess.weather module."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.bess.weather import (
    fetch_hourly_weather_forecast,
    fetch_temperature_forecast,
)


def _make_ha_forecast_response(temps: list[float], start_hour: int = 0):
    """Build a mock HA weather forecast API response.

    Args:
        temps: List of hourly temperature values.
        start_hour: Starting hour for datetime generation.

    Returns:
        Dict matching HA service_response structure.
    """
    base = datetime(2026, 3, 8, start_hour, 0, 0, tzinfo=timezone(timedelta(hours=1)))
    forecasts = []
    for i, temp in enumerate(temps):
        dt = base + timedelta(hours=i)
        forecasts.append(
            {
                "datetime": dt.isoformat(),
                "temperature": temp,
                "cloud_coverage": 50,
                "wind_speed": 3.0,
                "precipitation": 0.0,
            }
        )
    return {"service_response": {"weather.forecast_home": {"forecast": forecasts}}}


@pytest.fixture
def mock_post():
    """Patch requests.post for all weather tests."""
    with patch("core.bess.weather.requests.post") as mock:
        yield mock


def _setup_mock(mock_post: MagicMock, temps: list[float]) -> None:
    """Configure mock to return a successful forecast response."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = _make_ha_forecast_response(temps)
    mock_post.return_value = response


class TestFetchHourlyWeatherForecast:
    def test_parses_hourly_entries(self, mock_post):
        temps = [5.0, 6.0, 7.0]
        _setup_mock(mock_post, temps)

        rows = fetch_hourly_weather_forecast(
            "http://ha:8123", "token", "weather.forecast_home", "Europe/Stockholm"
        )

        assert len(rows) == 3
        assert rows[0]["temperature"] == 5.0
        assert rows[1]["temperature"] == 6.0
        assert rows[2]["temperature"] == 7.0

    def test_sends_correct_request(self, mock_post):
        _setup_mock(mock_post, [10.0])

        fetch_hourly_weather_forecast(
            "http://ha:8123", "mytoken", "weather.forecast_home", "Europe/Stockholm"
        )

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "Bearer mytoken" in call_kwargs.kwargs["headers"]["Authorization"]
        assert call_kwargs.kwargs["json"]["entity_id"] == "weather.forecast_home"

    def test_raises_on_http_error(self, mock_post):
        response = MagicMock()
        response.status_code = 500
        response.text = "Internal Server Error"
        mock_post.return_value = response

        with pytest.raises(RuntimeError, match="HTTP 500"):
            fetch_hourly_weather_forecast(
                "http://ha:8123", "token", "weather.forecast_home", "Europe/Stockholm"
            )

    def test_raises_on_missing_entity(self, mock_post):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "service_response": {"weather.other": {"forecast": []}}
        }
        mock_post.return_value = response

        with pytest.raises(RuntimeError, match="No forecast data"):
            fetch_hourly_weather_forecast(
                "http://ha:8123", "token", "weather.forecast_home", "Europe/Stockholm"
            )

    def test_raises_on_empty_forecast(self, mock_post):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "service_response": {"weather.forecast_home": {"forecast": []}}
        }
        mock_post.return_value = response

        with pytest.raises(RuntimeError, match="empty forecast"):
            fetch_hourly_weather_forecast(
                "http://ha:8123", "token", "weather.forecast_home", "Europe/Stockholm"
            )

    def test_strips_trailing_slash_from_url(self, mock_post):
        _setup_mock(mock_post, [10.0])

        fetch_hourly_weather_forecast(
            "http://ha:8123/", "token", "weather.forecast_home", "Europe/Stockholm"
        )

        url_arg = mock_post.call_args.args[0]
        assert "//api" not in url_arg


class TestFetchTemperatureForecast:
    def test_interpolates_to_96_periods(self, mock_post):
        # 25 hourly temps covering 24h + 1 endpoint
        temps = [float(i) for i in range(25)]
        _setup_mock(mock_post, temps)

        result = fetch_temperature_forecast(
            "http://ha:8123",
            "token",
            "weather.forecast_home",
            "Europe/Stockholm",
            num_periods=96,
        )

        assert len(result) == 96

    def test_interpolation_values(self, mock_post):
        # Two hourly values: 0°C and 4°C — interpolated to 4 quarter-hour values
        _setup_mock(mock_post, [0.0, 4.0])

        result = fetch_temperature_forecast(
            "http://ha:8123",
            "token",
            "weather.forecast_home",
            "Europe/Stockholm",
            num_periods=4,
        )

        assert len(result) == 4
        assert result[0] == pytest.approx(0.0)
        assert result[1] == pytest.approx(1.0)
        assert result[2] == pytest.approx(2.0)
        assert result[3] == pytest.approx(3.0)

    def test_single_hourly_value_repeated(self, mock_post):
        _setup_mock(mock_post, [8.0])

        result = fetch_temperature_forecast(
            "http://ha:8123",
            "token",
            "weather.forecast_home",
            "Europe/Stockholm",
            num_periods=10,
        )

        assert len(result) == 10
        assert all(t == 8.0 for t in result)

    def test_pads_short_forecast(self, mock_post):
        # Only 3 hourly values = 12 quarter-hour values, but we request 20
        _setup_mock(mock_post, [5.0, 10.0, 15.0])

        result = fetch_temperature_forecast(
            "http://ha:8123",
            "token",
            "weather.forecast_home",
            "Europe/Stockholm",
            num_periods=20,
        )

        assert len(result) == 20
        # Last padded values should equal the last forecast temperature
        assert result[-1] == 15.0
