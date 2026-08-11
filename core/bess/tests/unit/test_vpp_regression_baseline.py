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
        f"fixtures with no VPP baseline: {missing}. Add them with "
        "`scripts/capture_vpp_baseline.py --add-new` (records today's plan "
        "only, `plan: null`); a full re-baseline is NOT the remedy here."
    )


@pytest.mark.parametrize("name", fixture_names())
def test_vpp_execution_of_the_baseline_plan_is_unchanged(name):
    """Re-executing v10.0.2's recorded plan must produce the same commands
    and the same realized cost.

    Pins the *execution model* -- the command mapping and the VPP power
    model. Fails if `_intent_to_vpp` changes, if the firmware-priority model
    changes, or if the accounting underneath moves. It cannot fail because
    the DP planned something new, since the plan is read from the baseline
    rather than recomputed -- that is `test_current_plan_is_pinned`'s job.
    """
    baseline = _baseline()
    assert name in baseline, (
        f"{name} has no VPP baseline entry. Add it with "
        "`scripts/capture_vpp_baseline.py --add-new`."
    )
    entry = baseline[name]
    if entry["plan"] is None:
        pytest.skip(
            "fixture added after v10.0.2 — there is no released plan to "
            "replay; test_current_plan_is_pinned covers its execution"
        )
    replayed = simulate_plan(name, entry["plan"])

    assert replayed["commands"] == entry["commands"]
    assert replayed["realized_cost"] == pytest.approx(entry["realized_cost"], abs=1e-9)
    assert replayed["soe_trajectory"] == pytest.approx(
        entry["soe_trajectory"], abs=1e-9
    )


@pytest.mark.parametrize("name", fixture_names())
def test_current_plan_is_pinned(name):
    """Today's plan, and its VPP execution, must match what was recorded.

    This is the half that actually enforces "no regression from beta for
    Growatt VPP" on every fixture. An earlier revision asserted only *which*
    fixtures had already diverged from v10.0.2 -- since 35 of 36 had, any
    further regression on those 35 kept them in the same set and passed
    silently. Pinning the plan itself closes that.

    Re-pin in the PR that changes behaviour deliberately, quoting the
    measured delta, exactly as the golden parity gate requires.
    """
    baseline = _baseline()
    assert name in baseline, (
        f"{name} has no VPP baseline entry. Add it with "
        "`scripts/capture_vpp_baseline.py --add-new`."
    )
    entry = baseline[name]

    assert capture_plan(name) == entry["current_plan"], (
        "the DP now plans this fixture differently. If deliberate, re-pin "
        "and state the measured VPP delta in the PR."
    )
    replayed = simulate_plan(name, entry["current_plan"])
    assert replayed["commands"] == entry["current"]["commands"]
    assert replayed["realized_cost"] == pytest.approx(
        entry["current"]["realized_cost"], abs=1e-9
    )
    # The SoE path too, not just commands and total cost: an execution-model
    # change can shift the trajectory while netting out in both (an efficiency
    # application moved, or the zero-delivery hold regressing into a charge).
    assert replayed["soe_trajectory"] == pytest.approx(
        entry["current"]["soe_trajectory"], abs=1e-9
    )


def test_drift_from_the_released_version_is_recorded():
    """How far today's plans have moved from v10.0.2.

    Compares the artefact's two plan halves. That is not the same weak check
    an earlier revision made -- it caught a sloppy re-baseline only if someone
    hand-edited the file -- because `test_current_plan_is_pinned` now
    recomputes `capture_plan` per fixture and asserts it equals
    `current_plan`. With that in place, `capture_plan(name) != plan` and
    `current_plan != plan` are the same predicate whenever the suite is green,
    so recomputing here bought nothing but 36 more DP solves per run. The
    re-baseline it is meant to catch (both halves regenerated together, which
    would collapse `moved` to 0) still fails this assertion.

    Deliberate changes since the tag (Phase 2's preference table, #512's finer
    grid, #524's TOU gate, #526's authorization) already moved most of the
    corpus, so this is a recorded quantity rather than a pass/fail on equality.

    Counted over the fixtures that *have* a v10.0.2 reference plan, not over
    the whole corpus: a fixture added later has no such plan (`plan: null`)
    and cannot have drifted from the tag, so it must not shift this count and
    force a full re-baseline -- the one remedy `capture_vpp_baseline.py`
    warns against, since it discards the drift signal this test exists to
    hold.
    """
    baseline = _baseline()
    missing = [n for n in fixture_names() if n not in baseline]
    assert missing == [], (
        f"fixtures with no VPP baseline: {missing}. Add them with "
        "`scripts/capture_vpp_baseline.py --add-new`."
    )

    referenced = [n for n in fixture_names() if baseline[n]["plan"] is not None]
    moved = [
        name
        for name in referenced
        if baseline[name]["current_plan"] != baseline[name]["plan"]
    ]
    assert len(moved) == 35, (
        f"{len(moved)} of {len(referenced)} v10.0.2-referenced fixtures now "
        "plan differently from the tag. If a phase did this deliberately, "
        "re-pin with the measured delta."
    )
