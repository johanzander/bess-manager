"""Growatt VPP regression baseline against v10.0.2 (#539).

Growatt VPP is in real production use with no known bugs on beta, and until
this existed there was no way to tell whether a change moved its behaviour:
`inverter_simulator` is Growatt MIN/cloud **TOU** only, so the scenario
corpus, `run_scenario_realized` and the whole R == P harness cover the TOU
path and say nothing about VPP. "No regression from beta" was therefore
unenforceable for it -- a requirement with no instrument behind it.

The baseline is **v10.0.2's plans executed through today's VPP model**. That
split holds the execution model fixed, so a failure isolates a planner
change rather than leaving it ambiguous, and it is the only way to reach the
tag at all (`vpp_simulator` needs `_period_flows`, which arrived with
Phase 3).

**A delta here means "behaviour changed", never "behaviour got worse."** At
15-minute point forecasts there is no within-period load spike, so this can
model the intra-period discharge gate's cost but never its benefit -- see
`vpp_simulator`'s module docstring for the measured size of that bias. The
pin is a change detector; the economic question needs different evidence.

**Plans have already moved since v10.0.2, deliberately** -- Phase 2's
preference table, #512's finer grid, #524's TOU gate and #526's
authorization each changed what the DP plans, on 35 of 36 fixtures. So this
does not assert equality with the tag. It asserts that the *set* of
fixtures whose VPP behaviour differs is the one recorded here, so a new
divergence shows up as a new name rather than hiding inside an aggregate.
"""

import json

import pytest

from core.bess.tests.unit.vpp_capture import (
    BASELINE_PATH,
    capture_plan,
    fixture_names,
    simulate_plan,
)

pytestmark = pytest.mark.slow


def _baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text())["fixtures"]


def test_every_fixture_has_a_vpp_baseline():
    """A fixture added without a baseline entry silently escapes the pin."""
    missing = [name for name in fixture_names() if name not in _baseline()]
    assert missing == [], (
        f"fixtures with no VPP baseline: {missing}. Regenerate per "
        "`scripts/capture_vpp_baseline.py`."
    )


@pytest.mark.parametrize("name", fixture_names())
def test_vpp_execution_of_the_baseline_plan_is_unchanged(name):
    """Re-executing v10.0.2's recorded plan must produce the same commands
    and the same realized cost.

    This is the half that pins the *execution model* -- the command mapping
    and the VPP power model. It fails if `_intent_to_vpp` changes, if the
    simulator's firmware-priority model changes, or if the accounting
    underneath moves. It cannot fail because the DP planned something new,
    since the plan is read from the baseline rather than recomputed.
    """
    entry = _baseline()[name]
    replayed = simulate_plan(name, entry["plan"])

    assert replayed["commands"] == entry["commands"]
    assert replayed["realized_cost"] == pytest.approx(entry["realized_cost"], abs=1e-9)
    assert replayed["soe_trajectory"] == pytest.approx(
        entry["soe_trajectory"], abs=1e-9
    )


def test_the_set_of_fixtures_whose_plan_moved_since_v10_0_2_is_pinned():
    """Which fixtures the optimizer now plans differently from the released
    version is itself the regression signal.

    Deliberate changes since v10.0.2 (Phase 2, #512, #524, #526) already moved
    35 of 36, so the useful assertion is not "nothing changed" but "the same
    ones changed". A fixture appearing or disappearing from this set means a
    change reached VPP planning that nobody recorded -- which is exactly what
    "no regression from beta for Growatt VPP" needs to catch.

    When a phase deliberately changes more, re-pin this list in that phase's
    PR **with the measured delta stated**, the same discipline the golden
    parity gate uses.
    """
    baseline = _baseline()
    moved = sorted(
        name for name in fixture_names() if capture_plan(name) != baseline[name]["plan"]
    )
    unchanged = sorted(set(fixture_names()) - set(moved))

    assert unchanged == ["historical_2025_01_05_no_spread_no_solar"], (
        "the set of fixtures still planning exactly as v10.0.2 changed. "
        f"Now unchanged: {unchanged}. If a phase did this deliberately, "
        "re-pin here and state the measured delta in the PR."
    )
    assert len(moved) == 35
