import inspect

import pytest

from core.bess.dp_battery_algorithm import (
    SOE_STEP_KWH,
    optimize_battery_schedule,
)
from core.bess.exceptions import PWLWindowUnderRefinedError
from core.bess.settings import BatterySettings
from core.bess.tests.helpers import _scenario_inputs
from core.bess.tests.synthetic import measure_tie_coverage
from core.bess.tests.synthetic.measure_tie_coverage import (
    TIE_WINDOW_PAD,
    ScenarioMeasurement,
    classify_margin_ratios,
    measure_scenario,
    near_miss_segment,
    post_splice_soe_trajectory,
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


def _at_zero_terminal_value(name):
    """Load a fixture with its terminal value pinned to 0.0.

    Every SEK constant in this suite was measured at `terminal_value_per_kwh
    = 0.0`, which was the corpus-wide default until the fixtures were
    retrofitted onto production-computed terminal values. That retrofit
    dissolves most of the near-ties this suite measures: a nonzero terminal
    row adds a value gradient at the horizon, and across the whole retrofitted
    corpus only four fixtures still flag a tie window at all.

    This suite's subject is the *detector and the near-miss measurement rig* --
    "given a near-tie, is the coverage silence earned, and what is the miss
    worth" -- so it has to run under a condition where near-ties exist. 0.0 is
    that condition, and pinning it explicitly is why these constants remain
    comparable to the ones recorded when they were first measured.

    Pinned rather than re-measured deliberately: re-pinning the deltas against
    the retrofitted values would replace a set of numbers that mean "this is
    what the near miss costs" with a set that mostly mean "there is no longer
    a near miss here", which is not the same test. Whether #450's hybrid path
    still earns its keep at realistic terminal values is a real question -- the
    largest surviving advantage in the corpus is 0.0043 SEK -- but it belongs
    to #450, not to this rig's unit coverage.
    """
    scenario = dict(load_test_scenario(name))
    scenario.pop("terminal_value_per_kwh", None)
    scenario.pop("terminal_knee_kwh", None)
    return scenario


def _run_fixture(name):
    scenario = _at_zero_terminal_value(name)
    inputs = _scenario_inputs(scenario)
    diagnostics: dict = {}
    result = optimize_battery_schedule(**inputs, tie_diagnostics=diagnostics)
    return inputs, diagnostics, result


def _run_450_fixture():
    return _run_fixture("regression_2026_08_02_043728")


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
        soe_trajectory=post_splice_soe_trajectory(result, inputs["initial_soe"]),
        cost_basis=cost_bases[segment.start],
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
    """On a window the hybrid re-solved with this same solver, an
    independently-run solve lands on the same cost.

    Scope stated narrowly, because this control is weaker than it looks: it
    shows the rig hands the solver the same pins, prices and loads production
    did. It does NOT verify window placement -- shifting the segment by one
    period into periods the hybrid never re-solved reproduces the hybrid's
    cost just as exactly, because the DP is already optimal on most segments.
    Nor does it exercise `cost_basis`, which the returned cost provably does
    not depend on. The mis-slicing control below is what actually catches a
    bad slice.
    """
    # #450's own fixture stopped flagging at #512's finer grid (the snap
    # noise that near-tied it was halved away); use a fixture that still
    # flags -- window (14, 19) measured at the 0.1 kW / 0.025 kWh grid.
    inputs, diagnostics, result = _run_fixture("synthetic_consumption_high_no_solar")
    assert diagnostics["windows"], "fixture is expected to flag at least one window"
    window = diagnostics["windows"][0]
    period_costs, cost_bases = _replay(inputs, result)

    reference_cost = _reference(inputs, result, window, cost_bases)

    hybrid_cost = sum(period_costs[window.start : window.end])
    assert reference_cost == pytest.approx(hybrid_cost, abs=1e-6)


@pytest.mark.slow
def test_measures_the_closest_near_miss_on_the_450_fixture():
    """The measurement itself: what the DP's closest near miss actually costs.

    The segment is the window `detect_tie_windows` *would* have built had the
    threshold been low enough to flag this period, so the delta answers the
    counterfactual this suite exists to answer -- "how much SEK was left on
    the table by not flagging it".

    On this fixture the answer is zero: the DP's closest miss was already
    the right call (re-measured at #512's finer grid, where the segment
    shifts from (32, 37) to (34, 39) and the answer stays zero). Pinned as a
    value, not as an inequality -- the reference is not a proven optimum (see
    `segment_reference_cost`), so "reference <= hybrid" is not an invariant
    this suite may assert.
    """
    inputs, diagnostics, result = _run_450_fixture()
    segment = near_miss_segment(
        diagnostics["tie_margins"],
        diagnostics["value_slopes"],
        soe_step_kwh=SOE_STEP_KWH,
    )
    assert segment == Window(start=34, end=39)
    period_costs, cost_bases = _replay(inputs, result)

    reference_cost = _reference(inputs, result, segment, cost_bases)

    delta = sum(period_costs[segment.start : segment.end]) - reference_cost
    assert delta == pytest.approx(0.0, abs=1e-6)


@pytest.mark.slow
def test_reference_does_not_undershoot_the_hybrid_on_the_regression_segment():
    """Regression pin for the backward-pass feasibility defect (#450).

    This segment used to be the standing counter-example to the reference
    being usable at all: the solver returned 42.679610 SEK against a grid-DP
    path costing 42.648857 -- 0.031 SEK *worse* -- with both endpoints
    identical and the pin honoured. The cause was in
    `_pwl_candidate_values_at`, whose discharge-rate mask compared against the
    affordable power exactly while the replay's `_discharge_candidates`
    percent-floors the same bound with a `+ 1e-9` slack. Breakpoint abscissae
    carry ULP-level noise (they are built by adding lattice energies to the
    previous row's breakpoints), so V got evaluated a hair below a level's
    onset, dropped the level the replay would have taken, and recorded a
    value 0.042 SEK below the truth -- enough to flip period 8's action.

    With both passes on one action set the solver now *beats* the grid DP
    here, which is the whole point of a reference: a positive delta is a
    constructive witness that the DP left money on the table. The numbers are
    pinned rather than just the sign so that a future regression which merely
    shrinks the margin is caught too.

    Re-pinned for #466 (risk-aware IDLE tie-break): the grid replay now
    breaks a near-tied IDLE inside this window toward load-covering
    discharge, which changes the SOE trajectory `segment_reference_cost`
    inherits at both ends -- both figures move together without indicating
    a regression. This segment's own cost is
    NOT the right place to judge that: pinning both ends forbids either pass
    from banking energy differently outside the window, so a windowed delta
    conflates the tie-break's real effect with wherever it happened to move
    cost across the 7/12 boundary. The full-horizon `reward_objective_cost`
    on this scenario is the right measure and moved 230.710092 -> 230.741975,
    +0.031883 SEK, inside the #450/#467 0.05 SEK regression budget -- an
    accounting shift, not an economic regression.

    Re-pinned again for #497 (the DP no longer proposes discharges the
    inverter cannot execute): 42.965278 / 42.945155, with the delta still
    positive at +0.020123 SEK, and the full-horizon objective moving
    230.741975 -> 230.753873, a further +0.011898 SEK and still inside the
    same budget. Every absolute cost on this fixture shifted because the
    plan no longer books export revenue it cannot collect; the property
    this test exists to check -- the reference not undershooting the
    hybrid -- is unaffected.

    Re-pinned again for #512 (finer DP grid): 42.792260 / 42.792260. The
    finer grid closes this segment's remaining quantization gap entirely,
    so the delta is now exactly zero and the assertion relaxes from
    strictly-positive to non-negative -- the regression this test guards
    is a NEGATIVE delta (the reference coming out worse than the hybrid,
    the #450 feasibility defect), which stays forbidden.

    Re-pinned again for Phase 4b (#352, the exact-cover candidate):
    42.861695 / 42.861695, delta still exactly zero. This segment costs
    +0.069435 SEK more than before while the fixture's full-horizon
    objective *improves* 230.701009 -> 230.592975 (-0.108034) -- the plan
    moved energy between segments, which is what a candidate-space change
    does. The invariant under test is untouched: reference and hybrid
    agree to the femto-öre, so the reference still does not undershoot.
    """
    scenario = load_test_scenario("historical_2024_08_16_high_spread_no_solar")
    inputs = _scenario_inputs(scenario)
    diagnostics: dict = {}
    result = optimize_battery_schedule(**inputs, tie_diagnostics=diagnostics)
    period_costs, cost_bases = _replay(inputs, result)

    reference_cost = _reference(inputs, result, Window(start=7, end=12), cost_bases)

    hybrid_cost = sum(period_costs[7:12])
    assert hybrid_cost == pytest.approx(42.861695, abs=1e-5)
    assert reference_cost == pytest.approx(42.861695, abs=1e-5)
    assert hybrid_cost - reference_cost >= -1e-9


@pytest.mark.slow
def test_reference_cost_does_not_depend_on_cost_basis():
    """`cost_basis` is threaded for call-signature parity with production, and
    the docstring says so -- this is what makes that claim checkable.

    `_compute_reward`'s total cost is import minus export plus wear; none of
    those read the basis, which only rolls forward for profitability
    reporting. A future change that made the objective basis-dependent would
    silently invalidate every measurement seeded from `replay_schedule`, so
    the independence is pinned rather than assumed.
    """
    inputs, diagnostics, result = _run_450_fixture()
    segment = near_miss_segment(
        diagnostics["tie_margins"],
        diagnostics["value_slopes"],
        soe_step_kwh=SOE_STEP_KWH,
    )
    _period_costs, cost_bases = _replay(inputs, result)

    baseline = _reference(inputs, result, segment, cost_bases)
    perturbed = _reference(
        inputs, result, segment, [basis + 0.5 for basis in cost_bases]
    )

    assert perturbed == baseline


@pytest.mark.slow
def test_reference_reads_exactly_the_segments_periods_and_no_others():
    """Off-by-one control for the slicing the rig does internally.

    `segment_reference_cost` slices four horizon-length lists by the segment's
    bounds, and neither the self-consistency test nor any economic assertion
    would catch a one-period shift (the DP is near-optimal on neighbouring
    segments too, so a shifted window still matches to the last digit). This
    pins the boundary directly: perturbing the last period *inside* the
    segment must move the answer, and perturbing the first period *outside* it
    must not. An off-by-one in either direction flips one of the two.

    The perturbed input is `home_consumption`, not a price: this fixture's
    near-miss segment runs entirely on solar with zero grid import, so
    `buy_price` provably cannot affect its cost -- perturbing that would be a
    no-op dressed up as a control.
    """
    inputs, diagnostics, result = _run_450_fixture()
    segment = near_miss_segment(
        diagnostics["tie_margins"],
        diagnostics["value_slopes"],
        soe_step_kwh=SOE_STEP_KWH,
    )
    _period_costs, cost_bases = _replay(inputs, result)
    baseline = _reference(inputs, result, segment, cost_bases)

    def _with_extra_load(period: int):
        perturbed = dict(inputs)
        load = list(inputs["home_consumption"])
        load[period] += 0.5
        perturbed["home_consumption"] = load
        return _reference(perturbed, result, segment, cost_bases)

    assert _with_extra_load(segment.end - 1) != pytest.approx(baseline, abs=1e-6)
    assert _with_extra_load(segment.end) == pytest.approx(baseline, abs=1e-12)


@pytest.mark.slow
def test_segment_reference_refuses_a_segment_longer_than_the_solver_can_certify():
    """Why the segment stays short, pinned as a tested boundary.

    The exact solver seeds every discharge preimage of the next row's
    breakpoints, so its breakpoint set compounds per backward step: on this
    fixture it exhausts `PWL_MAX_PREIMAGE_SEED_POINTS` (1e6) at a horizon of 8
    periods and raises (a horizon of 10 at #512's finer grid). That wall is
    why this reference measures a padded segment rather than the whole
    78-period horizon. The raise is deliberately
    not caught -- an uncertifiable table has no honest use as a reference -- so callers must keep segments at the detector's own pad width.
    """
    inputs, _diagnostics, result = _run_450_fixture()
    _period_costs, cost_bases = _replay(inputs, result)

    with pytest.raises(PWLWindowUnderRefinedError):
        _reference(inputs, result, Window(start=0, end=10), cost_bases)


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
    real, non-zero amount (measured 0.0535 SEK at #512's finer grid), which
    is exactly the kind of finding the suite has to be able to surface.
    (The fixture is swapped from historical_2024_08_16_high_spread_no_solar,
    whose near-miss the finer grid closed to exactly zero.)

    Interpreting the number: it is a *segment* delta with both ends pinned, so
    it under-counts what a free-horizon optimum could win, and it credits any
    grid-quantization gain in those five periods, not only the near-tie
    itself. Both directions are stated in `segment_reference_cost`'s docstring
    and must survive into Task 6's reporting.
    """
    scenario = _at_zero_terminal_value("synthetic_2024_08_16_high_spread_with_solar")
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

    # A positive delta is a constructive witness: the reference is a concrete
    # feasible schedule with identical endpoints, replayed through the DP's own
    # reward function, so this proves the DP left money on the table here --
    # independently of whether the PWL solver itself found the true optimum
    # (it does not always; see the undershoot test above).
    delta = sum(period_costs[segment.start : segment.end]) - reference_cost
    # Re-pinned for Phase 4b (#352): 0.053490 -> 0.051273 SEK. The witness
    # shrank, i.e. the grid DP leaves slightly *less* on the table here now
    # that the exact-cover candidate is in the action space -- still
    # positive, which is what this test asserts the existence of.
    assert delta == pytest.approx(0.051273, abs=1e-5)


@pytest.mark.slow
def test_scenario_with_no_measurable_period_reports_nothing_rather_than_guessing():
    """Not every scenario has a near miss to measure.

    On this fixture every period is a detector blind spot (flat value
    function, or no behaviourally distinct alternative), so there is no
    distance-to-threshold to rank. Returning `None` forces the caller to
    report "nothing measurable" instead of silently measuring an arbitrary
    segment and presenting its economics as a coverage result.
    """
    scenario = _at_zero_terminal_value("historical_2025_01_05_no_spread_no_solar")
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


def test_refuses_to_measure_a_scenario_with_export_curtailment_enabled():
    """Fail fast on the one objective mismatch the harness cannot reproduce.

    With curtailment active, production solves and accounts against a floored
    `reward_sell_price` while this harness threads a single raw `sell_price`
    into both the solve and the replay -- so a delta would be an objective
    mismatch reported as a coverage finding. No fixture sets this today, which
    is exactly why the guard is tested: the failure it prevents is silent.
    """
    battery_settings = BatterySettings(export_curtailment_enabled=True)

    with pytest.raises(NotImplementedError, match="export curtailment"):
        segment_reference_cost(
            Window(start=0, end=2),
            buy_price=[1.0, 1.0],
            sell_price=[0.5, 0.5],
            home_consumption=[1.0, 1.0],
            solar_production=[0.0, 0.0],
            battery_settings=battery_settings,
            dt=0.25,
            soe_trajectory=[2.0, 2.0, 2.0],
            cost_basis=0.4,
            import_cap_kwh=None,
        )


# --------------------------------------------------------------------------
# measure_scenario -- the full harness, wired end to end
# --------------------------------------------------------------------------


@pytest.mark.slow
def test_measure_scenario_reports_a_real_non_zero_near_miss():
    """The "near miss found, financial impact computed" path, end to end.

    Same fixture and segment as
    `test_measures_a_real_near_miss_on_a_scenario_with_no_flags_at_all` above,
    which independently pins the delta at 0.051273 SEK by calling
    `replay_schedule`/`segment_reference_cost` directly. This test exercises
    the same numbers through the public `measure_scenario` entry point, so a
    wiring mistake in `measure_scenario` itself (wrong segment, wrong slice,
    wrong SOE trajectory) would show up here even though the lower-level
    pieces are already covered individually.
    """
    scenario = _at_zero_terminal_value("synthetic_2024_08_16_high_spread_with_solar")

    measurement = measure_scenario(scenario)

    assert isinstance(measurement, ScenarioMeasurement)
    assert sum(measurement.margin_ratio_counts.values()) == len(
        scenario["home_consumption"]
    )
    assert measurement.financial_impact_sek == pytest.approx(0.051273, abs=1e-5)


@pytest.mark.slow
def test_measure_scenario_reports_none_when_nothing_is_measurable():
    """The "no near miss" path: every period is a detector blind spot.

    Mirrors `test_scenario_with_no_measurable_period_reports_nothing_rather_
    than_guessing` above, which pins `near_miss_segment` returning `None`
    directly on this fixture. `measure_scenario` must propagate that as
    `financial_impact_sek=None` rather than measuring an arbitrary segment.
    """
    scenario = _at_zero_terminal_value("historical_2025_01_05_no_spread_no_solar")

    measurement = measure_scenario(scenario)

    assert measurement.financial_impact_sek is None
    assert sum(measurement.margin_ratio_counts.values()) == len(
        scenario["home_consumption"]
    )


def test_refuses_to_measure_a_scenario_with_a_grid_import_cap():
    """The symmetric objective-mismatch guard to the curtailment one above.

    `_scenario_inputs` threads a fixture's `home` block into `home_settings`,
    which `optimize_battery_schedule` turns into a per-period import cap
    constraining every charge decision -- while this harness replays and
    re-solves with `import_cap_kwh=None`. A capped fixture would therefore
    compare two different objectives and report the difference in SEK as a
    coverage finding. No fixture sets a `home` block today, which is exactly
    why the guard is tested: the failure it prevents is silent, and it is
    reached before the (expensive) solve.
    """
    scenario = load_test_scenario("regression_2026_08_02_043728")
    scenario["home"] = {"power_monitoring_enabled": True, "max_fuse_current": 25}

    with pytest.raises(NotImplementedError, match="grid import cap"):
        measure_scenario(scenario)


@pytest.mark.slow
def test_measure_scenario_rejects_a_replay_that_misses_the_reported_objective(
    monkeypatch,
):
    """The live identity check every SEK number in the suite rests on.

    `measure_scenario` asserts that the replayed per-period costs sum to the
    DP's own reported `reward_objective_cost`. That is the generic backstop
    for objective drift -- any future input the replay fails to thread breaks
    this sum first, whether or not anyone wrote a hand-enumerated guard for
    it. Pinned by forcing the replay off by a visible amount.
    """
    scenario = load_test_scenario("historical_2024_08_16_high_spread_no_solar")
    real_replay = measure_tie_coverage.replay_schedule

    def _biased_replay(*args, **kwargs):
        period_costs, cost_bases = real_replay(*args, **kwargs)
        return [cost + 0.01 for cost in period_costs], cost_bases

    monkeypatch.setattr(measure_tie_coverage, "replay_schedule", _biased_replay)

    with pytest.raises(AssertionError, match="reward_objective_cost"):
        measure_scenario(scenario)


@pytest.mark.slow
def test_measure_scenario_floors_a_negative_delta_at_zero(monkeypatch):
    """`segment_reference_cost` can legitimately undershoot the hybrid (a
    known PWL solver limitation, see `segment_reference_cost`'s docstring) --
    when it does, `measure_scenario` must report "no measurable miss"
    (0.0), never a negative "impact". No fixture in the current suite happens
    to trigger a negative delta on its near-miss segment, so this pins the
    flooring directly: monkeypatch `segment_reference_cost` to return a cost
    far above the hybrid's, forcing a negative delta, and assert it comes out
    as 0.0 rather than negative.
    """
    scenario = load_test_scenario("historical_2024_08_16_high_spread_no_solar")
    monkeypatch.setattr(
        measure_tie_coverage,
        "segment_reference_cost",
        lambda *args, **kwargs: 1_000_000.0,
    )

    measurement = measure_scenario(scenario)

    assert measurement.financial_impact_sek == 0.0
