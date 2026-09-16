"""Tests for the Octopus free-import price overlay.

Octopus does not change the published Agile rate for a Power Up session or a
Weekend Happy Hour, so BESS composes the free window onto the cached price
entries itself. The windows come from the Octoplus power-up calendar entity.
"""

import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from core.bess import time_utils
from core.bess.calendar_windows import CalendarWindow, parse_calendar_events
from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.exceptions import CalendarWindowError
from core.bess.free_import_overlay import apply_free_import_windows
from core.bess.price_manager import MockSource, PriceManager
from core.bess.settings import BatterySettings
from core.bess.simulation.inverter_simulator import (
    SimulationResult,
    derive_control_command,
    simulate,
)

LONDON = ZoneInfo("Europe/London")


@pytest.fixture(autouse=True)
def _london_timezone() -> Iterator[None]:
    previous = time_utils.TIMEZONE
    time_utils.set_timezone("Europe/London")
    yield
    time_utils.TIMEZONE = previous


def _entries(day: date, count: int, buy: float = 0.30, sell: float = 0.12) -> list:
    """Price entries in PriceManager's shape: period i is i quarter-hours after midnight."""
    base = datetime.combine(day, datetime.min.time())
    return [
        {
            "timestamp": (base + timedelta(minutes=15 * i)).strftime("%Y-%m-%d %H:%M"),
            "price": buy,
            "buyPrice": buy,
            "sellPrice": sell,
        }
        for i in range(count)
    ]


def _window(start: datetime, end: datetime) -> CalendarWindow:
    return CalendarWindow(start=start, end=end)


def _free_periods(entries: list) -> list[int]:
    return [i for i, e in enumerate(entries) if e["isFreeImport"]]


# --- Composition -------------------------------------------------------------


def test_periods_inside_a_window_are_free_to_import_but_keep_their_export_price() -> (
    None
):
    day = date(2026, 9, 13)
    entries = _entries(day, 96)
    window = _window(
        datetime(2026, 9, 13, 11, 0, tzinfo=LONDON),
        datetime(2026, 9, 13, 12, 0, tzinfo=LONDON),
    )

    result = apply_free_import_windows(entries, day, [window], free_price=0.0)

    assert _free_periods(result) == [44, 45, 46, 47]
    for i in (44, 45, 46, 47):
        assert result[i]["buyPrice"] == 0.0
        assert result[i]["sellPrice"] == 0.12
        assert result[i]["price"] == 0.30


def test_periods_outside_every_window_are_untouched() -> None:
    day = date(2026, 9, 13)
    entries = _entries(day, 96)
    window = _window(
        datetime(2026, 9, 13, 11, 0, tzinfo=LONDON),
        datetime(2026, 9, 13, 12, 0, tzinfo=LONDON),
    )

    result = apply_free_import_windows(entries, day, [window], free_price=0.0)

    for i, entry in enumerate(result):
        if i not in (44, 45, 46, 47):
            assert entry["buyPrice"] == 0.30
            assert entry["isFreeImport"] is False


def test_configured_free_price_is_used_instead_of_zero() -> None:
    day = date(2026, 9, 13)
    window = _window(
        datetime(2026, 9, 13, 11, 0, tzinfo=LONDON),
        datetime(2026, 9, 13, 11, 30, tzinfo=LONDON),
    )

    result = apply_free_import_windows(
        _entries(day, 96), day, [window], free_price=0.05
    )

    assert [result[i]["buyPrice"] for i in (44, 45)] == [0.05, 0.05]


def test_partially_covered_period_keeps_its_price_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    day = date(2026, 9, 13)
    window = _window(
        datetime(2026, 9, 13, 11, 10, tzinfo=LONDON),
        datetime(2026, 9, 13, 11, 30, tzinfo=LONDON),
    )

    with caplog.at_level(logging.WARNING):
        result = apply_free_import_windows(
            _entries(day, 96), day, [window], free_price=0.0
        )

    assert _free_periods(result) == [45]
    assert result[44]["buyPrice"] == 0.30
    assert "11:10" in caplog.text


def test_cached_entries_are_not_mutated() -> None:
    day = date(2026, 9, 13)
    entries = _entries(day, 96)
    window = _window(
        datetime(2026, 9, 13, 0, 0, tzinfo=LONDON),
        datetime(2026, 9, 14, 0, 0, tzinfo=LONDON),
    )

    apply_free_import_windows(entries, day, [window], free_price=0.0)

    assert all(e["buyPrice"] == 0.30 for e in entries)
    assert all("isFreeImport" not in e for e in entries)


def test_window_spanning_midnight_frees_the_right_periods_on_each_day() -> None:
    today, tomorrow = date(2026, 9, 13), date(2026, 9, 14)
    window = _window(
        datetime(2026, 9, 13, 23, 30, tzinfo=LONDON),
        datetime(2026, 9, 14, 0, 30, tzinfo=LONDON),
    )

    today_result = apply_free_import_windows(
        _entries(today, 96), today, [window], free_price=0.0
    )
    tomorrow_result = apply_free_import_windows(
        _entries(tomorrow, 96), tomorrow, [window], free_price=0.0
    )

    assert _free_periods(today_result) == [94, 95]
    assert _free_periods(tomorrow_result) == [0, 1]


def test_window_given_in_utc_aligns_with_local_periods() -> None:
    day = date(2026, 9, 13)
    window = _window(
        datetime(2026, 9, 13, 10, 0, tzinfo=UTC),
        datetime(2026, 9, 13, 11, 0, tzinfo=UTC),
    )

    result = apply_free_import_windows(_entries(day, 96), day, [window], 0.0)

    assert _free_periods(result) == [44, 45, 46, 47]  # 11:00-12:00 BST


def test_spring_forward_day_aligns_by_elapsed_time_not_wall_clock_index() -> None:
    """On the 92-period day, 11:00 BST is 10 elapsed hours after midnight GMT."""
    day = date(2026, 3, 29)
    assert time_utils.get_period_count(day) == 92
    window = _window(
        datetime(2026, 3, 29, 11, 0, tzinfo=LONDON),
        datetime(2026, 3, 29, 12, 0, tzinfo=LONDON),
    )

    result = apply_free_import_windows(_entries(day, 92), day, [window], 0.0)

    assert _free_periods(result) == [40, 41, 42, 43]


def test_fall_back_day_aligns_by_elapsed_time_not_wall_clock_index() -> None:
    """On the 100-period day, 11:00 GMT is 12 elapsed hours after midnight BST."""
    day = date(2026, 10, 25)
    assert time_utils.get_period_count(day) == 100
    window = _window(
        datetime(2026, 10, 25, 11, 0, tzinfo=LONDON),
        datetime(2026, 10, 25, 12, 0, tzinfo=LONDON),
    )

    result = apply_free_import_windows(_entries(day, 100), day, [window], 0.0)

    assert _free_periods(result) == [48, 49, 50, 51]


# --- Parsing the HA calendar payload -----------------------------------------


def test_verified_ha_calendar_payload_parses_to_a_window() -> None:
    raw = [
        {
            "start": {"dateTime": "2026-09-13T11:00:00+01:00"},
            "end": {"dateTime": "2026-09-13T12:00:00+01:00"},
            "summary": "Octopus Energy Power Up",
            "description": None,
            "location": None,
            "uid": 6134,
            "recurrence_id": None,
            "rrule": None,
        }
    ]

    assert parse_calendar_events(raw) == [
        CalendarWindow(
            start=datetime(2026, 9, 13, 10, 0, tzinfo=UTC),
            end=datetime(2026, 9, 13, 11, 0, tzinfo=UTC),
        )
    ]


def test_empty_calendar_parses_to_no_windows() -> None:
    assert parse_calendar_events([]) == []


@pytest.mark.parametrize(
    "event",
    [
        pytest.param(
            {"start": {"date": "2026-09-13"}, "end": {"date": "2026-09-14"}},
            id="all-day event",
        ),
        pytest.param(
            {"start": {}, "end": {"dateTime": "2026-09-13T12:00:00+01:00"}},
            id="missing dateTime",
        ),
        pytest.param(
            {
                "start": {"dateTime": "2026-09-13T11:00:00"},
                "end": {"dateTime": "2026-09-13T12:00:00"},
            },
            id="no UTC offset",
        ),
        pytest.param(
            {
                "start": {"dateTime": "2026-09-13T12:00:00+01:00"},
                "end": {"dateTime": "2026-09-13T11:00:00+01:00"},
            },
            id="end before start",
        ),
        pytest.param(
            {
                "start": {"dateTime": "not a time"},
                "end": {"dateTime": "2026-09-13T12:00:00+01:00"},
            },
            id="unparseable dateTime",
        ),
        pytest.param("not a mapping", id="non-mapping event"),
    ],
)
def test_malformed_calendar_events_raise(event: object) -> None:
    with pytest.raises(CalendarWindowError):
        parse_calendar_events([event])


def test_non_list_payload_raises() -> None:
    with pytest.raises(CalendarWindowError):
        parse_calendar_events({"events": []})


# --- Outcome: what the plan does with a free window --------------------------


def _plan_and_execute_through_price_manager(
    windows: list[CalendarWindow],
) -> SimulationResult:
    """Price a flat day through PriceManager, optimize it, and execute the plan."""
    dt = 0.25
    settings = BatterySettings(
        total_capacity=10.0,
        min_soc=10.0,
        max_soc=100.0,
        max_charge_power_kw=6.0,
        max_discharge_power_kw=6.0,
        efficiency_charge=0.95,
        efficiency_discharge=0.95,
        cycle_cost_per_kwh=0.02,
    )
    price_manager = PriceManager(
        MockSource([0.30] * 96),
        markup_rate=0.0,
        vat_multiplier=1.0,
        additional_costs=0.0,
        tax_reduction=0.0,
        area="GB",
        export_spot_multiplier=0.4,  # 12p export against 30p import
        free_import_window_source=lambda start, end: windows,
    )
    with patch(
        "core.bess.time_utils.now",
        return_value=datetime(2026, 9, 13, 0, 0, tzinfo=LONDON),
    ):
        price_manager.refresh_cache()
        entries = price_manager.get_cached_today_prices()

    buy = [e["buyPrice"] for e in entries]
    sell = [e["sellPrice"] for e in entries]
    assert sell == [pytest.approx(0.12)] * 96
    load = [0.25] * 96
    solar = [0.0] * 96
    initial_soe = 2.0  # 20% of 10 kWh

    plan = optimize_battery_schedule(
        buy,
        sell,
        load,
        settings,
        solar_production=solar,
        initial_soe=initial_soe,
        period_duration_hours=dt,
    )
    commands = []
    for pd in plan.period_data:
        action = pd.decision.battery_action
        assert action is not None
        commands.append(
            derive_control_command(
                pd.decision.strategic_intent,
                action / dt,
                settings,
                intra_period_discharge_allowed=pd.decision.intra_period_discharge_allowed,
            )
        )
    return simulate(commands, solar, load, buy, sell, initial_soe, settings, dt)


def test_plan_fills_the_battery_for_free_instead_of_paying_or_discharging() -> None:
    window = _window(
        datetime(2026, 9, 13, 11, 0, tzinfo=LONDON),
        datetime(2026, 9, 13, 12, 0, tzinfo=LONDON),
    )
    in_window = slice(44, 48)

    with_window = _plan_and_execute_through_price_manager([window])
    without_window = _plan_and_execute_through_price_manager([])

    periods = with_window.period_data
    grid_charge_cost_before = sum(
        p.energy.grid_to_battery * p.economic.buy_price for p in periods[:44]
    )
    assert grid_charge_cost_before == 0.0, "charging was not deferred into the window"
    assert sum(p.energy.battery_to_home for p in periods[in_window]) == 0.0
    grid_to_battery = sum(p.energy.grid_to_battery for p in periods[in_window])
    grid_to_home = sum(p.energy.grid_to_home for p in periods[in_window])
    assert grid_to_battery > 0.0, "the free window was not used to charge"

    # Every free kWh would otherwise have been bought at 30p -- directly for
    # the house, or after charge/discharge losses and cycle wear for what
    # went into the battery.
    free_energy_value = (
        0.30 * (grid_to_home + grid_to_battery * 0.95 * 0.95) - 0.02 * grid_to_battery
    )
    reduction = without_window.realized_cost - with_window.realized_cost
    assert reduction >= free_energy_value - 1e-6, (
        f"window cut realized cost by {reduction:.4f}, less than the "
        f"{free_energy_value:.4f} its free energy is worth"
    )
