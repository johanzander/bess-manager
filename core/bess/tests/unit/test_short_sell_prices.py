"""A sell price list shorter than the buy list trims the day instead of failing.

Some import/export tariff combinations project import prices further ahead
than export prices. Octopus Cosy import is a fixed three-band time-of-use
tariff, so the full day is always known, while Agile export is published day
by day and has come back with 46 of 48 half-hours. Indexing the short list raised
IndexError, today's prices were never cached, and the optimizer reported "No
prices available" on every cycle.
"""

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.price_manager import MockSource
from core.bess.tests.conftest import MockHomeAssistantController, MockSensorCollector
from core.bess.time_utils import get_period_count

MISSING = 4  # two half-hours, expanded to quarters
TOMORROW_BUY = 0.55  # marks tomorrow's entries; today never uses it


class ShortSellMockSource(MockSource):
    """Full buy prices, but today's sell prices stop MISSING periods early."""

    def __init__(self) -> None:
        super().__init__([0.8] * 68 + [0.2] * 32)
        self.today_sell_short = True

    @property
    def prices_are_final(self) -> bool:
        return True

    def get_prices_for_date(self, target_date: date) -> list:
        if target_date != time_utils.today():
            return [TOMORROW_BUY] * get_period_count(target_date)
        return self.test_prices[: get_period_count(target_date)]

    def get_sell_prices_for_date(self, target_date: date) -> list[float] | None:
        count = get_period_count(target_date)
        if target_date == time_utils.today() and self.today_sell_short:
            count -= MISSING
        return [0.1] * count


def _make_system(source: MockSource) -> BatterySystemManager:
    controller = MockHomeAssistantController()
    controller.settings["battery_soc"] = 50
    system = BatterySystemManager(
        controller=controller,
        price_source=source,
        addon_options={"inverter": {"platform": "growatt_server_min"}},
    )
    system._price_manager.refresh_cache()
    return system


def test_today_is_trimmed_to_the_sell_prices() -> None:
    system = _make_system(ShortSellMockSource())

    entries = system._price_manager.get_cached_today_prices()

    assert len(entries) == get_period_count(time_utils.today()) - MISSING


def test_short_today_is_not_extended_with_tomorrow() -> None:
    """Tomorrow 00:00 must not be appended onto today's 23:00 slot."""
    system = _make_system(ShortSellMockSource())
    assert system._price_manager.get_cached_tomorrow_prices()

    prices, entries = system._get_price_data(prepare_next_day=False)

    assert prices is not None
    assert entries is not None
    assert len(prices) == get_period_count(time_utils.today()) - MISSING
    assert entries[-1]["timestamp"].startswith(time_utils.today().isoformat())


def test_tomorrow_never_stands_in_for_a_missing_today() -> None:
    """With today uncached, tomorrow's entries must not be read as today's."""
    system = _make_system(ShortSellMockSource())
    pm = system._price_manager
    pm._today_prices = None
    pm._today_date = None
    assert pm.get_cached_tomorrow_prices()

    prices, entries = system._get_price_data(prepare_next_day=False)

    assert prices is None
    assert entries is None


def test_available_prices_not_extended_when_today_short() -> None:
    system = _make_system(ShortSellMockSource())

    buy, sell = system._price_manager.get_available_prices()

    assert len(buy) == len(sell) == get_period_count(time_utils.today()) - MISSING


def test_refresh_fills_in_once_the_sell_prices_arrive() -> None:
    source = ShortSellMockSource()
    system = _make_system(source)

    source.today_sell_short = False
    system._price_manager.refresh_cache()

    entries = system._price_manager.get_cached_today_prices()
    assert len(entries) == get_period_count(time_utils.today())


def test_refresh_keeps_the_short_day_when_the_refetch_fails() -> None:
    source = ShortSellMockSource()
    system = _make_system(source)

    with patch.object(
        source, "get_prices_for_date", side_effect=RuntimeError("source down")
    ):
        system._price_manager.refresh_cache()

    entries = system._price_manager.get_cached_today_prices()
    assert len(entries) == get_period_count(time_utils.today()) - MISSING


@pytest.mark.slow
@patch("core.bess.battery_system_manager.SensorCollector", MockSensorCollector)
def test_schedule_builds_on_a_short_day() -> None:
    system = _make_system(ShortSellMockSource())

    assert system.update_battery_schedule(current_period=40, prepare_next_day=False)
    schedule = system._current_schedule
    assert schedule is not None
    assert TOMORROW_BUY not in schedule.prices


@pytest.mark.slow
@patch("core.bess.battery_system_manager.SensorCollector", MockSensorCollector)
def test_period_past_the_trimmed_end_does_not_crash() -> None:
    """Once the clock passes the last priced period the cycle gives up cleanly."""
    system = _make_system(ShortSellMockSource())
    assert system.update_battery_schedule(current_period=40, prepare_next_day=False)

    last = get_period_count(time_utils.today()) - 1
    system.update_battery_schedule(current_period=last, prepare_next_day=False)


def test_tomorrow_unaffected() -> None:
    system = _make_system(ShortSellMockSource())
    tomorrow = time_utils.today() + timedelta(days=1)

    entries = system._price_manager.get_cached_tomorrow_prices()

    assert len(entries) == get_period_count(tomorrow)
