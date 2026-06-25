"""Tests for check_prediction_health strategy awareness.

The health check must validate only the forecast path used by the active
consumption strategy.  Before this fix, it always checked
``get_estimated_consumption`` (the ``sensor`` strategy sensor), producing
false-positive warnings when other strategies were active.
"""

import pytest

from core.bess.sensor_collector import SensorCollector
from core.bess.settings import BatterySettings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_controller(
    estimated_consumption_ok: bool = True,
    solar_forecast_ok: bool = True,
):
    """Return a minimal controller stub with configurable sensor behaviour.

    ``validate_methods_sensors`` is the gateway used by ``perform_health_check``.
    Methods that are "ok" are then called directly; raising an exception
    simulates a broken/missing sensor at the method level.
    """
    from unittest.mock import MagicMock

    controller = MagicMock()
    controller.METHOD_SENSOR_MAP = {
        "get_estimated_consumption": {
            "sensor_key": "48h_avg_grid_import",
            "name": "Average Hourly Power Consumption",
            "unit": "W",
            "precision": 1,
            "conversion_threshold": 1000,
        },
        "get_solar_forecast": {
            "sensor_key": "solar_forecast_today",
            "name": "Solar Forecast",
            "unit": "list",
            "precision": 1,
            "conversion_threshold": None,
        },
    }

    def _validate(method_list):
        results = []
        for name in method_list:
            info = controller.METHOD_SENSOR_MAP.get(name, {})
            results.append(
                {
                    "method_name": name,
                    "name": info.get("name", name),
                    "sensor_key": info.get("sensor_key", name),
                    "entity_id": f"sensor.{info.get('sensor_key', name)}",
                    "status": "ok",
                    "error": None,
                }
            )
        return results

    controller.validate_methods_sensors.side_effect = _validate

    if estimated_consumption_ok:
        controller.get_estimated_consumption.return_value = [1.125] * 96
    else:
        from core.bess.exceptions import SystemConfigurationError

        controller.get_estimated_consumption.side_effect = SystemConfigurationError(
            "48h_avg_grid_import sensor not available"
        )

    if solar_forecast_ok:
        controller.get_solar_forecast.return_value = [0.5] * 96
    else:
        from core.bess.exceptions import SystemConfigurationError

        controller.get_solar_forecast.side_effect = SystemConfigurationError(
            "solar_forecast_today sensor not available"
        )

    return controller


def _make_collector(controller=None) -> SensorCollector:
    if controller is None:
        controller = _make_controller()
    settings = BatterySettings()
    return SensorCollector(controller, settings)


# ---------------------------------------------------------------------------
# check_prediction_health — sensor strategy
# ---------------------------------------------------------------------------


class TestSensorStrategy:
    def test_ok_when_estimated_consumption_available(self):
        collector = _make_collector(_make_controller(estimated_consumption_ok=True))
        result = collector.check_prediction_health("sensor")
        assert result["status"] == "OK"

    def test_includes_estimated_consumption_check(self):
        collector = _make_collector(_make_controller(estimated_consumption_ok=True))
        result = collector.check_prediction_health("sensor")
        method_names = [c["method_name"] for c in result["checks"]]
        assert "get_estimated_consumption" in method_names

    def test_warning_when_estimated_consumption_unavailable(self):
        collector = _make_collector(_make_controller(estimated_consumption_ok=False))
        result = collector.check_prediction_health("sensor")
        # is_required=False → failure → WARNING not ERROR
        assert result["status"] == "WARNING"

    def test_consumption_check_shows_error_when_sensor_fails(self):
        collector = _make_collector(_make_controller(estimated_consumption_ok=False))
        result = collector.check_prediction_health("sensor")
        consumption_check = next(
            c
            for c in result["checks"]
            if c["method_name"] == "get_estimated_consumption"
        )
        assert consumption_check["status"] == "ERROR"


# ---------------------------------------------------------------------------
# check_prediction_health — fixed strategy
# ---------------------------------------------------------------------------


class TestFixedStrategy:
    def test_ok_without_any_consumption_sensor(self):
        # fixed strategy never needs the HA sensor
        controller = _make_controller(estimated_consumption_ok=False)
        collector = _make_collector(controller)
        result = collector.check_prediction_health("fixed")
        assert result["status"] == "OK"

    def test_does_not_check_estimated_consumption(self):
        collector = _make_collector()
        result = collector.check_prediction_health("fixed")
        method_names = [c["method_name"] for c in result["checks"]]
        assert "get_estimated_consumption" not in method_names


# ---------------------------------------------------------------------------
# check_prediction_health — influxdb_7d_avg strategy
# ---------------------------------------------------------------------------


class TestInfluxdb7dAvgStrategy:
    def test_ok_without_consumption_sensor(self):
        controller = _make_controller(estimated_consumption_ok=False)
        collector = _make_collector(controller)
        result = collector.check_prediction_health("influxdb_7d_avg")
        assert result["status"] == "OK"

    def test_does_not_check_estimated_consumption(self):
        collector = _make_collector()
        result = collector.check_prediction_health("influxdb_7d_avg")
        method_names = [c["method_name"] for c in result["checks"]]
        assert "get_estimated_consumption" not in method_names


# ---------------------------------------------------------------------------
# check_prediction_health — ha_statistics strategy
# ---------------------------------------------------------------------------


class TestHaStatisticsStrategy:
    def test_ok_without_48h_avg_grid_import_sensor(self):
        """Core bug regression: ha_statistics strategy must not fail due to
        missing 48h_avg_grid_import (the sensor strategy's sensor)."""
        controller = _make_controller(estimated_consumption_ok=False)
        collector = _make_collector(controller)
        result = collector.check_prediction_health("ha_statistics")
        assert result["status"] == "OK"

    def test_does_not_check_estimated_consumption(self):
        collector = _make_collector()
        result = collector.check_prediction_health("ha_statistics")
        method_names = [c["method_name"] for c in result["checks"]]
        assert "get_estimated_consumption" not in method_names


# ---------------------------------------------------------------------------
# Solar forecast is always validated regardless of strategy
# ---------------------------------------------------------------------------


class TestSolarForecastAlwaysChecked:
    @pytest.mark.parametrize(
        "strategy", ["sensor", "fixed", "influxdb_7d_avg", "ha_statistics"]
    )
    def test_solar_forecast_included_for_all_strategies(self, strategy):
        collector = _make_collector()
        result = collector.check_prediction_health(strategy)
        method_names = [c["method_name"] for c in result["checks"]]
        assert "get_solar_forecast" in method_names

    @pytest.mark.parametrize(
        "strategy", ["sensor", "fixed", "influxdb_7d_avg", "ha_statistics"]
    )
    def test_warning_when_solar_forecast_unavailable(self, strategy):
        controller = _make_controller(solar_forecast_ok=False)
        collector = _make_collector(controller)
        result = collector.check_prediction_health(strategy)
        assert result["status"] == "WARNING"


# ---------------------------------------------------------------------------
# check_health passes strategy through to prediction check
# ---------------------------------------------------------------------------


class TestCheckHealthStrategyPropagation:
    def test_default_strategy_is_sensor(self):
        """check_health() with no argument uses sensor strategy."""
        collector = _make_collector()
        checks = collector.check_health()
        prediction = next(c for c in checks if c["name"] == "Energy Prediction")
        method_names = [ch["method_name"] for ch in prediction["checks"]]
        assert "get_estimated_consumption" in method_names

    def test_ha_statistics_strategy_omits_consumption_sensor(self):
        collector = _make_collector()
        checks = collector.check_health("ha_statistics")
        prediction = next(c for c in checks if c["name"] == "Energy Prediction")
        method_names = [ch["method_name"] for ch in prediction["checks"]]
        assert "get_estimated_consumption" not in method_names

    def test_fixed_strategy_omits_consumption_sensor(self):
        collector = _make_collector()
        checks = collector.check_health("fixed")
        prediction = next(c for c in checks if c["name"] == "Energy Prediction")
        method_names = [ch["method_name"] for ch in prediction["checks"]]
        assert "get_estimated_consumption" not in method_names
