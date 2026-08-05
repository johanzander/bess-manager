"""Measurement harness for the #450 tie-detection coverage validation
suite (see docs/superpowers/specs/2026-08-05-tie-detection-synthetic-
validation-design.md)."""

from core.bess.dp_battery_algorithm import _compute_reward
from core.bess.pwl_window_dp import (
    resolve_pwl_window,
    run_pwl_window_backward_induction,
)

_BUCKET_ORDER = ["<0.1x", "0.1x-0.5x", "0.5x-1.0x", "1.0x-2.0x", ">2.0x"]


def _bucket_for_ratio(ratio: float) -> str:
    if ratio < 0.1:
        return "<0.1x"
    if ratio < 0.5:
        return "0.1x-0.5x"
    if ratio < 1.0:
        return "0.5x-1.0x"
    if ratio < 2.0:
        return "1.0x-2.0x"
    return ">2.0x"


def classify_margin_ratios(
    tie_margins: list[float], value_slopes: list[float], soe_step_kwh: float
) -> dict[str, int]:
    counts = dict.fromkeys(_BUCKET_ORDER, 0)
    for margin, slope in zip(tie_margins, value_slopes, strict=True):
        worst_case_noise = soe_step_kwh * abs(slope)
        ratio = margin / worst_case_noise if worst_case_noise > 0 else float("inf")
        counts[_bucket_for_ratio(ratio)] += 1
    return counts


def full_horizon_reference_cost(
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    solar_production: list[float],
    battery_settings,
    dt: float,
    start_soe: float,
    end_soe_target: float,
    initial_cost_basis: float,
    self_throttle_export_threshold_kwh: float,
    import_cap_kwh: float | None,
) -> float:
    """Exact reward-objective cost of the whole horizon, solved with no
    windowing restriction -- the "true optimal" reference this validation
    suite compares the hybrid's (possibly partial-coverage) result against.

    Pinned to `end_soe_target` (the grid DP's own realized final SOE) rather
    than a free terminal state -- an accepted approximation, see
    docs/superpowers/specs/2026-08-05-tie-detection-synthetic-validation-design.md.

    HORIZON LIMIT -- read before sizing a call. Despite the name, this cannot
    actually solve a full 24h/78-period horizon, and no parameter of this
    function changes that. `run_pwl_window_backward_induction` seeds every
    discharge preimage of the next row's breakpoints, so the breakpoint set
    grows geometrically going backwards; on the #450 fixture it exhausts
    `PWL_MAX_PREIMAGE_SEED_POINTS` (1e6) at a horizon of 8 periods and raises
    `PWLWindowUnderRefinedError`. That error is deliberately not caught here:
    an uncertifiable value table has no honest use as a "true optimal"
    reference. Callers must size the horizon to what the solver can certify
    (~6-7 periods on quarterly data, data-dependent) and treat the raise as a
    real answer -- "no reference available for this horizon" -- not as a
    failure to work around. See
    `test_full_horizon_solve_exhausts_the_exact_solvers_accuracy_budget`.

    The returned number is directly comparable to
    `OptimizationResult.reward_objective_cost`: it is accumulated the same
    way the DP's own forward/replay pass does it, by negating each period's
    `_compute_reward` and summing. Terminal value never enters either number,
    so pinning both runs to the same final SOE keeps the comparison exact.
    """
    horizon = len(buy_price)
    V = run_pwl_window_backward_induction(
        window_horizon=horizon,
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        battery_settings=battery_settings,
        dt=dt,
        end_soe_target=end_soe_target,
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        import_cap_kwh=import_cap_kwh,
    )
    actions = resolve_pwl_window(
        V,
        start_soe=start_soe,
        window_horizon=horizon,
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        battery_settings=battery_settings,
        dt=dt,
        cost_basis=initial_cost_basis,
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        import_cap_kwh=import_cap_kwh,
    )

    soe = start_soe
    cost_basis = initial_cost_basis
    reward_objective_cost = 0.0
    for t, (power, next_soe) in enumerate(actions):
        reward, cost_basis, _grid_imported = _compute_reward(
            power=power,
            soe=soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            buy_price=buy_price,
            sell_price=sell_price,
            solar_production=solar_production[t],
            cost_basis=cost_basis,
            self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
            import_cap_kwh=import_cap_kwh,
        )
        reward_objective_cost -= reward
        soe = next_soe

    return reward_objective_cost
