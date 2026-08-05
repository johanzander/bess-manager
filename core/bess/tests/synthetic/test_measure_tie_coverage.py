import inspect

import pytest

from core.bess.dp_battery_algorithm import (
    BATTERY_EXPORT_THRESHOLD_KWH,
    SOE_STEP_KWH,
    optimize_battery_schedule,
)
from core.bess.pwl_window_dp import PWLWindowUnderRefinedError
from core.bess.tests.helpers import _scenario_inputs
from core.bess.tests.synthetic.measure_tie_coverage import (
    TIE_WINDOW_PAD,
    classify_margin_ratios,
    near_miss_segment,
    replay_schedule,
    segment_reference_cost,
)
from core.bess.tests.unit.test_scenarios import load_test_scenario
from core.bess.tie_detection import Window, detect_tie_windows


def test_classifies_into_expected_buckets():
    # worst_case_noise = soe_step_kwh * abs(value_slope); ratio = margin / worst_case_noise
    # soe_step_kwh=0.1, value_slope=1.0 -> worst_case_noise=0.1 for every period below
    tie_margins = [0.005, 0.03, 0.08, 0.15, 0.25]
    value_slopes = [1.0, 1.0, 1.0, 1.0, 1.0]
    result = classify_margin_ratios(tie_margins, value_slopes, soe_step_kwh=0.1)
    # ratios: 0.05, 0.3, 0.8, 1.5, 2.5
    assert result == {
        "<0.1x": 1,
        "0.1x-0.5x": 1,
        "0.5x-1.0x": 1,
        "1.0x-2.0x": 1,
        ">2.0x": 1,
    }


def test_zero_value_slope_counts_as_over_2x():
    # worst_case_noise == 0 when value_slope == 0 -- ratio is undefined/infinite,
    # meaning grid-snapping cannot affect this period's ranking at all. Bucket
    # it in the "clearly not a tie" bucket rather than raising or dividing by zero.
    result = classify_margin_ratios([0.01], [0.0], soe_step_kwh=0.1)
    assert result == {
        "<0.1x": 0,
        "0.1x-0.5x": 0,
        "0.5x-1.0x": 0,
        "1.0x-2.0x": 0,
        ">2.0x": 1,
    }


def test_empty_input_returns_zero_counts():
    result = classify_margin_ratios([], [], soe_step_kwh=0.1)
    assert result == {
        "<0.1x": 0,
        "0.1x-0.5x": 0,
        "0.5x-1.0x": 0,
        "1.0x-2.0x": 0,
        ">2.0x": 0,
    }


# --------------------------------------------------------------------------
# Segment selection (pure -- no solver, no fixture)
# --------------------------------------------------------------------------


def test_near_miss_segment_picks_the_period_closest_to_the_threshold():
    # epsilon = TIE_NOISE_FACTOR(0.1) * soe_step(0.1) * |slope| = 0.01 * |slope|.
    # With slope 1.0 everywhere epsilon is 0.01, so every margin below is an
    # unflagged near miss. Period 3 sits closest to the threshold (1.2x).
    tie_margins = [0.05, 0.02, 0.04, 0.012, 0.03]
    value_slopes = [1.0] * 5

    assert near_miss_segment(tie_margins, value_slopes, soe_step_kwh=0.1) == Window(
        start=1, end=5
    )


def test_near_miss_segment_ignores_periods_the_detector_already_flagged():
    # Period 1's margin (0.005) is BELOW epsilon 0.01, so the detector already
    # flagged and re-solved it -- it is not a miss and must not be measured as
    # one. Period 4 is the closest genuine near miss.
    tie_margins = [0.05, 0.005, 0.04, 0.09, 0.011]
    value_slopes = [1.0] * 5

    assert near_miss_segment(tie_margins, value_slopes, soe_step_kwh=0.1) == Window(
        start=2, end=5
    )


def test_near_miss_segment_skips_periods_no_ratio_can_be_formed_for():
    # slope 0 -> epsilon 0 (the detector's zero-epsilon blind spot) and an
    # infinite margin -> no comparison happened. Neither yields a meaningful
    # distance-to-threshold, so neither may be selected; period 2 is the only
    # measurable candidate.
    tie_margins = [0.05, float("inf"), 0.02]
    value_slopes = [0.0, 1.0, 1.0]

    assert near_miss_segment(tie_margins, value_slopes, soe_step_kwh=0.1) == Window(
        start=0, end=3
    )


def test_near_miss_segment_clamps_padding_to_the_horizon():
    tie_margins = [0.011, 0.05]
    value_slopes = [1.0, 1.0]

    assert near_miss_segment(tie_margins, value_slopes, soe_step_kwh=0.1) == Window(
        start=0, end=2
    )


def test_near_miss_segment_returns_none_when_nothing_is_measurable():
    # Every period is either already flagged or has no formable ratio.
    assert (
        near_miss_segment([0.005, float("inf")], [1.0, 1.0], soe_step_kwh=0.1) is None
    )
    assert near_miss_segment([], [], soe_step_kwh=0.1) is None


def test_near_miss_segment_rejects_mismatched_input_lengths():
    with pytest.raises(ValueError, match="recorded per period in the same pass"):
        near_miss_segment([0.01, 0.02], [1.0], soe_step_kwh=0.1)


# --------------------------------------------------------------------------
# Reference cost against the real #450 fixture
# --------------------------------------------------------------------------


def _run_450_fixture():
    scenario = load_test_scenario("regression_2026_08_02_043728")
    inputs = _scenario_inputs(scenario)
    diagnostics: dict = {}
    result = optimize_battery_schedule(**inputs, tie_diagnostics=diagnostics)
    return inputs, diagnostics, result


def _replay(inputs, result):
    return replay_schedule(
        result,
        buy_price=inputs["buy_price"],
        sell_price=inputs["sell_price"],
        home_consumption=inputs["home_consumption"],
        solar_production=inputs["solar_production"],
        battery_settings=inputs["battery_settings"],
        dt=inputs["period_duration_hours"],
        initial_soe=inputs["initial_soe"],
        initial_cost_basis=inputs["initial_cost_basis"],
        self_throttle_export_threshold_kwh=BATTERY_EXPORT_THRESHOLD_KWH,
        import_cap_kwh=None,
    )


def _reference(inputs, result, segment, cost_bases):
    return segment_reference_cost(
        segment,
        buy_price=inputs["buy_price"],
        sell_price=inputs["sell_price"],
        home_consumption=inputs["home_consumption"],
        solar_production=inputs["solar_production"],
        battery_settings=inputs["battery_settings"],
        dt=inputs["period_duration_hours"],
        soe_trajectory=[inputs["initial_soe"]]
        + [p.energy.battery_soe_end for p in result.period_data],
        cost_basis=cost_bases[segment.start],
        self_throttle_export_threshold_kwh=BATTERY_EXPORT_THRESHOLD_KWH,
        import_cap_kwh=None,
    )


@pytest.mark.slow
def test_replay_reproduces_the_reported_reward_objective_cost():
    """The comparison's hybrid side must be the DP's own accounting, exactly.

    `OptimizationResult` reports only the horizon total, so a segment's share
    has to be replayed from the returned PeriodData. Pinning the total here is
    what makes that replay trustworthy: if the reconstruction ever drifts from
    what the DP actually accumulated, every segment delta silently inherits the
    bias, and this suite exists to measure deltas in SEK.
    """
    inputs, _diagnostics, result = _run_450_fixture()

    period_costs, _cost_bases = _replay(inputs, result)

    assert sum(period_costs) == pytest.approx(result.reward_objective_cost, abs=1e-9)


@pytest.mark.slow
def test_reference_reproduces_the_hybrid_on_a_window_it_already_resolved():
    """Self-consistency: on a window the hybrid re-solved with this very
    solver, an independently-run exact solve must land on the same cost.

    This is the control for the near-miss measurement below -- it isolates the
    measurement rig from the thing being measured. A non-zero delta here would
    mean the rig disagrees with the production hybrid on a case where both ran
    the same exact solver, so any delta it reports on an *unflagged* segment
    would be rig error, not a missed tie.
    """
    inputs, diagnostics, result = _run_450_fixture()
    assert diagnostics["windows"], "fixture is expected to flag at least one window"
    window = diagnostics["windows"][0]
    period_costs, cost_bases = _replay(inputs, result)

    reference_cost = _reference(inputs, result, window, cost_bases)

    hybrid_cost = sum(period_costs[window.start : window.end])
    assert reference_cost == pytest.approx(hybrid_cost, abs=1e-6)


@pytest.mark.slow
def test_reference_matches_or_beats_the_hybrid_on_the_closest_near_miss():
    """The measurement itself: what the DP's closest near miss actually costs.

    The segment is the window `detect_tie_windows` *would* have built had the
    threshold been low enough to flag this period, so the delta answers the
    counterfactual this suite exists to answer -- "how much SEK was left on
    the table by not flagging it".
    """
    inputs, diagnostics, result = _run_450_fixture()
    segment = near_miss_segment(
        diagnostics["tie_margins"],
        diagnostics["value_slopes"],
        soe_step_kwh=SOE_STEP_KWH,
    )
    assert segment is not None
    period_costs, cost_bases = _replay(inputs, result)

    reference_cost = _reference(inputs, result, segment, cost_bases)

    # Pinned to the hybrid's own SOE at both ends and solved with no grid
    # snapping, the exact segment can only match or beat the hybrid over the
    # same periods. A reference that came out *worse* would mean the rig is
    # solving a different (or infeasible) problem, not that the DP won.
    assert reference_cost <= sum(period_costs[segment.start : segment.end]) + 1e-6


@pytest.mark.slow
def test_segment_reference_refuses_a_segment_longer_than_the_solver_can_certify():
    """Why the segment stays short, pinned as a tested boundary.

    The exact solver seeds every discharge preimage of the next row's
    breakpoints, so its breakpoint set compounds per backward step: on this
    fixture it exhausts `PWL_MAX_PREIMAGE_SEED_POINTS` (1e6) at a horizon of 8
    periods and raises. That wall is why this reference measures a padded
    segment rather than the whole 78-period horizon. The raise is deliberately
    not caught -- an uncertifiable table has no honest use as a "true optimal"
    reference -- so callers must keep segments at the detector's own pad width.
    """
    inputs, _diagnostics, result = _run_450_fixture()
    _period_costs, cost_bases = _replay(inputs, result)

    with pytest.raises(PWLWindowUnderRefinedError):
        _reference(inputs, result, Window(start=0, end=8), cost_bases)


def test_segment_padding_matches_the_detectors_own():
    # The measured segment must be the window production would have built, so
    # this default is not free to drift from `detect_tie_windows`'.
    detector_pad = inspect.signature(detect_tie_windows).parameters["pad"].default
    assert TIE_WINDOW_PAD == detector_pad


@pytest.mark.slow
def test_measures_a_real_near_miss_on_a_scenario_with_no_flags_at_all():
    """The zero-flag case, which is the one this suite exists for.

    A scenario where the detector flagged nothing produces no evidence about
    its own coverage -- so the near-miss segment is the only thing that can
    tell us whether the silence was earned. On this fixture it is not
    entirely: re-solving the five periods around the closest miss is worth a
    real, non-zero amount (measured 0.078 SEK), which is exactly the kind of
    finding the suite has to be able to surface.

    Interpreting the number: it is a *segment* delta with both ends pinned, so
    it under-counts what a free-horizon optimum could win, and it credits any
    grid-quantization gain in those five periods, not only the near-tie
    itself. Both directions are stated in `segment_reference_cost`'s docstring
    and must survive into Task 6's reporting.
    """
    scenario = load_test_scenario("historical_2024_08_16_high_spread_no_solar")
    inputs = _scenario_inputs(scenario)
    diagnostics: dict = {}
    result = optimize_battery_schedule(**inputs, tie_diagnostics=diagnostics)
    assert diagnostics["windows"] == [], "fixture is expected to flag nothing"

    segment = near_miss_segment(
        diagnostics["tie_margins"],
        diagnostics["value_slopes"],
        soe_step_kwh=SOE_STEP_KWH,
    )
    assert segment is not None
    period_costs, cost_bases = _replay(inputs, result)
    reference_cost = _reference(inputs, result, segment, cost_bases)

    delta = sum(period_costs[segment.start : segment.end]) - reference_cost
    assert delta > 0.0
    assert reference_cost <= sum(period_costs[segment.start : segment.end]) + 1e-6


@pytest.mark.slow
def test_scenario_with_no_measurable_period_reports_nothing_rather_than_guessing():
    """Not every scenario has a near miss to measure.

    On this fixture every period is a detector blind spot (flat value
    function, or no behaviourally distinct alternative), so there is no
    distance-to-threshold to rank. Returning `None` forces the caller to
    report "nothing measurable" instead of silently measuring an arbitrary
    segment and presenting its economics as a coverage result.
    """
    scenario = load_test_scenario("historical_2025_01_05_no_spread_no_solar")
    inputs = _scenario_inputs(scenario)
    diagnostics: dict = {}
    optimize_battery_schedule(**inputs, tie_diagnostics=diagnostics)

    assert (
        near_miss_segment(
            diagnostics["tie_margins"],
            diagnostics["value_slopes"],
            soe_step_kwh=SOE_STEP_KWH,
        )
        is None
    )
