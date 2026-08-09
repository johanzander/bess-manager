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


# Same house and spike, but the battery starts empty, so no discharge action
# can bring the spike period's import under the fuse cap. This is the
# "constrain, don't raise" half of #429 -- the half the scenario above never
# reaches, because there the battery can always meet the cap.
UNMEETABLE_CAP_SCENARIO = {
    **IMPORT_CAP_SCENARIO,
    "battery": {**IMPORT_CAP_SCENARIO["battery"], "initial_soe": 1.0},
    "buy_price": [5.0, 5.0, 1.0, 1.0],
}


def test_cap_constrains_rather_than_raises_when_no_action_can_meet_it():
    """When the house load alone exceeds the fuse cap and the battery cannot
    help, the cap must constrain the choice among the least-bad actions, not
    eliminate every candidate (#429).

    The optimizer has to keep planning -- the load is served either way, and
    the fuse's real behavior is not the DP's to simulate. If the import
    filter ever stops flooring its threshold at the minimum import any
    candidate actually achieves, this period's candidate list empties and
    selection dies on an empty list instead of returning the honest plan.
    The expensive early prices keep the battery empty at the spike, so no
    discharge is available to duck under the cap.
    """
    result, realized_cost = run_scenario_realized(UNMEETABLE_CAP_SCENARIO)

    assert realized_cost == pytest.approx(
        result.economic_summary.battery_solar_cost, abs=0.01
    ), "Plan is not faithfully executable (R != P)"

    spike_period = result.period_data[2]
    assert spike_period.energy.grid_imported > IMPORT_CAP_KWH, (
        "fixture no longer exercises the unmeetable-cap path: import "
        f"{spike_period.energy.grid_imported:.2f} kWh is within the cap "
        f"{IMPORT_CAP_KWH:.2f} kWh"
    )
    assert spike_period.energy.battery_soe_start == pytest.approx(
        UNMEETABLE_CAP_SCENARIO["battery"]["min_soe_kwh"], abs=0.05
    ), "fixture no longer exercises an empty battery at the spike"
