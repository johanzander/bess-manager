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

Bit-identical, not `approx`: an extraction that reorders a floating-point
sum is a behavior change this phase is not allowed to make, and a
tolerance would hide exactly that.

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
    assert actual["soe_trajectory"] == golden["soe_trajectory"]
    assert actual["battery_solar_cost"] == golden["battery_solar_cost"]
