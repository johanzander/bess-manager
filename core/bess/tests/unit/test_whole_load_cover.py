"""#884: on a platform whose LOAD_SUPPORT is the inverter's own Self Use, the
plan may only cover the whole house deficit or hold -- never part of it.

Since #872 a Solis LOAD_SUPPORT period opens no discharge slot, so Self Use
runs and covers the whole net load from the battery (up to its maximum
discharge power, down to min SOC). A plan that discharges *part* of the
deficit and imports the rest describes a delivery the hardware will not make:
SOC falls faster than planned and the period's savings are misreported.

**Why these tests assert the plan, not the realized outcome.** The outcome
would be the stronger check (R == P via `run_scenario_realized`), but
`simulation/inverter_simulator` models only Growatt TOU hardware -- there is
no Solis execution model to run a plan through. So the assertion is the
plan-level property Self Use makes exact: every planned discharge in a
deficit period is either zero or the whole deliverable cover. Upgrade this to
R == P once a Solis execution model exists.
"""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from core.bess.dp_battery_algorithm import (
    _run_dynamic_programming,
    optimize_battery_schedule,
)
from core.bess.dp_constants import POWER_STEP_KW, SOE_STEP_KWH
from core.bess.execution_model import (
    DEFAULT_CAPABILITIES,
    DISCHARGE_RATE_ABSENT,
    LOAD_SUPPORT_WHOLE_LOAD,
    PlatformCapabilities,
)
from core.bess.pwl_window_dp import _backward_discharge_levels, _pwl_candidate_values_at
from core.bess.solis_modbus_controller import SolisModbusController
from core.bess.terminal_value import TerminalValueCurve
from core.bess.tests.helpers import _scenario_inputs, make_battery_settings

_FIXTURE = Path(__file__).parent / "fixtures" / "solis_issue_884_optimizer_inputs.json"

# Energy tolerance for "covers the whole deficit". Well below the 1% lattice
# step on this 3 kW battery (0.03 kW x 0.25 h = 0.0075 kWh), so a plan sitting
# one lattice step under the load -- 25 such periods before the fix -- fails.
_COVER_TOL_KWH = 1e-6


def _solis_plan(inputs: dict) -> Any:
    settings = inputs["battery_settings"]
    capabilities = PlatformCapabilities.from_controller(
        SolisModbusController(settings), settings
    )
    return optimize_battery_schedule(**inputs, capabilities=capabilities)


def _partial_covers(result: Any, settings: Any, dt: float) -> list[Any]:
    """(period, planned discharge, deliverable cover) for every period that
    discharges some but not all of what Self Use would deliver."""
    partial = []
    for i, pd in enumerate(result.period_data):
        e = pd.energy
        deficit = max(0.0, e.home_consumption - e.solar_production)
        full_cover = min(deficit, settings.max_discharge_power_kw * dt)
        if 0.0 < e.battery_discharged < full_cover - _COVER_TOL_KWH:
            partial.append((i, e.battery_discharged, full_cover))
    return partial


def test_solis_plan_never_schedules_a_partial_load_cover() -> None:
    """The #869 reporter's own day. Before the fix 66 of 74 LOAD_SUPPORT
    periods planned a partial cover, 41 of them by far more than lattice
    rounding (median shortfall 0.87 kW)."""
    inputs = _scenario_inputs(json.loads(_FIXTURE.read_text()))
    settings = inputs["battery_settings"]
    dt = inputs["period_duration_hours"]

    result = _solis_plan(inputs)

    load_support = [
        pd
        for pd in result.period_data
        if pd.decision.strategic_intent == "LOAD_SUPPORT"
    ]
    # Not vacuous: the battery still serves the house on this day, it just
    # does so in whole periods.
    assert len(load_support) >= 20, (
        f"expected the plan to keep covering load from the battery, got only "
        f"{len(load_support)} LOAD_SUPPORT periods"
    )
    partial = _partial_covers(result, settings, dt)
    assert partial == [], (
        f"{len(partial)} periods plan a partial load cover Self Use cannot "
        f"deliver (period, planned kWh, whole cover kWh): {partial[:5]}"
    )


def test_whole_load_cover_is_capped_at_the_battery_maximum_power() -> None:
    """When the house draws more than the battery can give, Self Use delivers
    the battery's full power and the grid supplies the rest. That is a whole
    cover, not a partial one, and the plan must still be able to choose it --
    otherwise a Solis battery could never discharge into an expensive
    high-load period."""
    settings = make_battery_settings(max_discharge_power_kw=3.0, cycle_cost_per_kwh=0.0)
    dt = 0.25
    horizon = 4
    result = _solis_plan(
        {
            "buy_price": [3.0] * horizon,
            "sell_price": [0.1] * horizon,
            # 5 kW of house load against a 3 kW battery.
            "home_consumption": [5.0 * dt] * horizon,
            "solar_production": [0.0] * horizon,
            "battery_settings": settings,
            "initial_soe": settings.max_soe_kwh,
            "period_duration_hours": dt,
        }
    )
    first = result.period_data[0]
    assert first.decision.strategic_intent == "LOAD_SUPPORT"
    assert first.energy.battery_discharged == pytest.approx(3.0 * dt, abs=1e-9)
    assert first.energy.grid_imported == pytest.approx(2.0 * dt, abs=1e-9)


# ── The backward passes value the same action set (#884) ─────────────────────
#
# The replay filters partial covers out of its candidates, so a backward pass
# that still admitted them would not change the actions chosen on most days --
# it would promise a value the replay cannot reach, and steer earlier periods
# towards rationing that never happens. Each backward pass is checked directly,
# on one period where a partial cover is the best ceiling-hardware action:
#
#   start: 3.0 kWh usable; house deficit 2.0 kWh; buy 1.0, sell 0.0
#   continuation: 5.0 per usable kWh up to 1.5 kWh, nothing above
#
#   hold          -2.0 import          + 1.5 x 5.0 = 5.5   <- whole_load best
#   partial 1.5   -0.5 import          + 1.5 x 5.0 = 7.0   <- ceiling best
#   whole cover    0.0                 + 1.0 x 5.0 = 5.0
#
# Discharge efficiency 1.0 and no cycle cost keep every candidate's next state
# on the SOE grid, so the coarse pass's value is exact rather than interpolated.

_HEAD_RATE = 5.0
_KNEE_KWH = 1.5
_START_USABLE_KWH = 3.0
_DEFICIT_KWH = 2.0
_WHOLE_LOAD = PlatformCapabilities(
    discharge_rate_semantics=DISCHARGE_RATE_ABSENT,
    load_support_delivery=LOAD_SUPPORT_WHOLE_LOAD,
)


def _one_period_battery() -> Any:
    return make_battery_settings(efficiency_discharge=1.0, cycle_cost_per_kwh=0.0)


@pytest.mark.parametrize(
    ("capabilities", "expected"),
    [(DEFAULT_CAPABILITIES, 7.0), (_WHOLE_LOAD, 5.5)],
    ids=["ceiling_partial_cover", "whole_load_hold"],
)
def test_grid_backward_pass_does_not_value_a_partial_cover(
    capabilities: Any, expected: Any
) -> None:
    battery = _one_period_battery()
    V = _run_dynamic_programming(
        horizon=1,
        buy_price=[1.0],
        sell_price=[0.0],
        home_consumption=[_DEFICIT_KWH],
        battery_settings=battery,
        dt=1.0,
        solar_production=[0.0],
        terminal_curve=TerminalValueCurve(head_rate=_HEAD_RATE, knee_kwh=_KNEE_KWH),
        capabilities=capabilities,
    )
    start = round(_START_USABLE_KWH / SOE_STEP_KWH)
    assert V[0][start] == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize(
    ("capabilities", "expected"),
    [(DEFAULT_CAPABILITIES, 7.0), (_WHOLE_LOAD, 5.5)],
    ids=["ceiling_partial_cover", "whole_load_hold"],
)
def test_pwl_backward_pass_does_not_value_a_partial_cover(
    capabilities: Any, expected: Any
) -> None:
    battery = _one_period_battery()
    min_soe = battery.min_soe_kwh
    continuation = (
        np.array([min_soe, min_soe + _KNEE_KWH, battery.max_soe_kwh]),
        np.array([0.0, _KNEE_KWH * _HEAD_RATE, _KNEE_KWH * _HEAD_RATE]),
    )
    power_row = np.concatenate(
        ([0.0], -_backward_discharge_levels(battery, capabilities), [POWER_STEP_KW])
    )
    value = _pwl_candidate_values_at(
        np.array([min_soe + _START_USABLE_KWH]),
        0,
        continuation,
        power_row,
        ([1.0], [0.0], [_DEFICIT_KWH], [0.0]),
        battery,
        1.0,
        None,
        None,
        capabilities,
    )[0]
    assert value == pytest.approx(expected, abs=1e-6)
