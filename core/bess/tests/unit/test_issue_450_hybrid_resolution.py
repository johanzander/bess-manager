"""End-to-end regression test for #450: the grid DP's SOE grid-snapping
must no longer be able to flip a near-tied window's choice, now that the
hybrid tie-detect/resolve/splice path replaces PR #461's full-MILP fix.

The primary assertion compares the hybrid against the grid DP alone on the
same fixture rather than pinning a magic number, so it keeps discriminating
"hybrid resolution applied" from "regressed to grid-snap noise" even when
unrelated economics changes move both figures. #497 did exactly that: removing
the DP's phantom export revenue shifted every absolute cost on this fixture,
while leaving the hybrid's advantage over grid-only essentially unchanged
(0.01245 SEK, against 0.0124 before). A pinned-number-only test would have
looked like a regression there and told us nothing about the mechanism.

`reward_objective_cost` is the DP's *own* objective, accumulated from each
period's `_compute_reward` return and recomputed by `_replay_accounting_pass`
after the window is spliced. It used to drift from
`economic_summary.battery_solar_cost` (a report rebuilt from
`_build_period_data`'s energy fields) by ~0.0257 SEK on this fixture, which is
why the original test pinned both separately. #497 removed that drift too --
`_build_period_data` now reports the same energy the reward priced, so the two
agree exactly on all 33 fixtures -- and the test asserts that agreement instead
of tolerating it.
"""

from unittest.mock import patch

import pytest

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.terminal_value import TerminalValueCurve
from core.bess.tests.unit.test_scenarios import build_scenario_optimizer_inputs


def _optimize(scenario_name, terminal_value_per_kwh=None):
    _, kwargs = build_scenario_optimizer_inputs(scenario_name)
    if terminal_value_per_kwh is not None:
        kwargs["terminal_curve"] = TerminalValueCurve.flat(terminal_value_per_kwh)
    result = optimize_battery_schedule(**kwargs)

    # Grid DP alone, tie detection suppressed: the behaviour #450 fixed.
    with patch("core.bess.tie_detection.detect_tie_windows", return_value=[]):
        grid_only = optimize_battery_schedule(**kwargs)
    return result, grid_only


def test_hybrid_resolution_improves_on_grid_dp():
    # #450's original reproduction fixture (regression_2026_08_02_043728) no
    # longer near-ties at #512's finer grid -- see the companion test below --
    # so the mechanism is asserted on a fixture that still does. Measured at
    # the 0.1 kW / 0.025 kWh grid: window (14, 19), advantage +0.0600 SEK.
    #
    # Pinned at terminal_value_per_kwh = 0.0 explicitly, which is what this
    # fixture ran at when the advantage above was measured -- it is no longer
    # the fixture's own value, since the corpus was retrofitted onto
    # production-computed terminal values. That retrofit dissolves this
    # window: a nonzero terminal row adds a value gradient at the horizon that
    # breaks the near-tie, and at the fixture's own 1.78386 SEK/kWh the
    # advantage falls to exactly 0.
    #
    # This is scoped deliberately rather than re-tuned. The test's subject is
    # the splice mechanism -- "when a window ties, does resolving it beat the
    # grid DP" -- so it has to run under a condition where a window ties, and
    # 0.0 is that condition for this fixture. Lowering the 0.01 threshold to
    # chase the one fixture that still ties at a realistic terminal value
    # (realworld_2026_04_27_184643, advantage +0.0043 SEK) would have kept the
    # test green while quietly weakening it by an order of magnitude.
    #
    # The finding that motivated the scoping is worth more than the pin: across
    # the whole retrofitted corpus only four fixtures still flag a tie window
    # at all, and the largest hybrid advantage among them is 0.0043 SEK. The
    # measured value of #450's hybrid path under realistic terminal values is
    # therefore close to nil, which is a question for #450, not for this test.
    result, grid_only = _optimize(
        "synthetic_consumption_high_no_solar", terminal_value_per_kwh=0.0
    )

    advantage = grid_only.reward_objective_cost - result.reward_objective_cost
    assert advantage > 0.01, (
        f"hybrid window resolution is no longer improving on the grid DP "
        f"(advantage {advantage:.9f} SEK, expected ~0.0600). Either tie "
        f"detection stopped flagging this fixture's window (14, 19) or the "
        f"PWL resolution stopped being spliced in."
    )

    # The DP's objective and the summary it reports must agree exactly (#497).
    assert result.economic_summary.battery_solar_cost == pytest.approx(
        result.reward_objective_cost, abs=1e-9
    ), "reported summary drifted from the objective the DP actually minimised"

    # Absolute pin, tight enough to catch an unintended economics change.
    assert result.reward_objective_cost == pytest.approx(249.70724, abs=1e-6)


def test_450_original_fixture_no_longer_needs_resolution():
    """#512's finer grid dissolves the near-tie that produced #450's original
    mis-ranking on its reproduction fixture: value-function snap noise halved,
    so the grid DP now ranks the window correctly on its own and tie detection
    flags nothing. Pinning this documents the intended fewer-ties effect --
    and if the fixture ever starts tying again (e.g. a TIE_NOISE_FACTOR
    change), the assertion points straight at the mechanism."""
    result, grid_only = _optimize("regression_2026_08_02_043728")
    assert result.reward_objective_cost == pytest.approx(
        grid_only.reward_objective_cost, abs=1e-9
    ), "fixture near-ties again -- hybrid and grid-only diverged"
