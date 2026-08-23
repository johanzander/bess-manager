"""The discharge gate must compare like with like (#683).

`_record_marginal_value` tests ``buy_price_t * efficiency_discharge >= shadow_price``.
That is correct only if ``shadow_price`` is denominated per kWh *of SoE*. In the
discharge-limited regime it is not: ``SOE_STEP_KWH`` (0.025) equals
``POWER_STEP_KW * dt`` (0.025) while the SoE->delivery conversion carries eta, so the
value function is a staircase whose riser is one full delivery step and which is flat
once every ``1/(1-eta)`` cells. ``_value_slope_below`` takes a *one-cell* backward
difference, lands on a riser 19 times out of 20, and therefore reports the
**undiscounted** price.

The two sides of the comparison are then in different units and the gate is a factor
``1/eta`` too strict -- it demands the current price beat the competing future price by
5.3% before the battery may cover a load spike, and it is wrong on exact ties.

Why eta must cancel entirely: covering ``dE`` from the battery consumes ``dE/eta`` of
SoE, which would later have delivered ``dE`` anyway. The opportunity cost is therefore
``dE * p_future`` and the correct rule is simply ``buy_now >= p_future``.

Like `test_discharge_gate_authorization_526.py`, these are built from real
optimizer-produced schedules rather than hand-assembled decisions, because the failure
mode is precisely that a branch is reachable by real DP output while a synthetic unit
test on the gate function looks fine.
"""

import pytest

from core.bess.tests.helpers import run_scenario
from core.bess.tests.unit.test_scenarios import load_test_scenario

# Fixtures measured to contain periods the gate closes *only* because of the eta
# factor -- i.e. where the buy price already meets or beats the marginal value of
# stored energy, so battery-now is at least as good as saving it. Chosen as the three
# with the highest count; `regression_2026_08_13_145213` is the reporter's own
# 13 Aug bundle, where every closed period is of this kind.
ETA_ONLY_CLOSED_FIXTURES = [
    "realworld_2026_04_22_202249",
    "regression_2026_08_13_145213",
    "regression_2026_07_26_203726",
]


@pytest.mark.parametrize("scenario_name", ETA_ONLY_CLOSED_FIXTURES)
def test_gate_opens_when_buying_costs_at_least_the_marginal_value(scenario_name):
    """Battery-now beats grid-now => the gate must authorize the discharge.

    The economically correct rule is ``buy_now >= p_future``, with eta cancelling on
    both sides. Any period where the buy price already meets the marginal value of a
    stored kWh and the gate is nonetheless closed is the battery being told to hold
    energy that is worth no more later than it is worth right now -- which is what the
    reporter observed as overnight grid import at 27% SOC.
    """
    result = run_scenario(load_test_scenario(scenario_name))

    wrongly_closed = [
        (i, pd.economic.buy_price, pd.decision.shadow_price)
        for i, pd in enumerate(result.period_data)
        if getattr(pd.decision, "shadow_price", 0.0)
        and not pd.decision.intra_period_discharge_allowed
        and pd.economic.buy_price >= pd.decision.shadow_price - 1e-9
    ]

    assert not wrongly_closed, (
        f"{len(wrongly_closed)} period(s) hold stored energy that buying cannot beat. "
        f"First three (period, buy, shadow): {wrongly_closed[:3]}"
    )
