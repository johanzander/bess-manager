"""Octoplus Power Down: per-period session import cap.

New optimizer input `session_import_cap_kwh_per_period` (element None = no
session cap that period) forces zero grid import in a joined Power Down
session window, "constrain, don't raise" (#429) exactly like the house-fuse
cap: an empty battery with nothing to export still imports the load it must
rather than the plan becoming infeasible. Where a fuse cap (home_settings)
also applies, the tighter of the two binds per period. See
docs/superpowers/specs/2026-09-13-octopus-power-down-export-pulse-design.md.
"""

import dataclasses
from typing import Any

import pytest

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.tests.helpers import _scenario_inputs, run_scenario_realized
from core.bess.tests.unit.test_grid_import_cap import (
    IMPORT_CAP_KWH,
    IMPORT_CAP_SCENARIO,
)

DT = 0.25
PERIODS = 4
TARGET_PERIOD = 2
EXPORT_TARGET_KWH = 0.25

BASE_SCENARIO: dict[str, Any] = {
    "battery": {
        "max_soe_kwh": 10.0,
        "min_soe_kwh": 1.0,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "efficiency_charge": 1.0,
        "efficiency_discharge": 1.0,
        "cycle_cost_per_kwh": 0.0,
        "initial_soe": 10.0,  # overridden per test
    },
    "buy_price": [1.0] * PERIODS,
    "sell_price": [0.1] * PERIODS,
    "home_consumption": [0.3] * PERIODS,
    "solar_production": [0.0] * PERIODS,
    "period_duration_hours": DT,
}


def _session_scenario(initial_soe: float) -> dict:
    caps: list[float | None] = [None] * PERIODS
    caps[TARGET_PERIOD] = 0.0
    targets = [0.0] * PERIODS
    targets[TARGET_PERIOD] = EXPORT_TARGET_KWH
    return {
        **BASE_SCENARIO,
        "battery": {**BASE_SCENARIO["battery"], "initial_soe": initial_soe},
        "session_import_cap_kwh_per_period": caps,
        "min_grid_export_kwh_per_period": targets,
    }


def test_full_battery_exports_the_target_and_imports_nothing() -> None:
    result, realized_cost = run_scenario_realized(_session_scenario(initial_soe=10.0))
    period = result.period_data[TARGET_PERIOD]

    assert period.energy.grid_exported >= EXPORT_TARGET_KWH
    assert period.energy.grid_imported == 0.0
    assert realized_cost == pytest.approx(
        result.economic_summary.battery_solar_cost, abs=0.01
    ), "Plan is not faithfully executable (R != P)"


def test_empty_battery_still_imports_the_load_it_must() -> None:
    """No raise: 'constrain, don't raise' lets the load import through even
    though the session cap is 0.0 and there is nothing to export."""
    result, realized_cost = run_scenario_realized(_session_scenario(initial_soe=1.0))
    period = result.period_data[TARGET_PERIOD]

    assert period.energy.grid_exported == 0.0
    assert period.energy.grid_imported > 0.0
    assert realized_cost == pytest.approx(
        result.economic_summary.battery_solar_cost, abs=0.01
    )


EVENING_SESSION_PERIODS = 4  # the session itself: one hour, 18:00-19:00
EVENING_HORIZON_PERIODS = 8  # + a second hour, 19:00-20:00, to re-buy the pulse
EVENING_BUY_PRICE = 2.0  # peak import
EVENING_SELL_PRICE = 0.1  # flat export
# Available energy above the floor (6.0 - 1.0 = 5.0 kWh, "battery at 60%" of
# a 10 kWh pack) exactly equals total consumption over the two-hour horizon
# (8 * 0.625 = 5.0 kWh) -- deliberately, per the min-export outcome test's own
# terminal-value note: without this, the pulse's exported energy is never
# re-bought inside the horizon, and the DP's reported cost (which does not
# price leftover SoE) makes the constraint look free or even negative.
EVENING_SESSION_SCENARIO: dict[str, Any] = {
    "battery": {
        "max_soe_kwh": 10.0,
        "min_soe_kwh": 1.0,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "efficiency_charge": 1.0,
        "efficiency_discharge": 1.0,
        "cycle_cost_per_kwh": 0.0,
        "initial_soe": 6.0,  # 60% of max_soe_kwh
    },
    "buy_price": [EVENING_BUY_PRICE] * EVENING_HORIZON_PERIODS,
    "sell_price": [EVENING_SELL_PRICE] * EVENING_HORIZON_PERIODS,
    "home_consumption": [0.625] * EVENING_HORIZON_PERIODS,
    "solar_production": [0.0] * EVENING_HORIZON_PERIODS,
    "period_duration_hours": DT,
    "terminal_value_per_kwh": 1.0,
}


def test_outcome_evening_session_exports_the_pulse_and_imports_nothing() -> None:
    """Spec scenario (Testing > Outcome test): an evening session, battery at
    60%, peak import, flat export. The session's own hour gets a 0.0 import
    cap on all 4 periods, and the pulse target lands on the first one."""
    caps: list[float | None] = [0.0] * EVENING_SESSION_PERIODS + [None] * (
        EVENING_HORIZON_PERIODS - EVENING_SESSION_PERIODS
    )
    targets = [0.0] * EVENING_HORIZON_PERIODS
    targets[0] = EXPORT_TARGET_KWH
    constrained_scenario = {
        **EVENING_SESSION_SCENARIO,
        "session_import_cap_kwh_per_period": caps,
        "min_grid_export_kwh_per_period": targets,
    }

    unconstrained, _ = run_scenario_realized(EVENING_SESSION_SCENARIO)
    constrained, constrained_realized = run_scenario_realized(constrained_scenario)

    pulse_period = constrained.period_data[0]
    exported = pulse_period.energy.grid_exported
    assert exported >= EXPORT_TARGET_KWH
    # The battery covers the session's own load, so grid import stays at
    # zero throughout the capped window.
    assert all(
        constrained.period_data[p].energy.grid_imported == 0.0
        for p in range(EVENING_SESSION_PERIODS)
    )
    assert constrained_realized == pytest.approx(
        constrained.economic_summary.battery_solar_cost, abs=0.01
    ), "Plan is not faithfully executable (R != P)"

    extra_cost = (
        constrained.economic_summary.battery_solar_cost
        - unconstrained.economic_summary.battery_solar_cost
    )
    # Non-vacuous bound: the constraint costs something (re-buying what it
    # exported, net of the export revenue) but never more than that.
    assert extra_cost > 0.0, (
        "fixture no longer discriminates: the pulse's energy was not "
        "re-bought inside the horizon"
    )
    assert extra_cost <= exported * (EVENING_BUY_PRICE - EVENING_SELL_PRICE) + 1e-9


def test_session_import_cap_wrong_length_raises() -> None:
    inputs = _scenario_inputs(BASE_SCENARIO)

    with pytest.raises(ValueError, match="session_import_cap_kwh_per_period"):
        optimize_battery_schedule(
            **inputs,
            session_import_cap_kwh_per_period=[None] * (PERIODS - 1),
        )


def test_session_cap_binds_tighter_than_a_looser_fuse_cap() -> None:
    """IMPORT_CAP_SCENARIO's spike period discharges just enough to meet the
    ~15.18 kWh fuse cap (test_grid_import_cap.py's own pinned result). A
    session cap of 5.0 kWh at the same period is tighter, has to win, and the
    battery has 9 kWh of headroom there -- not enough to reach 5.0 kWh import
    (needs 15 kWh discharge), so "constrain, don't raise" floors at the
    achievable minimum (20 - 9 = 11 kWh), well below the fuse cap alone."""
    caps: list[float | None] = [None] * len(IMPORT_CAP_SCENARIO["buy_price"])
    caps[2] = 5.0
    scenario = {
        **IMPORT_CAP_SCENARIO,
        "session_import_cap_kwh_per_period": caps,
    }

    result, realized_cost = run_scenario_realized(scenario)
    spike = result.period_data[2]

    assert spike.energy.grid_imported < IMPORT_CAP_KWH - 1.0, (
        "session cap did not bind tighter than the fuse cap alone: import "
        f"{spike.energy.grid_imported:.2f} kWh is not below the fuse-alone "
        f"result (~{IMPORT_CAP_KWH:.2f} kWh)"
    )
    assert realized_cost == pytest.approx(
        result.economic_summary.battery_solar_cost, abs=0.01
    ), "Plan is not faithfully executable (R != P)"


def test_an_all_none_session_cap_list_matches_no_session_cap_at_all() -> None:
    """session_import_cap_kwh_per_period=[None, None, ...] takes the
    list-comprehension combine branch (the parameter itself is not None);
    session_import_cap_kwh_per_period=None (the default) takes the
    fuse-broadcast branch instead. The two must produce bit-identical plans
    whenever the fuse cap is enabled, since every element defers to it."""
    inputs = _scenario_inputs(IMPORT_CAP_SCENARIO)
    horizon = len(inputs["buy_price"])

    without_session_list = optimize_battery_schedule(**inputs)
    with_all_none_session_list = optimize_battery_schedule(
        **inputs, session_import_cap_kwh_per_period=[None] * horizon
    )

    assert without_session_list.economic_summary is not None
    assert with_all_none_session_list.economic_summary is not None
    assert [dataclasses.asdict(p) for p in with_all_none_session_list.period_data] == [
        dataclasses.asdict(p) for p in without_session_list.period_data
    ]
    assert dataclasses.asdict(
        with_all_none_session_list.economic_summary
    ) == dataclasses.asdict(without_session_list.economic_summary)
