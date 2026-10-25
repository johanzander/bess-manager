"""Two-day horizon on DST transition days (issue #832).

The horizon used to be capped at a literal 192 periods, which drops the end of
tomorrow whenever today + tomorrow is longer than two normal days. Every test
pins the date: the real clock must never decide which DST case runs.
"""

from datetime import date, datetime
from typing import Any
from unittest.mock import patch

import pytest

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.price_manager import MockSource
from core.bess.tests.conftest import MockHomeAssistantController
from core.bess.tests.helpers import pinned_datetime_class
from core.bess.time_utils import TIMEZONE, get_period_count


class DSTAwareMockSource(MockSource):
    """Returns exactly the day's real period count (92 / 96 / 100)."""

    def get_prices_for_date(self, target_date: date) -> list:
        return self.test_prices[: get_period_count(target_date)]


def _pin(y: int, m: int, d: int, hour: int = 17) -> Any:
    # Pin the whole of time_utils' clock, not just now(): the period-index
    # helpers read the date themselves and must agree with the pinned day.
    return patch(
        "core.bess.time_utils.datetime",
        new=pinned_datetime_class(datetime(y, m, d, hour, 53, tzinfo=TIMEZONE)),
    )


def _system() -> BatterySystemManager:
    system = BatterySystemManager(
        controller=MockHomeAssistantController(),
        price_source=DSTAwareMockSource([0.5] * 100),
        addon_options={"inverter": {"platform": "growatt_server_min"}},
    )
    system._price_manager.refresh_cache()
    return system


# (pinned today, today periods, tomorrow periods)
CASES = [
    pytest.param((2026, 10, 24), 96, 100, id="today96_tomorrow100_fall_back"),
    pytest.param((2026, 10, 25), 100, 96, id="today100_fall_back_tomorrow96"),
    pytest.param((2026, 3, 28), 96, 92, id="today96_tomorrow92_spring_forward"),
    pytest.param((2026, 3, 29), 92, 96, id="today92_spring_forward_tomorrow96"),
    pytest.param((2026, 11, 15), 96, 96, id="normal_days"),
]


@pytest.mark.parametrize("day,today_n,tomorrow_n", CASES)
def test_horizon_keeps_all_of_both_days(
    day: tuple[int, int, int], today_n: int, tomorrow_n: int
) -> None:
    with _pin(*day):
        assert get_period_count(time_utils.today()) == today_n
        system = _system()

        prices, entries = system._get_price_data(prepare_next_day=False)

        assert prices is not None and entries is not None
        assert len(prices) == len(entries) == today_n + tomorrow_n


@pytest.mark.parametrize("day,today_n,tomorrow_n", CASES)
def test_every_horizon_array_lines_up(
    day: tuple[int, int, int], today_n: int, tomorrow_n: int
) -> None:
    """Prices, consumption, solar and the optimizer's output all span the horizon."""
    with _pin(*day):
        system = _system()
        prices, entries = system._get_price_data(prepare_next_day=False)
        assert prices is not None and entries is not None
        horizon = today_n + tomorrow_n

        result = system._gather_optimization_data(
            period=71,
            current_soc=50.0,
            prepare_next_day=False,
            period_count=len(prices),
        )
        assert result is not None
        opt_period, data = result
        assert len(data["full_consumption"]) == horizon
        assert len(data["full_solar"]) == horizon

        optimization = system._run_optimization(
            opt_period, data, prices, entries, False
        )
        assert optimization is not None
        assert len(optimization.period_data) == horizon - opt_period


def test_fall_back_tomorrow_plan_reaches_the_last_period() -> None:
    """96 + 100: the plan covers tomorrow's final quarter, not just up to 23:00."""
    with _pin(2026, 10, 24):
        system = _system()
        prices, entries = system._get_price_data(prepare_next_day=False)
        assert prices is not None and entries is not None

        result = system._gather_optimization_data(
            period=71,
            current_soc=50.0,
            prepare_next_day=False,
            period_count=len(prices),
        )
        assert result is not None
        opt_period, data = result
        optimization = system._run_optimization(
            opt_period, data, prices, entries, False
        )

        assert optimization is not None
        last = optimization.period_data[-1]
        assert last.timestamp is not None
        assert last.timestamp.date().isoformat() == "2026-10-25"
        assert (last.timestamp.hour, last.timestamp.minute) == (23, 45)


def test_fall_back_tomorrow_consumption_is_not_padded_with_a_flat_default() -> None:
    """96 + 100: periods past the doubled 96-value profile must come from the profile."""
    with _pin(2026, 10, 24):
        system = _system()
        controller = system.controller
        assert isinstance(controller, MockHomeAssistantController)
        controller.consumption_forecast = [0.25] * 96
        system.home_settings.consumption_strategy = "sensor"
        prices, _ = system._get_price_data(prepare_next_day=False)
        assert prices is not None

        result = system._gather_optimization_data(
            period=71,
            current_soc=50.0,
            prepare_next_day=False,
            period_count=len(prices),
        )
        assert result is not None
        _, data = result
        assert data["full_consumption"][192:196] == [0.25] * 4


def test_terminal_cap_spans_all_of_a_fall_back_tomorrow() -> None:
    """96 + 100: the terminal day's sell prices are tomorrow's 100 periods.

    Price entries are labelled by naive wall clock, so tomorrow's last four
    labels roll over to 26 Oct; picking the terminal day by label would hand
    the terminal cap those four night-time prices instead of the whole day.
    """
    with _pin(2026, 10, 24):
        system = _system()
        prices, entries = system._get_price_data(prepare_next_day=False)
        assert prices is not None and entries is not None
        result = system._gather_optimization_data(
            period=71,
            current_soc=50.0,
            prepare_next_day=False,
            period_count=len(prices),
        )
        assert result is not None
        opt_period, data = result

        with patch.object(
            system, "_calculate_terminal_curve", return_value=None
        ) as curve:
            system._run_optimization(opt_period, data, prices, entries, False)

        cap_sell_prices = curve.call_args.args[1]
        assert len(cap_sell_prices) == 100
