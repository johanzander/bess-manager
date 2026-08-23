"""A tie window too long for one exact solve must be bisected, not fatal (#624).

`detect_tie_windows` merges adjacent flagged periods with no cap on the merged
length, while `run_pwl_window_backward_induction`'s breakpoint set compounds
per backward step -- it seeds every discharge preimage of the next row's
breakpoints. Past roughly eight periods the cross product exceeds
`PWL_MAX_PREIMAGE_SEED_POINTS`, and no budget raise reaches a longer horizon
(`measure_tie_coverage.py`).

Before the fix that raised `PWLWindowUnderRefinedError` straight out of
`optimize_battery_schedule`, discarding the whole schedule -- including every
period that had solved fine. In the field (#624) the hourly retry then fed the
same effectively-unchanged inputs into the same wall 14 times across two
restarts, and the add-on never left "initializing".

The fixture is the reporter's own day: volatile SE3 prices over a 20 kWh /
10 kW battery, which merge periods 76-85 into a single nine-period window.
"""

import json

import pytest

import core.bess.dp_battery_algorithm as dpa
from core.bess.exceptions import PWLWindowUnderRefinedError
from core.bess.pwl_window_dp import run_pwl_window_backward_induction
from core.bess.tests.helpers import _scenario_inputs, run_scenario_realized
from core.bess.tests.integration.test_plan_faithfulness import (
    PLAN_EXECUTION_TOLERANCE_SEK,
)
from core.bess.tests.unit.golden_capture import DATA_DIR

FIXTURE = "regression_2026_08_17_624"

# Measured on this fixture: the merged window and where bisection lands.
EXPECTED_WINDOW = (76, 85)
EXPECTED_HALVES = [(76, 80), (80, 85)]


@pytest.fixture(scope="module")
def scenario() -> dict:
    return json.loads((DATA_DIR / f"{FIXTURE}.json").read_text())


def _inputs_without_terminal_row(scenario: dict) -> dict:
    """This rig runs with NO terminal row, and must keep doing so (#602).

    A nonzero terminal row adds a value gradient at the boundary that breaks the
    very near-ties this path exists to resolve. That was already measured in
    `TODO.md` after the #605 retrofit -- only four of 38 fixtures still flagged a
    tie window at all -- and #602 raises terminal values further. With the
    concave row this fixture's merge shrinks from nine periods to five, (76, 81),
    comfortably inside what a single solve certifies: the tests below would then
    pass while exercising the ordinary un-bisected path, which is exactly the
    silent coverage loss the first test guards against. A corpus-wide scan after
    #602 finds *no* fixture producing a window of eight periods or more, so there
    is nothing to re-point this at.

    Pinning the rig at zero is the same choice `test_issue_450_hybrid_resolution`
    and `test_measure_tie_coverage` already made, for the same reason: the
    subject is near-ties, so it has to run where near-ties exist. What it costs
    is recorded in `TODO.md` -- the hybrid path's *production* value is now
    measured by nothing -- and #602 sharpens that open question rather than
    answering it.
    """
    inputs = dict(_scenario_inputs(scenario))
    inputs.pop("terminal_curve", None)
    return inputs


def test_the_reporters_day_still_merges_a_window_no_single_solve_can_certify(
    scenario,
):
    """Guards the fixture's own premise.

    If tuning ever shortens this window below the solver's ceiling, the tests
    below would still pass while testing nothing -- they would exercise the
    ordinary un-bisected path. Assert the input really is pathological, so
    that day arrives as a failure here rather than as silent coverage loss.
    """
    inputs = _inputs_without_terminal_row(scenario)
    diagnostics: dict = {}
    dpa.optimize_battery_schedule(**inputs, tie_diagnostics=diagnostics)

    windows = [(w.start, w.end) for w in diagnostics["windows"]]
    assert EXPECTED_WINDOW in windows, (
        f"expected the merged window {EXPECTED_WINDOW} on this fixture, got "
        f"{windows} -- the fixture no longer reproduces #624's input shape"
    )

    start, end = EXPECTED_WINDOW
    inp = inputs
    with pytest.raises(PWLWindowUnderRefinedError):
        run_pwl_window_backward_induction(
            window_horizon=end - start,
            buy_price=inp["buy_price"][start:end],
            sell_price=inp["sell_price"][start:end],
            home_consumption=inp["home_consumption"][start:end],
            solar_production=inp["solar_production"][start:end],
            battery_settings=inp["battery_settings"],
            dt=inp["period_duration_hours"],
            end_soe_target=diagnostics["soe_trajectory"][end],
        )


def test_an_over_long_window_is_bisected_instead_of_killing_the_schedule(scenario):
    """The outcome that was broken: a schedule exists at all.

    Pre-fix this call raised `PWLWindowUnderRefinedError` and
    `battery_system_manager` turned that into `return None`, so the system had
    no schedule to publish.
    """
    inputs = _inputs_without_terminal_row(scenario)
    result = dpa.optimize_battery_schedule(**inputs)

    assert len(result.period_data) == len(inputs["buy_price"])
    # The window's periods are re-solved, not skipped: every period inside it
    # carries a decision, and the SOE trajectory stays physical throughout.
    settings = inputs["battery_settings"]
    for period in range(*EXPECTED_WINDOW):
        soe = result.period_data[period].energy.battery_soe_end
        assert settings.min_soe_kwh - 1e-6 <= soe <= settings.max_soe_kwh + 1e-6


def test_bisection_splits_at_the_midpoint_and_both_halves_certify(scenario, caplog):
    """Each half is solved by the same solver under the same certification.

    This is what makes the fix a re-sizing rather than a fallback: nothing
    uncertified is ever spliced, so P6 is untouched.
    """
    inputs = _inputs_without_terminal_row(scenario)
    with caplog.at_level("WARNING"):
        dpa.optimize_battery_schedule(**inputs)

    splits = [r for r in caplog.records if "#624" in r.getMessage()]
    assert len(splits) == 1, f"expected exactly one split, got {len(splits)}"
    message = splits[0].getMessage()
    assert f"({EXPECTED_WINDOW[0]}, {EXPECTED_WINDOW[1]})" in message
    assert f"splitting at {EXPECTED_HALVES[0][1]}" in message


@pytest.mark.slow
def test_the_bisected_schedule_is_executable_as_planned(scenario):
    """R == P across the splice: the plan the DP reports is the plan the
    derived inverter commands actually achieve.

    This is the test that matters for the bisection specifically. Splitting a
    window adds an interior boundary, and the second half must be solved from
    the SOE the first half actually reached rather than the grid DP's nominal
    value there. Getting that wrong shows up here as a plan the hardware
    cannot execute, and nowhere in the economics pins.

    This fixture used to carry a registered +0.0016 gap in
    `KNOWN_PLAN_EXECUTION_GAP_SEK`, which had nothing to do with bisection --
    it reproduced bit-identically with tie resolution disabled entirely -- so
    the assertion was that bisection adds NOTHING to that gap. #630 removed
    the gap's actual cause (the DP planned a solar surplus too small to
    classify SOLAR_EXPORT as exported, while the IDLE command it derived
    absorbed it), so the pin is now the plain equality it was always trying
    to approximate. Strictly stronger: any bisection seam error has nowhere
    to hide, since there is no longer a nonzero expected value for one to sit
    inside.

    The 0.001 SEK gate is the corpus-wide one, deliberately, not a looser
    local band. Written first at 0.01 SEK, this passed while telling the
    reader nothing: a tolerance ten times the effect it guards cannot
    distinguish a clean seam from a broken one.
    """
    result, realized_cost = run_scenario_realized(scenario)

    planned = result.economic_summary.battery_solar_cost
    assert realized_cost - planned == pytest.approx(
        0.0, abs=PLAN_EXECUTION_TOLERANCE_SEK
    ), (
        f"the bisected plan is not executable as planned: "
        f"R={realized_cost:.6f} P={planned:.6f} gap={realized_cost - planned:+.6f}"
    )
