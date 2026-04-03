"""Tests for extended DP optimization horizon with tomorrow's price data."""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.exceptions import PriceDataUnavailableError
from core.bess.price_manager import MockSource
from core.bess.tests.conftest import MockHomeAssistantController, MockSensorCollector
from core.bess.time_utils import get_period_count


class TodayOnlyMockSource(MockSource):
    """Mock source that only returns prices for today, raises for tomorrow."""

    def get_prices_for_date(self, target_date: date) -> list:
        if target_date > datetime.now().date():
            raise PriceDataUnavailableError(
                message="Tomorrow's prices not yet available"
            )
        return self.test_prices[: get_period_count(target_date)]


class DSTAwareMockSource(MockSource):
    """Mock source that returns the correct period count per date (DST-aware)."""

    def get_prices_for_date(self, target_date: date) -> list:
        return self.test_prices[: get_period_count(target_date)]


def _make_system(
    price_source: MockSource,
    controller: MockHomeAssistantController | None = None,
) -> BatterySystemManager:
    """Create a BatterySystemManager with mocked dependencies."""
    if controller is None:
        controller = MockHomeAssistantController()
    system = BatterySystemManager(controller=controller, price_source=price_source)
    return system


@pytest.fixture
def quarterly_prices_24h():
    """Up to 100 quarterly prices with clear day/evening split.

    Sized for the longest possible day (DST fall-back = 100 periods).
    Tests should use DSTAwareMockSource to trim to the actual day length.
    """
    # Moderate day prices (0.8), low evening (0.2)
    return [0.8] * 68 + [0.2] * 32


@pytest.fixture
def quarterly_prices_tomorrow():
    """Up to 100 quarterly prices for tomorrow - morning peak."""
    return [0.3] * 34 + [1.5] * 32 + [0.5] * 34


class TestGetPriceDataExtended:
    """Test _get_price_data() with extended horizon."""

    def test_extends_with_tomorrow_when_available(self, quarterly_prices_24h):
        """When tomorrow's prices are available, _get_price_data returns up to 192 entries."""
        source = MockSource(quarterly_prices_24h)
        system = _make_system(source)

        prices, _price_entries = system._get_price_data(prepare_next_day=False)

        assert prices is not None
        assert _price_entries is not None
        # MockSource returns same prices for any date, so today + tomorrow = 192
        assert len(prices) == 192
        assert len(_price_entries) == 192

    def test_graceful_fallback_when_tomorrow_unavailable(self, quarterly_prices_24h):
        """When tomorrow's prices aren't available, returns only today's entries."""
        source = TodayOnlyMockSource(quarterly_prices_24h)
        system = _make_system(source)

        prices, _price_entries = system._get_price_data(prepare_next_day=False)

        expected = get_period_count(datetime.now().date())
        assert prices is not None
        assert _price_entries is not None
        assert len(prices) == expected
        assert len(_price_entries) == expected

    def test_prepare_next_day_unaffected(self, quarterly_prices_24h):
        """prepare_next_day=True flow is completely unaffected by extended horizon."""
        source = DSTAwareMockSource(quarterly_prices_24h)
        system = _make_system(source)

        prices, _price_entries = system._get_price_data(prepare_next_day=True)

        tomorrow = datetime.now().date() + timedelta(days=1)
        expected = get_period_count(tomorrow)
        assert prices is not None
        # prepare_next_day fetches only tomorrow's prices, no extension
        assert len(prices) == expected

    def test_192_period_cap_enforced(self):
        """Even with very long price arrays, cap at 192 periods."""
        # 150 prices per day = 300 total would exceed cap
        source = MockSource([1.0] * 150)
        system = _make_system(source)

        prices, _price_entries = system._get_price_data(prepare_next_day=False)

        assert prices is not None
        assert len(prices) <= 192


class TestGatherOptimizationDataExtended:
    """Test _gather_optimization_data() with extended period counts."""

    def test_extends_consumption_for_192_periods(self):
        """Consumption predictions should extend to cover 192-period horizon."""
        controller = MockHomeAssistantController()
        controller.consumption_forecast = [1.0] * 96
        source = MockSource([0.5] * 96)
        system = _make_system(source, controller)

        result = system._gather_optimization_data(
            period=0, current_soc=50.0, prepare_next_day=False, period_count=192
        )

        assert result is not None
        _optimization_period, data = result
        assert len(data["full_consumption"]) == 192
        # Tomorrow's consumption should be a copy of today's
        assert data["full_consumption"][96:] == data["full_consumption"][:96]

    def test_extends_solar_with_tomorrow_forecast(self):
        """Solar predictions should use tomorrow's forecast for extended horizon."""
        controller = MockHomeAssistantController()
        controller.solar_forecast = [1.0] * 96
        controller.solar_forecast_tomorrow = [2.0] * 96
        source = MockSource([0.5] * 96)
        system = _make_system(source, controller)

        result = system._gather_optimization_data(
            period=0, current_soc=50.0, prepare_next_day=False, period_count=192
        )

        assert result is not None
        _, data = result
        assert len(data["full_solar"]) == 192
        # Tomorrow's solar should come from the tomorrow forecast
        assert data["full_solar"][96] == 2.0

    def test_solar_falls_back_to_zeros_on_error(self):
        """If tomorrow's solar forecast fails, fall back to zeros."""
        controller = MockHomeAssistantController()
        controller.solar_forecast = [1.0] * 96
        source = MockSource([0.5] * 96)
        system = _make_system(source, controller)

        # Patch get_solar_forecast_tomorrow to raise
        from core.bess.exceptions import SystemConfigurationError

        with patch.object(
            controller,
            "get_solar_forecast_tomorrow",
            side_effect=SystemConfigurationError("Not configured"),
        ):
            result = system._gather_optimization_data(
                period=0, current_soc=50.0, prepare_next_day=False, period_count=192
            )

        assert result is not None
        _, data = result
        assert len(data["full_solar"]) == 192
        # Tomorrow's solar should be zeros (fallback)
        assert all(v == 0.0 for v in data["full_solar"][96:])

    def test_96_periods_unchanged(self):
        """Standard 96-period case should work exactly as before."""
        controller = MockHomeAssistantController()
        source = MockSource([0.5] * 96)
        system = _make_system(source, controller)

        result = system._gather_optimization_data(
            period=0, current_soc=50.0, prepare_next_day=False, period_count=96
        )

        assert result is not None
        _, data = result
        assert len(data["full_consumption"]) == 96
        assert len(data["full_solar"]) == 96

    def test_prepare_next_day_unaffected(self):
        """prepare_next_day path should not be affected by extended horizon changes."""
        controller = MockHomeAssistantController()
        source = MockSource([0.5] * 96)
        system = _make_system(source, controller)

        result = system._gather_optimization_data(
            period=0, current_soc=50.0, prepare_next_day=True, period_count=96
        )

        assert result is not None
        _, data = result
        assert len(data["full_consumption"]) == 96


class TestCalculateTerminalValue:
    """Test _calculate_terminal_value() method."""

    def test_zero_when_horizon_extends_past_today(self):
        """Terminal value should be 0.0 when DP has explicit tomorrow data."""
        source = MockSource([1.0] * 96)
        system = _make_system(source)

        # 192 buy prices remaining but only ~96 today periods remaining from period 0
        terminal_value = system._calculate_terminal_value(
            buy_prices=[1.0] * 192, optimization_period=0
        )

        assert terminal_value == 0.0

    def test_positive_when_today_only(self):
        """Terminal value should be positive when only today's data is available."""
        source = MockSource([1.0] * 96)
        system = _make_system(source)

        # Only 50 remaining prices (clearly today-only)
        terminal_value = system._calculate_terminal_value(
            buy_prices=[1.0] * 50, optimization_period=46
        )

        # Should be avg_buy * efficiency_discharge - cycle_cost > 0
        assert terminal_value > 0.0

    def test_floored_at_zero(self):
        """Terminal value should never be negative."""
        source = MockSource([0.1] * 96)
        system = _make_system(source)
        # Very low prices + high cycle cost should floor at 0.0
        system.battery_settings.cycle_cost_per_kwh = 5.0

        terminal_value = system._calculate_terminal_value(
            buy_prices=[0.01] * 10, optimization_period=86
        )

        assert terminal_value == 0.0


class TestScheduleTruncation:
    """Test that _create_updated_schedule() truncates to today's periods."""

    @patch("core.bess.battery_system_manager.SensorCollector", MockSensorCollector)
    def test_schedule_arrays_truncated_to_today(self, quarterly_prices_24h):
        """DPSchedule arrays should never exceed today's period count."""
        source = DSTAwareMockSource(quarterly_prices_24h)
        controller = MockHomeAssistantController()
        controller.settings["battery_soc"] = 50
        system = _make_system(source, controller)

        # Run full optimization with extended horizon
        prices, _price_entries = system._get_price_data(prepare_next_day=False)

        assert prices is not None
        assert _price_entries is not None

        period_count = len(prices)
        result_data = system._gather_optimization_data(
            period=0,
            current_soc=50.0,
            prepare_next_day=False,
            period_count=period_count,
        )
        assert result_data is not None
        optimization_period, optimization_data = result_data

        result = system._run_optimization(
            optimization_period, optimization_data, prices, _price_entries, False
        )
        assert result is not None

        schedule_result = system._create_updated_schedule(
            optimization_period, result, prices, optimization_data, True, False
        )
        assert schedule_result is not None
        dp_schedule, _growatt_manager = schedule_result

        # Verify all schedule arrays are bounded to today
        from core.bess.time_utils import TIMEZONE

        today_count = get_period_count(datetime.now(tz=TIMEZONE).date())
        assert len(dp_schedule.actions) <= today_count
        assert len(dp_schedule.state_of_energy) <= today_count
        assert len(dp_schedule.prices) <= today_count
        assert len(dp_schedule.strategic_intents) <= today_count
