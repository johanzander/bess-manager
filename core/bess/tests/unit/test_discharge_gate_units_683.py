"""The discharge gate must price stored energy across the span it consumes (#683).

**The issue's own diagnosis is wrong about the cause, and this file is where that
matters most -- read this before "simplifying" the estimator back.** #683 is filed
as a units mismatch: that ``buy_price_t * efficiency_discharge >= shadow_price``
compares per-delivered against per-SoE and is therefore ``1/eta`` too strict. It is
not. That comparison was dimensionally sound: covering ``dE`` consumes ``dE/eta`` of
SoE, so the test ``dE * buy >= (dE/eta) * dV/dSoE`` reduces to
``buy * eta >= dV/dSoE`` exactly as written. Where ``V`` is smooth the new rule is
algebraically identical to the old one and no decision changes -- which is precisely
why 2508 corpus periods produce bit-identical actions, intents, SoE and cost.

The real defect is **estimation, not units**. ``SOE_STEP_KWH`` (0.025) equals
``POWER_STEP_KW * dt`` (0.025) while the SoE->delivery conversion carries eta, so the
value function is a staircase whose riser is one full delivery step and which is flat
once every ``1/(1-eta)`` cells. The estimator this replaced took a *one-cell* backward
difference of that staircase, which is a poor reading of ``dV/dSoE``: it lands on a
riser most of the time and reports the undiscounted price, and on a flat cell reports
far too little.

``_value_of_delivering_below`` reads across ``SOE_STEP_KWH / eta`` -- exactly the SoE
a delivery consumes -- so the staircase averages out by construction, and the result
comes out per kWh *delivered*, which is why the rule loses its eta rather than
gaining one. Measured across the 39-fixture corpus (2508 periods) the swap flips 122
gate decisions: **22 open and 100 close.** The one-cell reading was noisy in *both*
directions rather than eta-biased -- in 111 rule disagreements it priced stored energy
1.5-2.9x too *low*, authorizing discharge of energy worth well above the grid price
being paid. Against a 20-step reference price the median error falls from 6.7% to
2.7%. The 100 closes are the correction the issue does not lead a reader to expect.

Like `test_discharge_gate_authorization_526.py`, these are built from real
optimizer-produced schedules rather than hand-assembled decisions, because the failure
mode is precisely that a branch is reachable by real DP output while a synthetic unit
test on the gate function looks fine.
"""

import pytest

from core.bess.tests.helpers import run_scenario
from core.bess.tests.unit.test_scenarios import load_test_scenario

# Fixtures measured to contain periods the old one-cell estimator over-priced, so the
# gate closed while the buy price already met or beat the marginal value of stored
# energy -- battery-now at least as good as saving it. Chosen as the three with the
# highest count; `regression_2026_08_13_145213` is the reporter's own 13 Aug bundle,
# where every closed period is of this kind. (These are the *opens*; the corpus-wide
# swap closes ~4.5x more periods than it opens, per the module docstring.)
OVERPRICED_CLOSED_FIXTURES = [
    "realworld_2026_04_22_202249",
    "regression_2026_08_13_145213",
    "regression_2026_07_26_203726",
]


@pytest.mark.parametrize("scenario_name", OVERPRICED_CLOSED_FIXTURES)
def test_gate_opens_when_buying_costs_at_least_the_marginal_value(
    scenario_name: str,
) -> None:
    """Battery-now beats grid-now => the gate must authorize the discharge.

    With ``shadow_price`` denominated per kWh delivered, the rule is
        ``buy_now >= shadow``. Any period where the buy price already meets the marginal
        value of a stored kWh and the gate is nonetheless closed is the battery being told
        to hold energy that is worth no more later than it is worth right now -- which is
        what the reporter observed as overnight grid import at 27% SOC.

        This is a one-sided test by design: it catches the gate closing when it should
        open. The corpus-wide swap also *closes* 100 periods the old estimator wrongly
        opened; those are pinned by the goldens, not here.
    """
    result = run_scenario(load_test_scenario(scenario_name))

    # A shadow price of exactly 0.0 is the "never computed" default (#526), not a
    # worthless kWh -- those periods have nothing to authorize, so skip them.
    wrongly_closed = [
        (i, pd.economic.buy_price, pd.decision.shadow_price)
        for i, pd in enumerate(result.period_data)
        if pd.decision.shadow_price != 0.0
        and not pd.decision.intra_period_discharge_allowed
        and pd.economic.buy_price >= pd.decision.shadow_price - 1e-9
    ]

    assert not wrongly_closed, (
        f"{len(wrongly_closed)} period(s) hold stored energy that buying cannot beat. "
        f"First three (period, buy, shadow): {wrongly_closed[:3]}"
    )
