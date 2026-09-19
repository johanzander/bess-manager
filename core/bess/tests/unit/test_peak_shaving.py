"""Peak-shaving grid-import cap (issue #96, Option B).

`peak_shaving_import_cap_per_period` generalizes the fuse-derived
`import_cap_kwh` mechanism (#429) from a horizon-wide scalar to a per-period
cap: outside a configured window it is None (no constraint), inside it it
caps grid import for that period. The same "constrain, don't raise"
mechanism (#429) that already blocks grid-charging and forces discharge to
cover load applies -- this just varies the cap by period.
"""

import pytest

from core.bess.settings import PeakShavingSettings, peak_shaving_import_cap_per_period
from core.bess.tests.helpers import run_scenario_realized

# One capped period (index 1) sandwiched between two uncapped ones. Cheap
# buy price in period 1 and a high sell price reserved for period 2 give
# the battery a real opportunity cost for discharging early: importing
# cheaply in period 1 and exporting the preserved SOE at the period-2 price
# is worth far more than discharging now, so an uncapped plan imports
# instead of discharging -- a plan that discharges in period 1 anyway is
# evidence the cap, not price, drove the decision.
_SCENARIO = {
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
