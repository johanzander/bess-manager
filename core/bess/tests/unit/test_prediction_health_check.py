"""Tests for check_prediction_health strategy awareness.

The health check must validate only the forecast path used by the active
consumption strategy.  Before this fix, it always checked
``get_estimated_consumption`` (the ``sensor`` strategy sensor), producing
false-positive warnings when other strategies were active.
"""

from unittest.mock import patch

import pytest

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.price_manager import MockSource
from core.bess.sensor_collector import SensorCollector
from core.bess.settings import BatterySettings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_controller(
    estimated_consumption_ok: bool = True,
    solar_forecast_ok: bool = True,
    estimated_consumption_configured: bool = True,
    overlay_configured: bool = False,
    overlay_ok: bool = True,
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
        "get_consumption_overlay_blocks": {
            "sensor_key": "consumption_overlay",
            "name": "Planned Consumption Changes",
            "unit": "list",
            "precision": None,
            "conversion_threshold": None,
        },
    }
    controller.is_sensor_configured.side_effect = lambda key: (
        overlay_configured if key == "consumption_overlay" else True
    )

    if overlay_ok:
        controller.get_consumption_overlay_blocks.return_value = []
    else:
        from core.bess.exceptions import ConsumptionOverlayError

        controller.get_consumption_overlay_blocks.side_effect = ConsumptionOverlayError(
            "overlay block 0 is missing 'end'"
        )

    def _validate(method_list):
        results = []
        for name in method_list:
            info = controller.METHOD_SENSOR_MAP.get(name, {})
            if name == "get_estimated_consumption" and not (
                estimated_consumption_configured
            ):
                # Mirrors get_method_sensor_info() when the sensor key resolves
                # to nothing: the user never mapped an entity for it.
                results.append(
                    {
                        "method_name": name,
                        "name": info.get("name", name),
                        "sensor_key": info.get("sensor_key", name),
                        "entity_id": "Not configured",
                        "status": "not_configured",
                        "error": "Sensor not configured",
                    }
                )
                continue
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

    # An unmapped sensor also fails at the method level: _get_sensor_value
    # returns None and get_estimated_consumption raises
    # (ha_api_controller.py:1369-1371).
    if not estimated_consumption_configured:
        estimated_consumption_ok = False

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

    def test_error_when_estimated_consumption_unavailable(self):
        """Issue #558: under the sensor strategy this sensor is what every
        optimization run reads. A broken one means no schedule can ever be
        built, so it must surface as ERROR (a critical failure the dashboard
        shows) rather than a WARNING nobody acts on."""
        collector = _make_collector(_make_controller(estimated_consumption_ok=False))
        result = collector.check_prediction_health("sensor")
        assert result["status"] == "ERROR"

    def test_error_when_estimated_consumption_not_configured(self):
        """Issue #558's actual reporter state: the strategy is ``sensor`` but
        no entity was ever mapped. That was reported SKIPPED/OK, so the
        dashboard sat on "Initializing" forever with a green health check."""
        collector = _make_collector(
            _make_controller(estimated_consumption_configured=False)
        )
        result = collector.check_prediction_health("sensor")
        assert result["status"] == "ERROR"

    def test_component_is_required_under_sensor_strategy(self):
        """``required`` is what promotes an ERROR to a critical sensor failure
        in BatterySystemManager._run_health_check."""
        collector = _make_collector()
        result = collector.check_prediction_health("sensor")
        assert result["required"] is True

    def test_solar_forecast_failure_is_only_a_warning_under_sensor_strategy(self):
        """Requiring the consumption sensor must not drag the genuinely
        optional solar forecast up to required with it."""
        collector = _make_collector(_make_controller(solar_forecast_ok=False))
        result = collector.check_prediction_health("sensor")
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
    def test_component_is_not_required(self):
        """Only the sensor strategy makes this component required."""
        collector = _make_collector()
        result = collector.check_prediction_health("fixed")
        assert result["required"] is False

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
# check_prediction_health — load_power_7d_avg strategy
# ---------------------------------------------------------------------------


class TestLoadPower7dAvgStrategy:
    def test_ok_without_consumption_sensor(self):
        controller = _make_controller(estimated_consumption_ok=False)
        collector = _make_collector(controller)
        result = collector.check_prediction_health("load_power_7d_avg")
        assert result["status"] == "OK"

    def test_does_not_check_estimated_consumption(self):
        collector = _make_collector()
        result = collector.check_prediction_health("load_power_7d_avg")
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
        "strategy", ["sensor", "fixed", "load_power_7d_avg", "ha_statistics"]
    )
    def test_solar_forecast_included_for_all_strategies(self, strategy):
        collector = _make_collector()
        result = collector.check_prediction_health(strategy)
        method_names = [c["method_name"] for c in result["checks"]]
        assert "get_solar_forecast" in method_names

    @pytest.mark.parametrize(
        "strategy", ["sensor", "fixed", "load_power_7d_avg", "ha_statistics"]
    )
    def test_warning_when_solar_forecast_unavailable(self, strategy):
        controller = _make_controller(solar_forecast_ok=False)
        collector = _make_collector(controller)
        result = collector.check_prediction_health(strategy)
        assert result["status"] == "WARNING"


# ---------------------------------------------------------------------------
# check_health passes strategy through to prediction check
# ---------------------------------------------------------------------------


class TestCriticalFailurePromotion:
    """The end the reporter actually experienced (#558): the unmapped sensor
    has to reach ``get_critical_sensor_failures()``, which is what the
    dashboard renders as a degraded-system banner. Anything short of that is
    an endless "Initializing" spinner over a health check claiming OK.
    """

    def _system(self, mock_controller):
        return BatterySystemManager(
            controller=mock_controller,
            price_source=MockSource([1.0] * 96),
            addon_options={"inverter": {"platform": "growatt_server_min"}},
        )

    def test_unconfigured_sensor_becomes_a_critical_failure(self, mock_controller):
        collector = _make_collector(
            _make_controller(estimated_consumption_configured=False)
        )
        prediction = collector.check_prediction_health("sensor")
        system = self._system(mock_controller)

        with patch(
            "core.bess.battery_system_manager.run_system_health_checks",
            return_value={"status": "ERROR", "checks": [prediction]},
        ):
            system._run_health_check()

        assert system.get_critical_sensor_failures() == ["Energy Prediction"]

    def test_unconfigured_sensor_is_not_critical_under_ha_statistics(
        self, mock_controller
    ):
        collector = _make_collector(
            _make_controller(estimated_consumption_configured=False)
        )
        prediction = collector.check_prediction_health("ha_statistics")
        system = self._system(mock_controller)

        with patch(
            "core.bess.battery_system_manager.run_system_health_checks",
            return_value={"status": "OK", "checks": [prediction]},
        ):
            system._run_health_check()

        assert system.get_critical_sensor_failures() == []


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


class TestConsumptionOverlay:
    """The overlay (#428) is checked whenever configured, on any strategy.

    It is not a strategy, so it cannot be keyed off one — and it must not
    produce a warning on the overwhelming majority of installs that never
    configure it.
    """

    def test_omitted_when_no_overlay_entity_is_configured(self) -> None:
        collector = _make_collector(_make_controller(overlay_configured=False))
        result = collector.check_prediction_health("ha_statistics")
        method_names = [ch["method_name"] for ch in result["checks"]]
        assert "get_consumption_overlay_blocks" not in method_names

    def test_checked_when_an_overlay_entity_is_configured(self) -> None:
        collector = _make_collector(_make_controller(overlay_configured=True))
        result = collector.check_prediction_health("ha_statistics")
        method_names = [ch["method_name"] for ch in result["checks"]]
        assert "get_consumption_overlay_blocks" in method_names

    def test_an_overlay_with_no_blocks_today_is_healthy(self) -> None:
        """No blocks declared is the normal steady state, not a fault.

        The documented template emits an empty list whenever none of the
        user's input_booleans are on — most days. An empty list must not read
        as "sensor returned nothing useful" the way an empty solar forecast
        does.
        """
        collector = _make_collector(_make_controller(overlay_configured=True))
        result = collector.check_prediction_health("ha_statistics")
        assert result["status"] == "OK"

    def test_a_broken_overlay_makes_the_check_fail(self) -> None:
        """Configured-but-broken is an error, not something to skip past.

        Every optimization run reads the overlay once configured, so a
        malformed one stops schedules being built. The health check is where
        the user finds out why.
        """
        collector = _make_collector(
            _make_controller(overlay_configured=True, overlay_ok=False)
        )
        result = collector.check_prediction_health("ha_statistics")
        assert result["status"] == "ERROR"
