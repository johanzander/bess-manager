"""Tests for the ha_consumption_series strategy's integration into
BatterySystemManager: dispatch, no-silent-fallback, and horizon extension.

The extension case matters because the DP horizon can exceed 96 periods
(spanning into tomorrow). Every other strategy extends by repeating today's
uniform pattern — fine for a flat forecast, wrong for a real time series.
This strategy must extend using the entity's own `raw_tomorrow` data
instead, mirroring how solar already fetches tomorrow's real forecast.
"""

from unittest.mock import MagicMock

import pytest

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.exceptions import ConsumptionForecastUnavailableError
from core.bess.runtime_failure_tracker import RuntimeFailureTracker
from core.bess.settings import BatterySettings, HomeSettings


def _make_manager(controller, strategy: str) -> BatterySystemManager:
    home_settings = HomeSettings()
    home_settings.consumption_strategy = strategy
    manager = BatterySystemManager.__new__(BatterySystemManager)
    manager._controller = controller
    manager.home_settings = home_settings
    manager.battery_settings = BatterySettings()
    manager._runtime_failure_tracker = RuntimeFailureTracker()
    return manager


class TestDispatch:
    def test_dispatches_to_controller_series_method(self):
        controller = MagicMock()
        controller.get_consumption_forecast_series.return_value = [1.0] * 96
        manager = _make_manager(controller, "ha_consumption_series")

        result = manager._get_consumption_forecast()

        assert result == [1.0] * 96
        controller.get_consumption_forecast_series.assert_called_once()

    def test_does_not_silently_fall_back_on_failure(self):
        controller = MagicMock()
        controller.get_consumption_forecast_series.side_effect = (
            ConsumptionForecastUnavailableError("entity stale")
        )
        manager = _make_manager(controller, "ha_consumption_series")

        with pytest.raises(ConsumptionForecastUnavailableError):
            manager._get_consumption_forecast()


class TestHorizonExtension:
    def test_extends_using_tomorrow_series_not_repeated_today(self):
        controller = MagicMock()
        manager = _make_manager(controller, "ha_consumption_series")
        today_values = [1.0] * 96
        tomorrow_values = [9.0] * 96
        controller.get_consumption_forecast_series_tomorrow.return_value = (
            tomorrow_values
        )

        extended = manager._extend_consumption_predictions(today_values, 118)

        assert len(extended) == 118
        assert extended[:96] == today_values
        # The extra periods must come from tomorrow's real forecast (9.0),
        # not a repeat of today's uniform pattern (1.0).
        assert extended[96] == 9.0

    def test_other_strategies_still_repeat_today(self):
        controller = MagicMock()
        manager = _make_manager(controller, "ha_statistics")
        today_values = [1.0] * 96

        extended = manager._extend_consumption_predictions(today_values, 118)

        assert len(extended) == 118
        assert extended[96] == 1.0
        controller.get_consumption_forecast_series_tomorrow.assert_not_called()

    def test_no_extension_needed_returns_unchanged(self):
        controller = MagicMock()
        manager = _make_manager(controller, "ha_consumption_series")
        today_values = [1.0] * 96

        extended = manager._extend_consumption_predictions(today_values, 96)

        assert extended == today_values
        controller.get_consumption_forecast_series_tomorrow.assert_not_called()
