"""Plan-faithfulness regression for the DP's grid-import capacity constraint.

Issue #429: the DP had no ceiling on grid_imported, so it could plan to leave
the battery idle and import an unbounded load through a load-first spike --
a plan the household's fuse cannot physically deliver. See
docs/agents/bess-knowledge.md and the issue for the economics/behavior this
pins.
"""

import pytest

from core.bess.tests.helpers import run_scenario_realized

IMPORT_CAP_SCENARIO = {
    "battery": {
        "max_soe_kwh": 10.0,
        "min_soe_kwh": 1.0,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 10.0,
        "efficiency_charge": 1.0,
        "efficiency_discharge": 1.0,
        "cycle_cost_per_kwh": 0.40,
        "initial_soe": 10.0,
    },
    "home": {
        "voltage": 230,
        "max_fuse_current": 22,
        # 3-phase on purpose: the cap must NOT scale with phase_count --
        # HomePowerMonitor gates on the single worst-loaded phase, not
        # phase-summed power (see _effective_import_cap_kwh's docstring).
        # A regression that reintroduces a phase_count multiplier would
        # triple this cap and let the full 10 kWh spike through unconstrained.
        "phase_count": 3,
        "safety_margin": 1.0,
        "power_monitoring_enabled": True,
    },
    # Flat, cheap buy price during the load spike (period 2) and a much
    # higher sell price later (period 3) give the DP a genuine economic
    # reason to import unbounded rather than discharge -- preserving SOE
    # for the lucrative period-3 export is worth more than avoiding the
    # (otherwise cheap) grid import. Confirmed against the pre-fix DP: with
    # the cap disabled, period 2 imports the full 10 kWh load and the
    # battery stays untouched until period 3's export.
    "buy_price": [1.0, 1.0, 1.0, 1.0],
    "sell_price": [0.1, 0.1, 0.1, 5.0],
    "home_consumption": [1.0, 1.0, 10.0, 1.0],
    "solar_production": [0.0, 0.0, 0.0, 0.0],
    "period_duration_hours": 1.0,
}

IMPORT_CAP_KWH = (230 * 22 * 1.0 / 1000.0) * 1.0  # ~5.06 kWh, phase_count-independent


def test_grid_import_stays_within_fuse_cap():
    """A load spike exceeding the fuse-derived import cap must be partly
    covered by battery discharge, not left as unconstrained grid import."""
    result, realized_cost = run_scenario_realized(IMPORT_CAP_SCENARIO)

    assert realized_cost == pytest.approx(
        result.economic_summary.battery_solar_cost, abs=0.01
    ), "Plan is not faithfully executable (R != P)"

    spike_period = result.period_data[2]
    assert spike_period.energy.grid_imported <= IMPORT_CAP_KWH + 0.01, (
        f"Grid import {spike_period.energy.grid_imported:.2f} kWh exceeds "
        f"fuse cap {IMPORT_CAP_KWH:.2f} kWh"
    )
