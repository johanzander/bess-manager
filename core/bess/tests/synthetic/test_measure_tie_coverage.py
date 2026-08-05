import pytest

from core.bess.dp_battery_algorithm import (
    BATTERY_EXPORT_THRESHOLD_KWH,
    POWER_TOLERANCE_KW,
    _compute_reward,
    optimize_battery_schedule,
)
from core.bess.pwl_window_dp import PWLWindowUnderRefinedError
from core.bess.tests.helpers import _scenario_inputs
from core.bess.tests.synthetic.measure_tie_coverage import (
    classify_margin_ratios,
    full_horizon_reference_cost,
)
from core.bess.tests.unit.test_scenarios import load_test_scenario


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


def _hybrid_prefix_cost(
    result, inputs, initial_cost_basis: float, periods: int
) -> float:
    """The hybrid schedule's own `reward_objective_cost` restricted to its
    first `periods` periods, replayed from the returned PeriodData.

    Needed because `OptimizationResult` reports only the horizon total. The
    replay is verified against that total in
    `test_prefix_replay_reproduces_the_reported_reward_objective_cost`, so a
    drift between this reconstruction and the DP's own accounting fails
    loudly rather than quietly biasing the comparison.

    `power` is reconstructed from `decision.battery_action` (kWh, + charge /
    - discharge), not from `energy.battery_charged`: an IDLE period whose
    surplus solar passively charges the battery reports a positive
    `battery_charged` but is not a STORE action, and feeding that back as
    `power` would flip it into the charge branch of `_compute_reward`. STORE
    physics are binary (see `_build_period_data`'s #203 note), so any power
    above the tolerance replays the identical action.
    """
    dt = inputs["period_duration_hours"]
    soes = [inputs["initial_soe"]] + [
        p.energy.battery_soe_end for p in result.period_data
    ]
    cost_basis = initial_cost_basis
    prefix_cost = 0.0
    for t in range(periods):
        action_kwh = result.period_data[t].decision.battery_action or 0.0
        if action_kwh > POWER_TOLERANCE_KW * dt:
            power = 1.0
        elif action_kwh < -POWER_TOLERANCE_KW * dt:
            power = action_kwh / dt
        else:
            power = 0.0
        reward, cost_basis, _grid_imported = _compute_reward(
            power=power,
            soe=soes[t],
            next_soe=soes[t + 1],
            period=t,
            home_consumption=inputs["home_consumption"][t],
            battery_settings=inputs["battery_settings"],
            dt=dt,
            buy_price=inputs["buy_price"],
            sell_price=inputs["sell_price"],
            solar_production=inputs["solar_production"][t],
            cost_basis=cost_basis,
            self_throttle_export_threshold_kwh=BATTERY_EXPORT_THRESHOLD_KWH,
            import_cap_kwh=None,
        )
        prefix_cost -= reward
    return prefix_cost


def _run_450_fixture():
    scenario = load_test_scenario("regression_2026_08_02_043728")
    inputs = _scenario_inputs(scenario)
    diagnostics: dict = {}
    result = optimize_battery_schedule(**inputs, tie_diagnostics=diagnostics)
    return inputs, diagnostics, result


@pytest.mark.slow
def test_prefix_replay_reproduces_the_reported_reward_objective_cost():
    inputs, diagnostics, result = _run_450_fixture()

    replayed = _hybrid_prefix_cost(
        result,
        inputs,
        diagnostics["resolved_initial_cost_basis"],
        len(result.period_data),
    )

    assert replayed == pytest.approx(result.reward_objective_cost, abs=1e-9)


@pytest.mark.slow
def test_reference_matches_or_beats_the_hybrid_on_a_450_fixture_prefix():
    # Six periods, not the fixture's full 78: the exact PWL solver's
    # breakpoint set grows geometrically backwards and exhausts
    # PWL_MAX_PREIMAGE_SEED_POINTS at 8 periods on this fixture (pinned by
    # test_full_horizon_solve_exhausts_the_exact_solvers_accuracy_budget
    # below). Six is the largest round horizon that solves comfortably.
    periods = 6
    inputs, diagnostics, result = _run_450_fixture()

    reference_cost = full_horizon_reference_cost(
        buy_price=inputs["buy_price"][:periods],
        sell_price=inputs["sell_price"][:periods],
        home_consumption=inputs["home_consumption"][:periods],
        solar_production=inputs["solar_production"][:periods],
        battery_settings=inputs["battery_settings"],
        dt=inputs["period_duration_hours"],
        start_soe=diagnostics["soe_trajectory"][0],
        end_soe_target=diagnostics["soe_trajectory"][periods],
        initial_cost_basis=diagnostics["resolved_initial_cost_basis"],
        self_throttle_export_threshold_kwh=BATTERY_EXPORT_THRESHOLD_KWH,
        import_cap_kwh=None,
    )

    # The exact solve over this sub-horizon, pinned to the hybrid's own start
    # and end SOE, can only match or beat the hybrid's cost over the same
    # periods -- it is solving the same problem with no grid snapping. On
    # this fixture the two agree exactly (delta 0.000000 SEK), i.e. the grid
    # DP's first six decisions are provably optimal.
    assert reference_cost <= (
        _hybrid_prefix_cost(
            result, inputs, diagnostics["resolved_initial_cost_basis"], periods
        )
        + 1e-6
    )


@pytest.mark.slow
def test_full_horizon_solve_exhausts_the_exact_solvers_accuracy_budget():
    """The 78-period exact solve this helper was specified for is not
    computable, and that is a property of the solver, not of this call.

    `run_pwl_window_backward_induction` seeds every discharge preimage of the
    next row's breakpoints, so |breakpoints| grows geometrically going
    backwards; on the #450 fixture it blows PWL_MAX_PREIMAGE_SEED_POINTS
    (1e6) at horizon 8. Because the requirement compounds per backward step
    rather than growing linearly, a 78-period solve is not reachable by
    raising the budget. Pinned here so the limit is a documented, tested
    boundary rather than a surprise for callers sizing a horizon.
    """
    periods = 8
    inputs, diagnostics, _result = _run_450_fixture()

    with pytest.raises(PWLWindowUnderRefinedError):
        full_horizon_reference_cost(
            buy_price=inputs["buy_price"][:periods],
            sell_price=inputs["sell_price"][:periods],
            home_consumption=inputs["home_consumption"][:periods],
            solar_production=inputs["solar_production"][:periods],
            battery_settings=inputs["battery_settings"],
            dt=inputs["period_duration_hours"],
            start_soe=diagnostics["soe_trajectory"][0],
            end_soe_target=diagnostics["soe_trajectory"][periods],
            initial_cost_basis=diagnostics["resolved_initial_cost_basis"],
            self_throttle_export_threshold_kwh=BATTERY_EXPORT_THRESHOLD_KWH,
            import_cap_kwh=None,
        )
