"""Tests for InfluxDB configuration gating in periodic data-fetch functions.

Regression coverage for issue #201: get_sensor_data_batch and
get_power_sensor_data_batch only checked for empty strings, not the shipped
placeholder credentials, so the ~15-minute periodic job kept attempting (and
failing) a real HTTP connection for every user who never configured InfluxDB.
"""

from datetime import date
from unittest.mock import patch

from core.bess import influxdb_helper

PLACEHOLDER_CONFIG = {
    "url": "http://homeassistant.local:8086/api/v2/query",
    "bucket": "home_assistant/autogen",
    "username": "your_db_username_here",
    "password": "your_db_password_here",
}


class TestGetSensorDataBatchSkipsUnconfigured:
    def test_does_not_attempt_http_request_with_placeholder_credentials(self):
        with (
            patch.object(
                influxdb_helper,
                "get_influxdb_config",
                return_value=PLACEHOLDER_CONFIG,
            ),
            patch.object(influxdb_helper.requests, "post") as mock_post,
        ):
            result = influxdb_helper.get_sensor_data_batch(
                ["sensor.battery_soc"], date(2026, 7, 1)
            )

        mock_post.assert_not_called()
        assert result["status"] == "error"


class TestGetPowerSensorDataBatchSkipsUnconfigured:
    def test_does_not_attempt_http_request_with_placeholder_credentials(self):
        with (
            patch.object(
                influxdb_helper,
                "get_influxdb_config",
                return_value=PLACEHOLDER_CONFIG,
            ),
            patch.object(influxdb_helper.requests, "post") as mock_post,
        ):
            result = influxdb_helper.get_power_sensor_data_batch(
                ["sensor.solar_power"], date(2026, 7, 1)
            )

        mock_post.assert_not_called()
        assert result["status"] == "error"


class TestIsInfluxdbConfiguredRequiresBucket:
    def test_returns_false_when_bucket_is_empty(self):
        config = {
            "url": "http://homeassistant.local:8086/api/v2/query",
            "bucket": "",
            "username": "real_user",
            "password": "real_password",
        }
        with patch.object(influxdb_helper, "get_influxdb_config", return_value=config):
            assert influxdb_helper.is_influxdb_configured() is False
