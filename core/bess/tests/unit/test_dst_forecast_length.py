"""Forecast arrays are as long as the real day on DST days (issue #689).

Pinned dates, never the real clock: 2026-10-25 is the 100-period fall-back day,
2026-03-29 the 92-period spring-forward day, 2026-06-15 a normal 96-period day.
"""

from datetime import date, datetime
from typing import Any
from unittest.mock import patch

import pytest

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.price_manager import MockSource
from core.bess.tests.conftest import MockHomeAssistantController
from core.bess.time_utils import TIMEZONE, expand_wall_clock_profile

FALL_BACK_DAY = date(2026, 10, 25)
SPRING_FORWARD_DAY = date(2026, 3, 29)
NORMAL_DAY = date(2026, 6, 15)

# A profile whose every quarter-hour is distinct, so a one-hour shift shows.
PROFILE = [q / 1000.0 for q in range(96)]


def _system(
    controller: MockHomeAssistantController | None = None,
) -> BatterySystemManager:
    return BatterySystemManager(
        controller=controller or MockHomeAssistantController(),
        price_source=MockSource([0.5] * 100),
        addon_options={"inverter": {"platform": "growatt_server_min"}},
    )


def _clock_at(day: date) -> Any:
    """Pin 'now' to noon on the given day."""
    return patch.object(
        time_utils,
        "now",
        return_value=datetime(day.year, day.month, day.day, 12, tzinfo=TIMEZONE),
    )


# --- expand_wall_clock_profile ------------------------------------------------


@pytest.mark.parametrize(
    "target_date, expected_periods",
    [(NORMAL_DAY, 96), (FALL_BACK_DAY, 100), (SPRING_FORWARD_DAY, 92)],
)
def test_expanded_profile_has_one_entry_per_real_period(
    target_date: date, expected_periods: int
) -> None:
    assert len(expand_wall_clock_profile(PROFILE, target_date)) == expected_periods


def test_expanded_profile_repeats_the_fall_back_hour_without_shifting_the_rest() -> (
    None
):
    """Index 16 is the real 03:00 CET period (00, 01, 02 CEST, 02 CET fill 0-15)."""
    expanded = expand_wall_clock_profile(PROFILE, FALL_BACK_DAY)

    assert expanded[8:12] == PROFILE[8:12]  # 02:00 CEST
    assert expanded[12:16] == PROFILE[8:12]  # 02:00 CET reuses the 02:00 values
    assert expanded[16] == PROFILE[12]  # 03:00 CET reads the 03:00 value
    assert expanded[-1] == PROFILE[95]  # 23:45


def test_expanded_profile_drops_the_skipped_spring_forward_hour() -> None:
    expanded = expand_wall_clock_profile(PROFILE, SPRING_FORWARD_DAY)

    assert expanded[7] == PROFILE[7]  # 01:45
    assert expanded[8] == PROFILE[12]  # 03:00 CEST, the 02:xx profile is skipped
    assert expanded[-1] == PROFILE[95]


def test_a_profile_that_is_not_a_day_is_rejected() -> None:
    with pytest.raises(ValueError, match="96"):
        expand_wall_clock_profile([1.0] * 95, FALL_BACK_DAY)


# --- consumption forecast per strategy ----------------------------------------


@pytest.mark.parametrize(
    "target_date, expected",
    [(NORMAL_DAY, 96), (FALL_BACK_DAY, 100), (SPRING_FORWARD_DAY, 92)],
)
@pytest.mark.parametrize("strategy", ["fixed", "sensor", "ha_statistics"])
def test_consumption_forecast_is_one_entry_per_real_period(
    strategy: str, target_date: date, expected: int
) -> None:
    controller = MockHomeAssistantController()
    controller.consumption_forecast = [0.5] * 96
    system = _system(controller)
    system.home_settings.consumption_strategy = strategy
    with patch.object(system, "_get_ha_statistics_forecast", return_value=PROFILE):
        forecast = system._get_consumption_forecast(target_date)

    assert len(forecast) == expected


def test_fixed_forecast_is_quarterly_value_times_period_count() -> None:
    system = _system()
    system.home_settings.consumption_strategy = "fixed"
    system.home_settings.default_hourly = 4.0

    assert system._get_consumption_forecast(FALL_BACK_DAY) == [1.0] * 100


def test_hour_of_day_profile_is_not_shifted_after_the_repeated_hour() -> None:
    system = _system()
    system.home_settings.consumption_strategy = "ha_statistics"
    with patch.object(system, "_get_ha_statistics_forecast", return_value=PROFILE):
        forecast = system._get_consumption_forecast(FALL_BACK_DAY)

    assert forecast[16] == PROFILE[12]  # real 03:00 CET reads the 03:00 value
    assert forecast[12:16] == PROFILE[8:12]  # repeated hour reuses 02:00's value


# --- the arrays the optimizer is handed ---------------------------------------


def test_next_day_plan_on_fall_back_day_has_100_aligned_consumption_and_solar() -> None:
    """Preparing tomorrow (the fall-back day) from the day before."""
    controller = MockHomeAssistantController()
    controller.solar_forecast_tomorrow = [q / 500.0 for q in range(96)]
    system = _system(controller)
    system.home_settings.consumption_strategy = "ha_statistics"

    with (
        _clock_at(date(2026, 10, 24)),
        patch.object(system, "_get_ha_statistics_forecast", return_value=PROFILE),
    ):
        result = system._gather_optimization_data(
            period=0, current_soc=50.0, prepare_next_day=True, period_count=100
        )

    assert result is not None
    _, data = result
    assert len(data["full_consumption"]) == 100
    assert len(data["full_solar"]) == 100
    assert data["full_consumption"][16] == PROFILE[12]
    assert data["full_solar"][16] == controller.solar_forecast_tomorrow[12]
    assert data["full_consumption"][99] == PROFILE[95]


def test_extended_horizon_tomorrow_slice_is_sized_by_tomorrows_period_count() -> None:
    """Today (24 Oct, 96) followed by tomorrow (25 Oct, 100) is 196 periods."""
    controller = MockHomeAssistantController()
    controller.solar_forecast_tomorrow = [q / 500.0 for q in range(96)]
    system = _system(controller)
    system.home_settings.consumption_strategy = "ha_statistics"

    with (
        _clock_at(date(2026, 10, 24)),
        patch.object(system, "_get_ha_statistics_forecast", return_value=PROFILE),
    ):
        result = system._gather_optimization_data(
            period=0, current_soc=50.0, prepare_next_day=False, period_count=196
        )

    assert result is not None
    _, data = result
    assert data["full_consumption"][:96] == PROFILE
    assert data["full_consumption"][96 + 16] == PROFILE[12]
    assert data["full_solar"][96 + 16] == controller.solar_forecast_tomorrow[12]
    assert data["full_consumption"][195] == PROFILE[95]


def test_todays_arrays_on_the_fall_back_day_are_100_long_and_aligned() -> None:
    controller = MockHomeAssistantController()
    controller.solar_forecast = [q / 500.0 for q in range(96)]
    system = _system(controller)
    system.home_settings.consumption_strategy = "ha_statistics"

    with (
        _clock_at(FALL_BACK_DAY),
        patch.object(system, "_get_ha_statistics_forecast", return_value=PROFILE),
    ):
        result = system._gather_optimization_data(
            period=40, current_soc=50.0, prepare_next_day=False, period_count=100
        )

    assert result is not None
    _, data = result
    assert data["full_consumption"][16] == PROFILE[12]
    assert data["full_solar"][16] == controller.solar_forecast[12]
    assert data["full_solar"][99] == controller.solar_forecast[95]


def test_next_day_plan_on_spring_forward_day_has_92_aligned_arrays() -> None:
    controller = MockHomeAssistantController()
    controller.solar_forecast_tomorrow = [q / 500.0 for q in range(96)]
    system = _system(controller)
    system.home_settings.consumption_strategy = "ha_statistics"

    with (
        _clock_at(date(2026, 3, 28)),
        patch.object(system, "_get_ha_statistics_forecast", return_value=PROFILE),
    ):
        result = system._gather_optimization_data(
            period=0, current_soc=50.0, prepare_next_day=True, period_count=92
        )

    assert result is not None
    _, data = result
    assert len(data["full_consumption"]) == len(data["full_solar"]) == 92
    assert data["full_consumption"][8] == PROFILE[12]  # 03:00 CEST follows 01:45
    assert data["full_solar"][8] == controller.solar_forecast_tomorrow[12]


def test_tomorrows_solar_and_consumption_agree_in_length_on_a_dst_day() -> None:
    """The (consumption, solar) pairing the terminal-value knee walks."""
    system = _system()
    system.home_settings.consumption_strategy = "fixed"
    with _clock_at(date(2026, 10, 24)):
        solar = system._fetch_tomorrow_solar_forecast()
        consumption = system._get_consumption_forecast(FALL_BACK_DAY)

    assert len(solar) == len(consumption) == 100
