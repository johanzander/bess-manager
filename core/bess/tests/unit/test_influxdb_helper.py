"""Tests for InfluxDB configuration gating in periodic data-fetch functions.

Regression coverage for issue #201: get_sensor_data_batch and
get_power_sensor_data_batch only checked for empty strings, not the shipped
placeholder credentials, so the ~15-minute periodic job kept attempting (and
failing) a real HTTP connection for every user who never configured InfluxDB.
"""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from core.bess import influxdb_helper

PLACEHOLDER_CONFIG = {
    "url": "http://homeassistant.local:8086/api/v2/query",
    "bucket": "home_assistant/autogen",
    "username": "your_db_username_here",
    "password": "your_db_password_here",
}

VALID_CONFIG = {
    "url": "http://homeassistant.local:8086/api/v2/query",
    "bucket": "homeassistant/autogen",
    "username": "real_user",
    "password": "real_password",
}

# The exact body InfluxDB 1.x returns (HTTP 500) when the bucket names a
# database that does not exist -- e.g. the erroneous "home_assistant/autogen"
# (underscore) instead of "homeassistant/autogen". This is the real failure
# a user hit whose only symptom was a bare "InfluxDB error: 500".
NO_DATABASE_BODY = "error failed to initialize execute state: no database"


def _mock_response(status_code: int, text: str) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


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


class TestErrorBodyIsSurfaced:
    """When InfluxDB returns a non-200, the actual response body carries the
    real reason (e.g. 'no database' for a wrong bucket). Surfacing only the
    status code ('InfluxDB error: 500') hid that reason and turned a
    one-line misconfiguration into an opaque failure. Every error path must
    include the body."""

    def test_connection_test_includes_body_for_unmapped_status(self):
        with (
            patch.object(
                influxdb_helper, "get_influxdb_config", return_value=VALID_CONFIG
            ),
            patch.object(
                influxdb_helper.requests,
                "post",
                return_value=_mock_response(500, NO_DATABASE_BODY),
            ),
        ):
            result = influxdb_helper.test_influxdb_connection()

        assert result["status"] == "error"
        assert (
            "no database" in result["message"]
        ), f"Expected the InfluxDB body to be surfaced, got: {result['message']!r}"

    def test_batch_fetch_includes_body_on_error(self):
        with (
            patch.object(influxdb_helper, "is_influxdb_configured", return_value=True),
            patch.object(
                influxdb_helper, "get_influxdb_config", return_value=VALID_CONFIG
            ),
            patch.object(
                influxdb_helper.requests,
                "post",
                return_value=_mock_response(500, NO_DATABASE_BODY),
            ),
        ):
            result = influxdb_helper.get_sensor_data_batch(
                ["battery_soc"], date(2026, 7, 30)
            )

        assert result["status"] == "error"
        assert (
            "no database" in result["message"]
        ), f"Expected the InfluxDB body to be surfaced, got: {result['message']!r}"

    def test_power_batch_fetch_includes_body_on_error(self):
        with (
            patch.object(influxdb_helper, "is_influxdb_configured", return_value=True),
            patch.object(
                influxdb_helper, "get_influxdb_config", return_value=VALID_CONFIG
            ),
            patch.object(
                influxdb_helper.requests,
                "post",
                return_value=_mock_response(500, NO_DATABASE_BODY),
            ),
        ):
            result = influxdb_helper.get_power_sensor_data_batch(
                ["solar_power"], date(2026, 7, 30)
            )

        assert result["status"] == "error"
        assert (
            "no database" in result["message"]
        ), f"Expected the InfluxDB body to be surfaced, got: {result['message']!r}"


class TestShippedConfigDefaultBucket:
    """The shipped add-on default bucket must be a valid InfluxDB 1.x DBRP
    for a stock Home Assistant install. The database is 'homeassistant'
    (no underscore); the earlier default 'home_assistant/autogen' pointed at
    a non-existent database and made every data fetch fail with HTTP 500."""

    def test_config_yaml_default_bucket_matches_stock_ha_database(self):
        config_path = (
            Path(__file__).resolve().parents[4] / "bess_manager" / "config.yaml"
        )
        config = yaml.safe_load(config_path.read_text())
        bucket = config["options"]["influxdb"]["bucket"]
        assert bucket == "homeassistant/autogen", (
            f"Shipped default bucket must target the stock HA database "
            f"'homeassistant' (no underscore), got {bucket!r}"
        )
