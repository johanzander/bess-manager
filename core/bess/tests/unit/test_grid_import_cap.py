"""Plan-faithfulness regression for the DP's grid-import capacity constraint.

Issue #429: the DP had no ceiling on grid_imported, so it could plan to leave
the battery idle and import an unbounded load through a load-first spike --
a plan the household's fuse cannot physically deliver. See
docs/agents/bess-knowledge.md and the issue for the economics/behavior this
pins.
"""

import pytest

from core.bess.dp_battery_algorithm import _effective_import_cap_kwh
from core.bess.settings import HomeSettings
from core.bess.tests.helpers import run_scenario_realized


def test_effective_import_cap_scales_with_phase_count():
    """Each phase is an independent fuse, so the cap scales with phase_count
    -- matching HomePowerMonitor, which authorizes the battery up to its full
    max_charge_power_w (not a single phase's worth) on a balanced, unloaded
    3-phase house (see _effective_import_cap_kwh's docstring)."""
    single_phase = HomeSettings(
        voltage=230,
        max_fuse_current=22,
        phase_count=1,
        safety_margin=1.0,
        power_monitoring_enabled=True,
    )
    three_phase = HomeSettings(
        voltage=230,
        max_fuse_current=22,
        phase_count=3,
        safety_margin=1.0,
        power_monitoring_enabled=True,
    )
    cap_1p = _effective_import_cap_kwh(single_phase, dt=1.0)
    cap_3p = _effective_import_cap_kwh(three_phase, dt=1.0)

    assert cap_1p == pytest.approx(230 * 22 * 1.0 / 1000.0)
    assert cap_3p == pytest.approx(cap_1p * 3)


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
        # 3-phase on purpose: the cap must scale with phase_count -- each
        # phase is an independent fuse (see _effective_import_cap_kwh's
        # docstring and test_effective_import_cap_scales_with_phase_count
        # above). A regression that drops the phase_count multiplier would
        # cut this cap to a third and force far more discharge than the
        # fuses actually require.
        "phase_count": 3,
        "safety_margin": 1.0,
        "power_monitoring_enabled": True,
    },
    # Flat, cheap buy price during the load spike (period 2) and a much
    # higher sell price later (period 3) give the DP a genuine economic
    # reason to import up to the cap rather than discharge -- preserving SOE
    # for the lucrative period-3 export is worth more than avoiding the
    # (otherwise cheap) grid import. The spike (20 kWh) exceeds even the
    # phase_count-scaled cap (~15.2 kWh), so some discharge is still required.
    "buy_price": [1.0, 1.0, 1.0, 1.0],
    "sell_price": [0.1, 0.1, 0.1, 5.0],
    "home_consumption": [1.0, 1.0, 20.0, 1.0],
    "solar_production": [0.0, 0.0, 0.0, 0.0],
    "period_duration_hours": 1.0,
}

IMPORT_CAP_KWH = (230 * 22 * 1.0 * 3 / 1000.0) * 1.0  # ~15.18 kWh, phase_count=3


def test_grid_import_stays_within_fuse_cap():
    """A load spike exceeding the fuse-derived import cap must be partly
    covered by battery discharge, not left as unconstrained grid import --
    but the DP should use the full phase_count-scaled cap rather than
    over-discharging against a too-conservative single-phase ceiling."""
    result, realized_cost = run_scenario_realized(IMPORT_CAP_SCENARIO)

    assert realized_cost == pytest.approx(
        result.economic_summary.battery_solar_cost, abs=0.01
    ), "Plan is not faithfully executable (R != P)"

    spike_period = result.period_data[2]
    assert spike_period.energy.grid_imported <= IMPORT_CAP_KWH + 0.01, (
        f"Grid import {spike_period.energy.grid_imported:.2f} kWh exceeds "
        f"fuse cap {IMPORT_CAP_KWH:.2f} kWh"
    )
    assert spike_period.energy.grid_imported >= IMPORT_CAP_KWH - 0.5, (
        f"Grid import {spike_period.energy.grid_imported:.2f} kWh is well "
        f"under the phase_count-scaled cap {IMPORT_CAP_KWH:.2f} kWh -- the "
        "DP is over-discharging against a too-conservative cap"
    )
