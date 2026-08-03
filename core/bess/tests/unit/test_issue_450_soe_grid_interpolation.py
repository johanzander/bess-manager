"""Regression for #450: SOE-grid snap noise in the backward-induction pass
can pick a sub-optimal charging window when two adjacent windows are
financially near-tied.

Uses the real debug bundle attached to #448 (reconstructed via
scripts/mock_ha/scenarios/from_debug_log.py --issue 450), not a hand-built
period/decision -- a synthetic-input unit test on the changed lookup could
pass while the new interpolation path is unreachable by any real
DP-produced schedule.
"""

import json
import os

import pytest

from core.bess.tests.helpers import assert_intent_at_hour, run_scenario_realized

_FIXTURE = os.path.join(
    os.path.dirname(__file__), "data", "regression_2026_08_02_043728.json"
)


def _load_fixture():
    with open(_FIXTURE) as f:
        return json.load(f)


def test_picks_cheaper_adjacent_charging_window():
    """13:00-13:45 (index 34-36) vs 13:15-14:00 (index 35-37): flat solar
    surplus across all four periods makes price the only tiebreaker.
    13:15-14:00 is the genuinely cheaper window (per #450's direct
    reward-function comparison, confirmed against the DP's own
    _compute_reward/_state_transition) -- the DP must pick it, not snap to
    the earlier window under SOE-grid discretization noise."""
    scenario = _load_fixture()

    result, realized_cost = run_scenario_realized(scenario)

    # Plan-faithfulness: executing the plan must reproduce its own economics.
    planned_cost = result.economic_summary.battery_solar_cost
    tol = max(0.5, 0.01 * abs(planned_cost))
    assert realized_cost == pytest.approx(planned_cost, abs=tol)

    # Index 34 = period 52 = 13:00 was wrongly STORE under the pre-fix snap;
    # the cheaper window starts at index 35 (13:15) instead.
    assert_intent_at_hour(result, 34, "SOLAR_EXPORT")
    assert_intent_at_hour(result, 35, "SOLAR_STORAGE")
    assert_intent_at_hour(result, 36, "SOLAR_STORAGE")
    assert_intent_at_hour(result, 37, "SOLAR_STORAGE")
