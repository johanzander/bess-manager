"""Peak-shaving grid-import cap (issue #96, Option B).

`peak_shaving_import_cap_per_period` generalizes the fuse-derived
`import_cap_kwh` mechanism (#429) from a horizon-wide scalar to a per-period
cap: outside a configured window it is None (no constraint), inside it it
caps grid import for that period. The same "constrain, don't raise"
mechanism (#429) that already blocks grid-charging and forces discharge to
cover load applies -- this just varies the cap by period.
"""

from typing import Any

import pytest

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.exceptions import PeakShavingSensorError
from core.bess.price_manager import MockSource
from core.bess.settings import (
    MonthPeak,
    PeakShavingSettings,
    peak_shaving_import_cap_per_period,
)
from core.bess.tests.helpers import run_scenario_realized

# One capped period (index 1) sandwiched between two uncapped ones. Cheap
# buy price in period 1 and a high sell price reserved for period 2 give
# the battery a real opportunity cost for discharging early: importing
# cheaply in period 1 and exporting the preserved SOE at the period-2 price
# is worth far more than discharging now, so an uncapped plan imports
# instead of discharging -- a plan that discharges in period 1 anyway is
# evidence the cap, not price, drove the decision.
_SCENARIO: dict[str, Any] = {
    "battery": {
        "max_soe_kwh": 10.0,
        "min_soe_kwh": 1.0,
        "max_charge_power_kw": 5.0,
        # Deliberately well above what period 2 could ever need to export
        # (at most 7 kWh, min_soe to max_soe): keeps the discharge RATE from
        # ever being period 2's binding constraint, so every kWh preserved
        # in period 1 has real marginal export value in period 2 -- not just
        # value up to whatever a tighter rate cap could move anyway.
        "max_discharge_power_kw": 20.0,
        "efficiency_charge": 1.0,
        "efficiency_discharge": 1.0,
        "cycle_cost_per_kwh": 0.0,
        "initial_soe": 8.0,
        "initial_cost_basis": 0.0,
    },
    "buy_price": [0.01, 0.01, 0.01],
    "sell_price": [0.0, 0.0, 10.0],
    "home_consumption": [0.5, 2.0, 0.5],
    "solar_production": [0.0, 0.0, 0.0],
    "period_duration_hours": 1.0,
}

_CAP_KWH = 0.5


def test_peak_shaving_cap_forces_discharge_to_cover_load() -> None:
    """With the window-2 cap active, grid import in period 1 stays within the
    cap and the shortfall is covered by the battery -- and the executed plan
    matches what was planned (R == P), not just the plan's own claim.

    Verified by reversion below: without the cap, period 1's grid import
    exceeds it (grid import is cheaper than discharging given the wear
    cost), so this is not vacuously satisfied by a plan that would have
    stayed under the cap anyway.
    """
    scenario = {
        **_SCENARIO,
        "peak_shaving_import_cap_per_period": [None, _CAP_KWH, None],
    }
    result, realized_cost = run_scenario_realized(scenario)

    assert realized_cost == pytest.approx(
        result.economic_summary.battery_solar_cost, abs=1e-9
    ), "executed plan's realized cost must match the planned cost (R == P)"

    capped_period = result.period_data[1]
    assert capped_period.energy.grid_imported <= _CAP_KWH + 1e-9, (
        f"period 1 imported {capped_period.energy.grid_imported} kWh, "
        f"above the configured cap of {_CAP_KWH} kWh"
    )
    # The 2.0 kWh load isn't fully covered by the capped import alone --
    # confirms the battery, not solar (there is none), made up the rest.
    discharged = capped_period.energy.battery_discharged
    assert discharged > 1.0, (
        f"period 1 only discharged {discharged} kWh -- the cap should have "
        "forced the battery to cover most of the 2.0 kWh load"
    )


def test_peak_shaving_cap_is_not_vacuous() -> None:
    """Reversion check: without the cap, the same scenario imports from the
    grid instead of discharging in period 1, because grid import (0.01
    SEK/kWh) is far cheaper than the opportunity cost of not having that
    SOE available to export at 10 SEK/kWh in period 2. This is what proves
    the first test's assertions actually discriminate on the cap being
    applied, not on some other property of the scenario.
    """
    uncapped_scenario = {
        **_SCENARIO,
        "peak_shaving_import_cap_per_period": [None, None, None],
    }
    result, _ = run_scenario_realized(uncapped_scenario)
    capped_period = result.period_data[1]
    assert capped_period.energy.grid_imported > _CAP_KWH + 1e-9, (
        "expected the uncapped plan to import more than the cap would allow "
        f"(got {capped_period.energy.grid_imported} kWh) -- otherwise the "
        "capped test above is vacuous"
    )


def test_peak_shaving_import_cap_per_period_disabled_returns_none() -> None:
    """Disabled (the default) means no additional constraint at all."""
    settings = PeakShavingSettings()
    assert (
        peak_shaving_import_cap_per_period(settings, ["2026-01-05 08:00"], dt=1.0)
        is None
    )


def test_peak_shaving_import_cap_per_period_windows_by_time_and_weekday() -> None:
    """Only periods inside the configured time window AND weekday get a cap;
    everything else is None.

    2026-01-05 is a Monday, 2026-01-10 a Saturday -- both dates are used to
    pin the weekday filter, not just the time-of-day one.
    """
    settings = PeakShavingSettings(
        enabled=True,
        start_time="07:00",
        end_time="20:00",
        days=[0, 1, 2, 3, 4],  # Monday-Friday
        max_import_kw=2.0,
    )
    timestamps = [
        "2026-01-05 06:59",  # Monday, just before the window
        "2026-01-05 07:00",  # Monday, window start (inclusive)
        "2026-01-05 19:59",  # Monday, just before window end
        "2026-01-05 20:00",  # Monday, window end (exclusive)
        "2026-01-10 12:00",  # Saturday, inside the time window but wrong day
    ]
    caps = peak_shaving_import_cap_per_period(settings, timestamps, dt=1.0)

    assert caps == [None, 2.0, 2.0, None, None]


def test_peak_shaving_import_cap_per_period_overnight_window() -> None:
    """An overnight window (start_time > end_time, e.g. 22:00-06:00) covers
    both sides of midnight, with the post-midnight portion attributed to
    the day the window started -- so `days=[0]` (Monday) means "the whole
    Monday-night-into-Tuesday-morning window", not two separate half-windows.
    """
    settings = PeakShavingSettings(
        enabled=True,
        start_time="22:00",
        end_time="06:00",
        days=[0],  # Monday only
        max_import_kw=2.0,
    )
    timestamps = [
        "2026-01-05 21:59",  # Monday, just before the window
        "2026-01-05 22:00",  # Monday, window start (inclusive)
        "2026-01-06 02:00",  # Tuesday early morning, still Monday's window
        "2026-01-06 05:59",  # Tuesday, just before window end
        "2026-01-06 06:00",  # Tuesday, window end (exclusive)
        "2026-01-06 23:00",  # Tuesday night -- not in `days`, so excluded
    ]
    caps = peak_shaving_import_cap_per_period(settings, timestamps, dt=1.0)

    assert caps == [None, 2.0, 2.0, 2.0, None, None]


# --- Dynamic cap (issue #96, Flemish capacity tariff) -----------------------
#
# With a month-peak reading the cap is not the fixed `max_import_kw` but
# min(max_import_kw, max(floor_kw, month_peak_kw)): importing below what the
# month's peak already is (or the tariff's free floor) costs nothing, while
# importing above it raises the bill for the whole month.

_ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]


def _flemish_settings() -> PeakShavingSettings:
    return PeakShavingSettings(
        enabled=True,
        all_day=True,  # Flanders bills every quarter-hour: no window
        days=_ALL_DAYS,
        max_import_kw=5.0,
        floor_kw=2.5,
    )


def test_dynamic_cap_tightens_to_floor_when_month_peak_is_below_it() -> None:
    caps = peak_shaving_import_cap_per_period(
        _flemish_settings(),
        ["2026-10-05 14:45", "2026-10-05 15:00"],
        dt=0.25,
        month_peak=MonthPeak(month="2026-10", kw=1.40),
    )
    assert caps == [pytest.approx(2.5 * 0.25), pytest.approx(2.5 * 0.25)]


def test_dynamic_cap_follows_month_peak_between_floor_and_ceiling() -> None:
    caps = peak_shaving_import_cap_per_period(
        _flemish_settings(),
        ["2026-10-20 18:00"],
        dt=0.25,
        month_peak=MonthPeak(month="2026-10", kw=4.0),
    )
    assert caps == [pytest.approx(4.0 * 0.25)]


def test_dynamic_cap_never_exceeds_the_configured_ceiling() -> None:
    caps = peak_shaving_import_cap_per_period(
        _flemish_settings(),
        ["2026-10-20 18:00"],
        dt=0.25,
        month_peak=MonthPeak(month="2026-10", kw=6.2),
    )
    assert caps == [pytest.approx(5.0 * 0.25)]


def test_dynamic_cap_falls_back_to_floor_after_month_rollover() -> None:
    """The peak resets on the 1st: periods in the next month get the floor,
    not the old month's peak, or the last day of the month would plan against
    a peak that no longer applies."""
    caps = peak_shaving_import_cap_per_period(
        _flemish_settings(),
        ["2026-10-31 23:45", "2026-11-01 00:00"],
        dt=0.25,
        month_peak=MonthPeak(month="2026-10", kw=4.0),
    )
    assert caps == [pytest.approx(4.0 * 0.25), pytest.approx(2.5 * 0.25)]


def test_without_a_month_peak_the_cap_is_the_fixed_ceiling() -> None:
    """No peak entity configured: behaviour is exactly the shipped fixed cap."""
    caps = peak_shaving_import_cap_per_period(
        _flemish_settings(), ["2026-10-05 14:45"], dt=0.25
    )
    assert caps == [pytest.approx(5.0 * 0.25)]


def test_all_day_ignores_the_window_times_but_still_honours_the_days() -> None:
    settings = _flemish_settings()
    settings.start_time = "07:00"
    settings.end_time = "08:00"
    settings.days = [0]  # Monday only; 2026-10-05 is a Monday, 2026-10-06 a Tuesday
    caps = peak_shaving_import_cap_per_period(
        settings,
        [
            "2026-10-05 00:00",
            "2026-10-05 12:00",
            "2026-10-05 23:45",
            "2026-10-06 12:00",
        ],
        dt=0.25,
    )
    assert caps == [pytest.approx(5.0 * 0.25)] * 3 + [None]


def test_equal_start_and_end_time_is_still_an_empty_window() -> None:
    """The existing meaning of start == end is unchanged: all-day is its own
    setting, not an encoding of the window times."""
    settings = PeakShavingSettings(
        enabled=True,
        start_time="08:00",
        end_time="08:00",
        days=_ALL_DAYS,
        max_import_kw=5.0,
    )
    caps = peak_shaving_import_cap_per_period(
        settings, ["2026-10-05 08:00", "2026-10-05 12:00"], dt=0.25
    )
    assert caps == [None, None]


def test_dynamic_cap_stops_a_cheap_grid_charge_from_setting_a_new_peak() -> None:
    """Frank's 2026-10-05 quarter, replayed through the real DP.

    Cheap period 0 invites charging at full power to serve later. Under the
    fixed 5 kW cap the DP imports well above 2.5 kWh in the hour; with his
    month peak at 1.40 kW and the 2.5 kW floor it may import at most 2.5 kWh
    -- and the plan's own flows stay within it.

    This asserts the DP's plan, not the executed one: `simulate()` runs
    `_state_transition` without the import cap, and the DP treats any
    positive charge power as "charge as much as the cap and rate allow", so
    the simulator charges at full rate regardless of the 40% command and
    would report R != P for any throttled grid charge, fuse cap (#429)
    included. Plan-faithfulness for the cap is covered on the discharge side
    below, which the simulator does model.
    """
    scenario = {
        **_SCENARIO,
        "battery": {**_SCENARIO["battery"], "initial_soe": 1.0},
        "buy_price": [0.01, 1.0, 1.0],
        "sell_price": [0.0, 1.0, 1.0],
        "home_consumption": [0.5, 0.5, 0.5],
    }
    timestamps = ["2026-10-05 02:00", "2026-10-05 03:00", "2026-10-05 04:00"]

    fixed_caps = peak_shaving_import_cap_per_period(
        _flemish_settings(), timestamps, dt=1.0
    )
    fixed, _ = run_scenario_realized(
        {**scenario, "peak_shaving_import_cap_per_period": fixed_caps}
    )
    assert fixed.period_data[0].energy.grid_imported > 2.5 + 1e-9, (
        "expected the fixed 5 kW cap to let the DP import above the floor "
        "-- otherwise the dynamic assertion below is vacuous"
    )

    dynamic_caps = peak_shaving_import_cap_per_period(
        _flemish_settings(),
        timestamps,
        dt=1.0,
        month_peak=MonthPeak(month="2026-10", kw=1.40),
    )
    result, _ = run_scenario_realized(
        {**scenario, "peak_shaving_import_cap_per_period": dynamic_caps}
    )
    assert result.period_data[0].energy.grid_imported <= 2.5 + 1e-9


# --- Wiring: BatterySystemManager reads the peak and builds the cap ----------


@pytest.fixture
def peak_system(mock_controller: Any) -> BatterySystemManager:
    system = BatterySystemManager(
        controller=mock_controller, price_source=MockSource([1.0] * 96)
    )
    system.peak_shaving = _flemish_settings()
    return system


def _entries_today() -> list[dict[str, Any]]:
    """Two quarter-hour price entries on today's date, in PriceManager's format."""
    today = time_utils.today().strftime("%Y-%m-%d")
    return [{"timestamp": f"{today} 14:45"}, {"timestamp": f"{today} 15:00"}]


def test_system_builds_the_dynamic_cap_from_the_month_peak_entity(
    peak_system: BatterySystemManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        peak_system.controller, "get_peak_shaving_month_peak_kw", lambda: 1.40
    )

    caps = peak_system._get_peak_shaving_import_cap_limits(_entries_today(), dt=0.25)

    assert caps == [pytest.approx(2.5 * 0.25)] * 2


def test_system_without_a_month_peak_entity_keeps_the_fixed_cap(
    peak_system: BatterySystemManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        peak_system.controller, "get_peak_shaving_month_peak_kw", lambda: None
    )

    caps = peak_system._get_peak_shaving_import_cap_limits(_entries_today(), dt=0.25)

    assert caps == [pytest.approx(5.0 * 0.25)] * 2


def test_unusable_month_peak_entity_blocks_planning_and_is_surfaced(
    peak_system: BatterySystemManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No silent fallback to the fixed cap: the error propagates and lands on
    the dashboard, and clears once the entity reads cleanly again."""

    def _broken() -> float:
        raise PeakShavingSensorError("entity is unavailable")

    monkeypatch.setattr(
        peak_system.controller, "get_peak_shaving_month_peak_kw", _broken
    )
    with pytest.raises(PeakShavingSensorError):
        peak_system._get_peak_shaving_import_cap_limits(_entries_today(), dt=0.25)
    assert peak_system._runtime_failure_tracker.has_active_failure(
        "PEAK_SHAVING_SENSOR"
    )

    monkeypatch.setattr(
        peak_system.controller, "get_peak_shaving_month_peak_kw", lambda: 1.40
    )
    peak_system._get_peak_shaving_import_cap_limits(_entries_today(), dt=0.25)
    assert not peak_system._runtime_failure_tracker.has_active_failure(
        "PEAK_SHAVING_SENSOR"
    )


def test_disabled_peak_shaving_never_reads_the_entity(
    peak_system: BatterySystemManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken entity must not block planning for a user who turned the
    feature off."""

    def _broken() -> float:
        raise PeakShavingSensorError("entity is unavailable")

    monkeypatch.setattr(
        peak_system.controller, "get_peak_shaving_month_peak_kw", _broken
    )
    peak_system.peak_shaving.enabled = False

    assert (
        peak_system._get_peak_shaving_import_cap_limits(_entries_today(), dt=0.25)
        is None
    )


def test_dynamic_cap_covers_load_with_the_battery_and_executes_as_planned() -> None:
    """The same discharge-side scenario as the fixed-cap test, with the cap
    now derived from a month peak: floor 0.5 kW, peak 0.3 kW -> 0.5 kWh cap.
    The plan covers the load from the battery and R == P."""
    settings = PeakShavingSettings(
        enabled=True,
        all_day=True,
        days=_ALL_DAYS,
        max_import_kw=5.0,
        floor_kw=_CAP_KWH,
    )
    caps = peak_shaving_import_cap_per_period(
        settings,
        ["2026-10-05 02:00", "2026-10-05 03:00", "2026-10-05 04:00"],
        dt=1.0,
        month_peak=MonthPeak(month="2026-10", kw=0.3),
    )
    assert caps == [pytest.approx(_CAP_KWH)] * 3

    result, realized_cost = run_scenario_realized(
        {**_SCENARIO, "peak_shaving_import_cap_per_period": caps}
    )

    assert realized_cost == pytest.approx(
        result.economic_summary.battery_solar_cost, abs=1e-9
    ), "executed plan's realized cost must match the planned cost (R == P)"
    assert result.period_data[1].energy.grid_imported <= _CAP_KWH + 1e-9
