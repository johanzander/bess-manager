"""The period after a spliced PWL window must report flows derived from the
state the splice actually left it in.

A window owns periods `[start, end)` but writes the SOE at `end` -- its pinned
exit state. The period AT `end` is not re-solved, so it keeps the flow record
the selection loop derived from its PRE-splice start SOE. Once
`_replay_accounting_pass` stopped re-deriving flows (Phase 3 Task 2), that
record and the reported `battery_soe_start` could describe different states.

`resolve_pwl_window` only guarantees the exit lands within
`_end_soe_pin_tolerance`, not exactly. Every corpus fixture happens to land it
to ~1e-15, so no fixture exercises this -- the pin is perturbed deliberately
here rather than waiting for one to drift.

The boundary period must be IDLE-with-passive-charging for this to
discriminate at all: `_idle_battery_flows` derives `battery_charged` from the
SOE delta, so a stale record is visible. A discharging boundary computes
`battery_discharged` from the action alone, which no splice can move -- such a
period cannot detect the bug, and a test written against one would pass
whether or not the fix exists.
"""

import json

import pytest

import core.bess.dp_battery_algorithm as dpa
import core.bess.pwl_window_dp as pwl
from core.bess.tests.helpers import _scenario_inputs
from core.bess.tests.unit.golden_capture import DATA_DIR

pytestmark = pytest.mark.slow

# Measured 2026-08-10: this fixture splices one window (0, 6) and its boundary
# period 6 is IDLE with passive solar charging.
# Re-measured for #602: the concave terminal row moves the value function, so
# the spliced window now exits at 5. The fixture still satisfies this test's
# stated precondition -- period 5 is IDLE with passive solar charging -- which
# is what makes it still able to detect a stale flow record.
FIXTURE = "synthetic_consumption_efficient"
BOUNDARY_PERIOD = 5

# Well inside the pin's tolerance band, far above float noise.
PIN_DRIFT_KWH = 0.004


def _run(drift):
    scenario = json.loads((DATA_DIR / f"{FIXTURE}.json").read_text())
    inputs = _scenario_inputs(scenario)
    settings = inputs["battery_settings"]
    real_resolve = pwl.resolve_pwl_window

    def drifting_resolve(*args, **kwargs):
        resolution = real_resolve(*args, **kwargs)
        if not resolution or not drift:
            return resolution
        action, next_soe, flows = resolution[-1]
        drifted = max(settings.min_soe_kwh, next_soe - drift)
        return [*resolution[:-1], (action, drifted, flows)]

    pwl.resolve_pwl_window = drifting_resolve
    try:
        return dpa.optimize_battery_schedule(**inputs), settings
    finally:
        pwl.resolve_pwl_window = real_resolve


def test_boundary_period_flows_track_the_spliced_exit_soe():
    """Move the window's exit SOE; the next period's reported charge must move
    with it, because it is passively absorbing solar into a battery that now
    starts somewhere else."""
    base, settings = _run(drift=0.0)
    drifted, _ = _run(drift=PIN_DRIFT_KWH)

    b = base.period_data[BOUNDARY_PERIOD].energy
    d = drifted.period_data[BOUNDARY_PERIOD].energy

    assert d.battery_charged > 0, (
        "fixture no longer has a passively-charging boundary period, so this "
        "test can no longer detect a stale record -- re-pick the fixture"
    )
    assert d.battery_soe_start == pytest.approx(
        b.battery_soe_start - PIN_DRIFT_KWH, abs=1e-9
    ), "the perturbation did not reach the boundary period's start SOE"

    # Starting PIN_DRIFT_KWH lower with the same end state means absorbing
    # that much more, grossed up by charge efficiency.
    expected = b.battery_charged + PIN_DRIFT_KWH / settings.efficiency_charge
    assert d.battery_charged == pytest.approx(expected, abs=1e-6), (
        "the boundary period reports charge derived from its PRE-splice start "
        "SOE while reporting the post-splice one -- a stale flow record"
    )
