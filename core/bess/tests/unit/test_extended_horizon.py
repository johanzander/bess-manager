"""Tests for extended DP optimization horizon with tomorrow's price data."""

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.exceptions import PriceDataUnavailableError
from core.bess.price_manager import MockSource
from core.bess.settings import BatterySettings
from core.bess.tests.conftest import MockHomeAssistantController, MockSensorCollector
from core.bess.time_utils import get_period_count

pytestmark = pytest.mark.slow


class TodayOnlyMockSource(MockSource):
    """Mock source that only returns prices for today, raises for tomorrow."""

    def get_prices_for_date(self, target_date: date) -> list:
        if target_date > time_utils.today():
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
    system = BatterySystemManager(
        controller=controller,
        price_source=price_source,
        addon_options={"inverter": {"platform": "growatt_server_min"}},
    )
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

        expected = get_period_count(time_utils.today())
        assert prices is not None
        assert _price_entries is not None
        assert len(prices) == expected
        assert len(_price_entries) == expected

    def test_prepare_next_day_unaffected(self, quarterly_prices_24h):
        """prepare_next_day=True flow is completely unaffected by extended horizon."""
        source = DSTAwareMockSource(quarterly_prices_24h)
        system = _make_system(source)

        prices, _price_entries = system._get_price_data(prepare_next_day=True)

        tomorrow = time_utils.today() + timedelta(days=1)
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

    def test_prepare_next_day_uses_tomorrow_solar_forecast(self):
        """prepare_next_day must build the schedule from TOMORROW's solar forecast.

        Regression: the next-day schedule was built with today's solar forecast,
        which under-/over-forecasts tomorrow's production and distorts the plan.
        """
        controller = MockHomeAssistantController()
        controller.solar_forecast = [1.0] * 96  # today
        controller.solar_forecast_tomorrow = [2.0] * 96  # tomorrow
        source = MockSource([0.5] * 96)
        system = _make_system(source, controller)

        result = system._gather_optimization_data(
            period=0, current_soc=50.0, prepare_next_day=True, period_count=96
        )

        assert result is not None
        _, data = result
        assert len(data["full_solar"]) == 96
        # Solar must come from the tomorrow forecast, not today's
        assert all(v == 2.0 for v in data["full_solar"])

    def test_prepare_next_day_starts_from_real_soc(self):
        """Next-day plan must seed initial SOE from the real current SOC.

        Regression: the prepare_next_day run (cron at 23:55, when current SOC is
        known and ~= tomorrow's starting SOC) discarded current_soc and assumed
        min SOC, so any night the battery wasn't actually empty the next-day plan
        started from a wrong state.
        """
        controller = MockHomeAssistantController()
        source = MockSource([0.5] * 96)
        system = _make_system(source, controller)

        result = system._gather_optimization_data(
            period=0, current_soc=50.0, prepare_next_day=True, period_count=96
        )

        assert result is not None
        _, data = result
        expected_soe = 50.0 / 100.0 * system.battery_settings.total_capacity
        # Must reflect real SOC, not min_soe_kwh
        assert expected_soe != system.battery_settings.min_soe_kwh
        assert data["combined_soe"][0] == expected_soe

    def test_prepare_next_day_solar_falls_back_to_zeros_on_error(self):
        """If tomorrow's solar forecast is unavailable, next-day uses zeros."""
        from core.bess.exceptions import SystemConfigurationError

        controller = MockHomeAssistantController()
        controller.solar_forecast = [1.0] * 96
        source = MockSource([0.5] * 96)
        system = _make_system(source, controller)

        with patch.object(
            controller,
            "get_solar_forecast_tomorrow",
            side_effect=SystemConfigurationError("Not configured"),
        ):
            result = system._gather_optimization_data(
                period=0, current_soc=50.0, prepare_next_day=True, period_count=96
            )

        assert result is not None
        _, data = result
        assert len(data["full_solar"]) == 96
        assert all(v == 0.0 for v in data["full_solar"])


class TestCalculateTerminalValue:
    """Test _calculate_terminal_value() method."""

    def test_nonzero_when_horizon_extends_past_today(self):
        """Terminal value should still apply the median/cap formula when the
        horizon extends past today (#345) — the caller already truncates
        buy_prices/sell_prices to the current optimization window, so there
        is no reason to zero out the estimate just because that window
        happens to cross midnight-today.
        """
        source = MockSource([1.0] * 96)
        system = _make_system(source)

        # 192 buy prices remaining (extends past today's ~96 remaining periods
        # from period 0) — should use the same median/cap formula as the
        # today-only case, not return 0.0. Sell prices vary so the cap branch
        # applies (it is skipped on a fixed export tariff, #359).
        sell_prices = [0.6, 0.8] * 96
        terminal_value = system._calculate_terminal_value(
            buy_prices=[1.0] * 192, sell_prices=sell_prices, optimization_period=0
        )

        median_price = 1.0
        max_sell_price = 0.8
        buy_based = max(
            0.0,
            median_price * system.battery_settings.efficiency_discharge
            - system.battery_settings.cycle_cost_per_kwh,
        )
        sell_cap = max(
            0.0,
            max_sell_price * system.battery_settings.efficiency_discharge
            - system.battery_settings.cycle_cost_per_kwh,
        )
        expected = min(buy_based, sell_cap)

        assert terminal_value == pytest.approx(expected)
        assert terminal_value > 0.0

    def test_positive_when_today_only(self):
        """Terminal value should be positive when only today's data is available."""
        source = MockSource([1.0] * 96)
        system = _make_system(source)

        # Only 50 remaining prices (clearly today-only), sell prices high enough
        # that the arbitrage cap doesn't bind.
        terminal_value = system._calculate_terminal_value(
            buy_prices=[1.0] * 50, sell_prices=[1.0] * 50, optimization_period=46
        )

        # Should be median_buy * efficiency_discharge - cycle_cost > 0
        assert terminal_value > 0.0

    def test_floored_at_zero(self):
        """Terminal value should never be negative."""
        source = MockSource([0.1] * 96)
        system = _make_system(source)
        # Very low prices + high cycle cost should floor at 0.0
        system.battery_settings.cycle_cost_per_kwh = 5.0

        terminal_value = system._calculate_terminal_value(
            buy_prices=[0.01] * 10, sell_prices=[0.01] * 10, optimization_period=86
        )

        assert terminal_value == 0.0

    def test_capped_by_sell_price_on_wide_spread(self):
        """Belgian-shaped case (#126/#244): wide buy/sell spread must cap the
        buy-median terminal value at the best achievable in-horizon export,
        so the DP doesn't hold charge to chase a fictitious bonus."""
        source = MockSource([0.3] * 96)
        system = _make_system(source)
        system.battery_settings.cycle_cost_per_kwh = 0.05

        buy_prices = [0.21, 0.24, 0.30, 0.35, 0.38]  # median = 0.30
        sell_prices = [0.10, 0.12, 0.13, 0.15, 0.16]  # max = 0.16

        terminal_value = system._calculate_terminal_value(
            buy_prices=buy_prices, sell_prices=sell_prices, optimization_period=91
        )

        eff = system.battery_settings.efficiency_discharge
        buy_based = 0.30 * eff - 0.05
        sell_cap = 0.16 * eff - 0.05
        assert sell_cap < buy_based, "test fixture must exercise the binding cap"
        assert terminal_value == pytest.approx(sell_cap)

    def test_uses_buy_based_when_cap_does_not_bind(self):
        """Ordinary/Nordic-shaped case: a narrow evening peak sits well above
        the buy-median estimate, so the cap must not bind and today's
        reserve-holding behavior is preserved (the gap #245 left untested)."""
        source = MockSource([0.6] * 96)
        system = _make_system(source)
        system.battery_settings.cycle_cost_per_kwh = 0.05

        buy_prices = [0.6, 0.6, 0.6, 1.4, 1.4]  # median = 0.6
        sell_prices = [p * 0.85 for p in buy_prices]  # max = 1.19

        terminal_value = system._calculate_terminal_value(
            buy_prices=buy_prices, sell_prices=sell_prices, optimization_period=91
        )

        eff = system.battery_settings.efficiency_discharge
        buy_based = 0.6 * eff - 0.05
        sell_cap = max(sell_prices) * eff - 0.05
        assert buy_based < sell_cap, "test fixture must exercise the non-binding cap"
        assert terminal_value == pytest.approx(buy_based)

    def test_cap_skipped_on_fixed_export_tariff(self):
        """Fixed export tariff (#359): the arbitrage-consistency cap bounds
        terminal value by an in-horizon export opportunity the DP would forgo
        by holding charge. A flat sell curve offers no such opportunity, and
        applying the cap there drives terminal value below the round-trip
        breakeven for storing surplus solar, so the buy-based estimate must
        stand."""
        source = MockSource([0.22] * 96)
        system = _make_system(source)
        system.battery_settings.cycle_cost_per_kwh = 0.02

        buy_prices = [0.20, 0.22, 0.24, 0.34, 0.40]  # median = 0.24
        sell_prices = [0.12] * 5  # fixed export tariff (e.g. Octopus Outgoing)

        terminal_value = system._calculate_terminal_value(
            buy_prices=buy_prices, sell_prices=sell_prices, optimization_period=29
        )

        eff_discharge = system.battery_settings.efficiency_discharge
        eff_charge = system.battery_settings.efficiency_charge
        buy_based = 0.24 * eff_discharge - 0.02
        sell_cap = 0.12 * eff_discharge - 0.02
        assert sell_cap < 0.12 / eff_charge, (
            "test fixture must exercise the degenerate case: on a flat sell "
            "curve the cap sits below the round-trip breakeven, so applying "
            "it makes storing surplus solar impossible at any future price"
        )
        assert terminal_value == pytest.approx(buy_based)

    def test_extended_horizon_schedule_retains_charge_for_terminal_value(self):
        """End-to-end regression for #345: with the old zeroed terminal value,
        the DP had no reason to hold charge through the end of an extended
        horizon and drained to the floor after its last profitable sale; with
        the fixed (nonzero, median/cap) terminal value, it recharges and
        holds through the horizon's end instead. This exercises the real
        DP (`optimize_battery_schedule`), not just the isolated
        `_calculate_terminal_value` formula the other tests in this class
        cover -- a regression to the old zeroing behavior would make this
        test's two runs produce identical (drained) end-of-horizon SOE.
        """
        source = MockSource([1.0] * 96)
        system = _make_system(source)
        # A fresh instance (not mutated fields) so derived min/max_soe_kwh --
        # computed once in __post_init__ -- stay consistent with these values.
        system.battery_settings = BatterySettings(
            total_capacity=10.0,
            min_soc=10.0,
            max_soc=100.0,
            max_charge_power_kw=10.0,
            max_discharge_power_kw=10.0,
            efficiency_charge=0.9,
            efficiency_discharge=0.9,
            cycle_cost_per_kwh=0.1,
        )

        # A great mid-horizon sell price (period 3) the DP should exploit
        # regardless of terminal value, followed by a weak tail (periods 6-7)
        # that's only worth holding through if the horizon's terminal value
        # is a genuine positive estimate -- not zero.
        prices = [1.0, 1.0, 1.0, 3.0, 1.0, 1.0, 0.3, 0.3]
        home_consumption = [0.0] * 8
        solar_production = [0.0] * 8

        # The production formula's actual value for this price window --
        # not a hand-copied constant, so this stays coupled to
        # `_calculate_terminal_value` itself.
        terminal_value = system._calculate_terminal_value(
            buy_prices=prices, sell_prices=prices, optimization_period=0
        )
        assert terminal_value > 0.0

        def final_soe(terminal_value_per_kwh: float) -> float:
            result = optimize_battery_schedule(
                buy_price=prices,
                sell_price=prices,
                home_consumption=home_consumption,
                solar_production=solar_production,
                initial_soe=10.0,
                battery_settings=system.battery_settings,
                period_duration_hours=1.0,
                terminal_value_per_kwh=terminal_value_per_kwh,
            )
            return result.period_data[-1].energy.battery_soe_end

        zeroed_final_soe = final_soe(0.0)  # pre-#345 behavior
        fixed_final_soe = final_soe(terminal_value)  # current behavior

        assert zeroed_final_soe == pytest.approx(1.0)
        assert fixed_final_soe == pytest.approx(10.0)
        assert fixed_final_soe > zeroed_final_soe


class TestPrepareNextDayTimestamps:
    """Timestamps in the next-day schedule must land on tomorrow's date (issue #155)."""

    def test_prepare_next_day_timestamps_are_tomorrows_date(self):
        """Optimize with prepare_next_day=True and verify every period timestamp is tomorrow."""
        controller = MockHomeAssistantController()
        source = DSTAwareMockSource([0.5] * 100)
        system = _make_system(source, controller)

        tomorrow = time_utils.today() + timedelta(days=1)

        prices, price_entries = system._get_price_data(prepare_next_day=True)
        assert prices is not None
        assert price_entries is not None

        result_data = system._gather_optimization_data(
            period=0, current_soc=50.0, prepare_next_day=True, period_count=len(prices)
        )
        assert result_data is not None
        optimization_period, optimization_data = result_data

        result = system._run_optimization(
            optimization_period, optimization_data, prices, price_entries, True
        )
        assert result is not None

        for pd in result.period_data:
            assert pd.timestamp is not None
            assert (
                pd.timestamp.date() == tomorrow
            ), f"Period {pd.period} has timestamp on {pd.timestamp.date()}, expected {tomorrow}"

    def test_regular_hourly_timestamps_are_todays_date(self):
        """Optimize without prepare_next_day and verify timestamps stay on today."""
        controller = MockHomeAssistantController()
        source = DSTAwareMockSource([0.5] * 100)
        system = _make_system(source, controller)

        today = time_utils.today()

        prices, price_entries = system._get_price_data(prepare_next_day=False)
        assert prices is not None
        assert price_entries is not None

        # Use today-only prices so all periods are within today
        today_count = get_period_count(today)
        prices_today = prices[:today_count]
        entries_today = price_entries[:today_count]

        result_data = system._gather_optimization_data(
            period=0, current_soc=50.0, prepare_next_day=False, period_count=today_count
        )
        assert result_data is not None
        optimization_period, optimization_data = result_data

        result = system._run_optimization(
            optimization_period, optimization_data, prices_today, entries_today, False
        )
        assert result is not None

        for pd in result.period_data:
            assert pd.timestamp is not None
            assert (
                pd.timestamp.date() == today
            ), f"Period {pd.period} has timestamp on {pd.timestamp.date()}, expected {today}"


class TestUnifiedSolarPath:
    """Verify the unified solar-sourcing path eliminates duplication (issue #157)."""

    def test_prepare_next_day_and_extended_horizon_share_solar_helper(self):
        """Both prepare_next_day and extended horizon must use the same tomorrow-solar helper.

        If the tomorrow solar forecast raises, both paths must fall back to zeros
        through the shared _fetch_tomorrow_solar_forecast helper.
        """
        from core.bess.exceptions import SystemConfigurationError

        controller = MockHomeAssistantController()
        controller.solar_forecast = [1.0] * 96
        controller.solar_forecast_tomorrow = [2.0] * 96
        source = DSTAwareMockSource([0.5] * 100)
        system = _make_system(source, controller)

        with patch.object(
            controller,
            "get_solar_forecast_tomorrow",
            side_effect=SystemConfigurationError("Forecast unavailable"),
        ):
            # prepare_next_day path: must fall back to zeros
            result_nd = system._gather_optimization_data(
                period=0, current_soc=50.0, prepare_next_day=True, period_count=96
            )
            # extended-horizon path: tomorrow extension must also fall back to zeros
            result_ext = system._gather_optimization_data(
                period=0, current_soc=50.0, prepare_next_day=False, period_count=192
            )

        assert result_nd is not None
        assert result_ext is not None

        _, data_nd = result_nd
        _, data_ext = result_ext

        # next-day: all solar is zeros (tomorrow not available)
        assert all(v == 0.0 for v in data_nd["full_solar"])
        # extended: today's solar (1.0) is intact, tomorrow extension is zeros
        assert all(v == 1.0 for v in data_ext["full_solar"][:96])
        assert all(v == 0.0 for v in data_ext["full_solar"][96:])


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
        today_count = get_period_count(time_utils.today())
        assert len(dp_schedule.actions) <= today_count
        assert len(dp_schedule.state_of_energy) <= today_count
        assert len(dp_schedule.prices) <= today_count
        assert len(dp_schedule.strategic_intents) <= today_count
