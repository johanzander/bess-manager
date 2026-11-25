"""Plan-faithfulness regression for the fuse cap on grid export (#910).

A fuse trips on current in either direction, but the fuse-derived cap (#429)
only bounded `grid_imported`. When the user opts in (`fuse_limits_export`),
the cap bounds `grid_exported` too, with the same "constrain, don't raise"
floor as the import side. It is opt-in because some users set the fuse fields
to a grid operator's import-only limit and must keep exporting above it.
"""

from typing import Any

import pytest

from core.bess.tests.helpers import run_scenario_realized

# 1-phase, 230 V, 20 A -> 4.6 kWh per hourly period, well under the battery's
# 10 kW discharge rate, so the uncapped plan would export far above it.
EXPORT_CAP_KWH = 230 * 20 * 1.0 * 1 / 1000.0

EXPORT_CAP_SCENARIO: dict[str, Any] = {
    "battery": {
        "max_soe_kwh": 20.0,
        "min_soe_kwh": 1.0,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 10.0,
        "efficiency_charge": 1.0,
        "efficiency_discharge": 1.0,
        "cycle_cost_per_kwh": 0.0,
        "initial_soe": 20.0,
    },
    "home": {
        "voltage": 230,
        "max_fuse_current": 20,
        "phase_count": 1,
        "safety_margin": 1.0,
        "power_monitoring_enabled": True,
        "fuse_limits_export": True,
    },
    # One lucrative export hour (period 2): uncapped, the DP dumps the full
    # 10 kW discharge into it.
    "buy_price": [1.0, 1.0, 1.0, 1.0],
    "sell_price": [0.1, 0.1, 5.0, 0.1],
    "home_consumption": [0.5, 0.5, 0.5, 0.5],
    "solar_production": [0.0, 0.0, 0.0, 0.0],
    "period_duration_hours": 1.0,
}


def test_grid_export_stays_within_fuse_cap() -> None:
    """Battery export into a high sell price must stop at the fuse limit, and
    the plan must still execute exactly as planned (R == P)."""
    result, realized_cost = run_scenario_realized(EXPORT_CAP_SCENARIO)

    assert realized_cost == pytest.approx(
        result.economic_summary.battery_solar_cost, abs=0.01
    ), "Plan is not faithfully executable (R != P)"

    for t, period in enumerate(result.period_data):
        assert period.energy.grid_exported <= EXPORT_CAP_KWH + 1e-6, (
            f"period {t}: grid export {period.energy.grid_exported:.2f} kWh "
            f"exceeds the fuse cap {EXPORT_CAP_KWH:.2f} kWh"
        )

    export_period = result.period_data[2]
    assert export_period.energy.grid_exported >= EXPORT_CAP_KWH - 0.11, (
        f"export {export_period.energy.grid_exported:.2f} kWh is well under "
        f"the cap {EXPORT_CAP_KWH:.2f} kWh -- the cap should limit the "
        "discharge, not suppress it"
    )


# A full battery and a solar surplus larger than the cap in the first period,
# so there is no earlier period to make room in: nothing can bring export
# under the fuse limit, and the cap must keep the least-export action rather
# than empty the candidate set.
UNMEETABLE_EXPORT_CAP_SCENARIO = {
    **EXPORT_CAP_SCENARIO,
    "sell_price": [1.0, 1.0, 1.0, 1.0],
    "solar_production": [8.0, 0.0, 0.0, 0.0],
}


def test_export_cap_constrains_rather_than_raises_when_no_action_can_meet_it() -> None:
    result, realized_cost = run_scenario_realized(UNMEETABLE_EXPORT_CAP_SCENARIO)

    assert realized_cost == pytest.approx(
        result.economic_summary.battery_solar_cost, abs=0.01
    ), "Plan is not faithfully executable (R != P)"

    surplus_period = result.period_data[0]
    assert surplus_period.energy.grid_exported > EXPORT_CAP_KWH, (
        "fixture no longer exercises the unmeetable-cap path: export "
        f"{surplus_period.energy.grid_exported:.2f} kWh is within the cap"
    )
    assert surplus_period.energy.battery_discharged == pytest.approx(0.0, abs=1e-9)


# Fuse protection on, export limiting left off (the default): the fuse fields
# carry an import-only limit, e.g. a grid operator's, and export above it is
# allowed.
IMPORT_ONLY_SCENARIO = {
    **EXPORT_CAP_SCENARIO,
    "home": {**EXPORT_CAP_SCENARIO["home"], "fuse_limits_export": False},
}


def test_export_is_not_capped_unless_the_user_opts_in() -> None:
    result, realized_cost = run_scenario_realized(IMPORT_ONLY_SCENARIO)

    assert realized_cost == pytest.approx(
        result.economic_summary.battery_solar_cost, abs=0.01
    ), "Plan is not faithfully executable (R != P)"

    export_period = result.period_data[2]
    assert export_period.energy.grid_exported > EXPORT_CAP_KWH + 1.0, (
        f"export {export_period.energy.grid_exported:.2f} kWh was held to the "
        f"fuse limit {EXPORT_CAP_KWH:.2f} kWh although export limiting is off"
    )


def test_export_limiting_is_off_by_default() -> None:
    from core.bess.settings import HomeSettings

    assert HomeSettings().fuse_limits_export is False
