"""The emitted plan must not depend on the last bit of a float (#606).

`regression_2026_08_13_145213` produced two different plans on two
interpreters -- period 18 was -1.1625 kW on Python 3.12.13 and -0.6875 kW on
3.13.15, same commit, same pinned numpy, deterministic within each. Neither
plan is wrong: measured, the two cost *exactly* the same (`battery_solar_cost
= -4.954319746390006` in both, bit-identical, not merely within a tolerance).

The cause is a structural plateau, not a coincidence. Periods 17-20 are four
bit-identical 15-minute slots inside one hourly price block -- same buy price,
same sell price, same home consumption, same solar -- and all four are pure
BATTERY_EXPORT with no binding rate, AC or SOE constraint. The DP objective is
therefore exactly invariant to how a fixed total discharge is split across the
block: only the sum reaches period 21. At `terminal_value_per_kwh = 0.0` the
boundary energy is worthless, the block is not marginal and the degeneracy
never arises, which is why this only appeared once #605 retrofitted the corpus
onto production terminal values.

On the plateau the two candidates' values differ by *one ULP* (measured 0.93
ULP recomputed in exact rational arithmetic), while `epsilon_for_period` at
this period is 7.36e-4 SEK -- the gap is ~8e11 times inside epsilon. Both
candidates are in the eligible set, `tie_policy`'s rows 3 and 4 both stand
down, and row 5 ("the argmax winner stands") hands the choice back to the
float comparison in `action_selector.select_action`'s argmax loop. That is the
P2 violation (`docs/agents/optimizer-architecture.md`): a within-epsilon
choice resolved outside the one preference table.

`tie_margins` cannot see it, and is not malfunctioning. `_tie_margin` measures
the gap to the best *behaviourally distinct* alternative, where distinctness
is SOE separation alone (`TIE_DEDUP_SOE_KWH = 1.0`). The two candidates sit
0.5 kWh apart -- exactly half the dedup distance -- so the flipping candidate
is skipped by construction and the reported margin (1.488e-02) is the gap to
something else entirely.

**Why a 1-ULP perturbation is the right test.** A test that only fails on
Python 3.13 cannot be run here, and pinning the interpreter would hide the
defect rather than fix it -- the boundary would still be 0.93 ULP wide, and
the next wheel, compiler or architecture change would land with no diagnosis
attached. Perturbing one input by a single ULP reproduces the same divergence
on one interpreter, and reproduces CI's plan *exactly*: with
`sell_price[19]` moved one ULP up, pre-fix output is
`p18/p19 = -0.6875/-1.1625` and every other period byte-identical. Testing the
mechanism directly is also what keeps this honest if the fixture drifts.
"""

import json
import math
from pathlib import Path

import pytest

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.tests.helpers import _scenario_inputs

DATA_DIR = Path(__file__).parent / "data"

# The fixture whose plateau #606 was reported against, and the input whose
# single-ULP perturbation reproduces the reported CI plan exactly.
TIE_FIXTURE = "regression_2026_08_13_145213"
PERTURBED_KEY = "sell_price"
PERTURBED_INDEX = 19


def _plan(scenario: dict) -> list[float]:
    result = optimize_battery_schedule(**_scenario_inputs(scenario))
    return [p.decision.battery_action for p in result.period_data]


def _cost(scenario: dict) -> float:
    result = optimize_battery_schedule(**_scenario_inputs(scenario))
    return result.economic_summary.battery_solar_cost


def _load(name: str) -> dict:
    return json.loads((DATA_DIR / f"{name}.json").read_text())


def test_plan_is_stable_under_a_one_ulp_input_perturbation():
    """A 2.2e-16 relative change to one price must not reorder the plan.

    Pre-fix this fails with periods 18 and 19 swapping to -0.6875 / -1.1625 --
    which is precisely the plan CI emitted on Python 3.13.15, so the mutation
    reproduces the reported defect rather than merely resembling it.
    """
    scenario = _load(TIE_FIXTURE)
    perturbed = _load(TIE_FIXTURE)
    perturbed[PERTURBED_KEY][PERTURBED_INDEX] = math.nextafter(
        perturbed[PERTURBED_KEY][PERTURBED_INDEX], math.inf
    )

    baseline = _plan(scenario)
    actual = _plan(perturbed)

    assert actual == baseline


def test_the_two_plans_on_the_plateau_cost_the_same():
    """The premise of the fix: this is a tie, not a mis-ranking.

    If the perturbed plan were genuinely cheaper, routing the choice through
    `tie_policy` would be forfeiting money and the fix above would be wrong.
    Measured: the costs are bit-identical, so the preference row gives up
    nothing. This holds both before and after the fix -- it is the guard that
    keeps the fix honest, not a reproduction of the bug.
    """
    scenario = _load(TIE_FIXTURE)
    perturbed = _load(TIE_FIXTURE)
    perturbed[PERTURBED_KEY][PERTURBED_INDEX] = math.nextafter(
        perturbed[PERTURBED_KEY][PERTURBED_INDEX], math.inf
    )

    assert _cost(perturbed) == pytest.approx(_cost(scenario), abs=1e-9)
