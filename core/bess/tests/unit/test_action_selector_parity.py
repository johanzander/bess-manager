"""Bit-parity gate for the single action selector (`action_selector.py`).

Phase 1 of `docs/superpowers/plans/2026-08-09-optimizer-target-architecture.md`
(principle P1, `docs/agents/optimizer-architecture.md`) collapsed the two
hand-mirrored enumerate/evaluate/select functions -- the grid replay's
`_best_action_at_continuous_state` and the PWL replay's
`_pwl_best_action_at_continuous_state` -- into one `select_action`
parameterized by a continuation-value evaluator. That extraction is only
worth anything if it changed nothing, so every fixture's emitted actions,
SOE trajectory and optimized cost are pinned bit-identically against
outputs captured from `origin/main` before the refactor started.

**The plan is bit-identical; the cost carries 1e-9 (changed 2026-08-11).**
The original rule here was bit-identical everywhere, on the argument that an
extraction reordering a floating-point sum is a behavior change this phase
was not allowed to make and a tolerance would hide it. That still holds for
`actions`, `intents` and `soe_trajectory`, which remain `==`.

It does not survive contact with `battery_solar_cost`, which turned out not
to be reproducible across environments: on one commit, py3.12.13/numpy 2.5.2
and py3.13 reproduce every golden exactly while py3.11.15/numpy 2.4.6
differs on 27 of 36 by up to 5.7e-14 SEK, with the plan bit-identical in all
three. A gate that goes red on a numpy bump with no behavior change does not
become more honest by being strict -- it trains the reflex to re-capture,
which is how a real change gets absorbed. The reordering the old rule
existed to catch still fails this test, via the plan fields, because a sum
reordering that changes a decision changes the decision.

**Golden lifecycle.** These goldens pin *refactor* parity. Every later
behavior-changing phase (Phase 2 onward) regenerates them
(`scripts/capture_selector_goldens.py`) as part of its measured-delta
step and states the regeneration in its PR body. This test is never
deleted or skipped -- a phase that cannot regenerate the goldens has not
measured its delta.
"""

import json

import pytest

from core.bess.tests.unit.golden_capture import (
    GOLDEN_DIR,
    capture_fixture,
    fixture_names,
)

pytestmark = pytest.mark.slow


def test_every_fixture_has_a_golden():
    """A fixture added without a golden would silently escape the gate."""
    missing = [
        name for name in fixture_names() if not (GOLDEN_DIR / f"{name}.json").exists()
    ]
    assert missing == [], (
        f"fixtures without a parity golden: {missing}. Run "
        "`.venv/bin/python scripts/capture_selector_goldens.py`."
    )


@pytest.mark.parametrize("name", fixture_names())
def test_selector_refactor_is_bit_identical(name):
    golden = json.loads((GOLDEN_DIR / f"{name}.json").read_text())
    actual = capture_fixture(name)

    assert actual["actions"] == golden["actions"]
    assert actual["intents"] == golden["intents"]
    assert (
        actual["intra_period_discharge_allowed"]
        == golden["intra_period_discharge_allowed"]
    )
    assert actual["soe_trajectory"] == golden["soe_trajectory"]

    # Cost gets a tolerance where the plan does not, because it is the one
    # field whose exact bits are not reproducible across environments.
    # Measured 2026-08-11 on the same commit: py3.12.13/numpy 2.5.2 and
    # py3.13 (CI) both reproduce every golden exactly, while py3.11.15/numpy
    # 2.4.6 differs on 27 of 36 fixtures by 1e-16 to 5.7e-14 SEK -- with
    # `actions` and `soe_trajectory` bit-identical on all 36 in every
    # environment. That is summation order in a numpy reduction, not
    # behaviour. `backend/requirements.txt` now pins `numpy==2.5.2` so a bump
    # cannot move reported costs silently; this tolerance is the other half,
    # covering the interpreter and platform the pin does not fix.
    #
    # 1e-9 is ~17,000x the largest observed noise and ~1e7 times finer than
    # the smallest genuine cost movement this corpus has ever recorded
    # (0.0181 SEK), so nothing real can hide under it. The plan itself stays
    # bit-exact: a reordered float sum that actually changes a decision moves
    # `actions` or `intents`, which are compared with `==`.
    #
    assert actual["battery_solar_cost"] == pytest.approx(
        golden["battery_solar_cost"], abs=1e-9
    )
