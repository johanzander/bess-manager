"""Measurement harness for the #450 tie-detection coverage validation
suite (see docs/superpowers/specs/2026-08-05-tie-detection-synthetic-
validation-design.md)."""

from core.bess.dp_battery_algorithm import (
    POWER_STEP_KW,
    POWER_TOLERANCE_KW,
    _compute_reward,
)
from core.bess.models import OptimizationResult
from core.bess.pwl_window_dp import (
    resolve_pwl_window,
    run_pwl_window_backward_induction,
)
from core.bess.settings import BatterySettings
from core.bess.tie_detection import Window, epsilon_for_period

# Must equal `detect_tie_windows`' own `pad` default: the measured segment has
# to be exactly the window production would have built around a flagged
# period, or the delta stops being a counterfactual. Pinned by
# `test_segment_padding_matches_the_detectors_own`.
TIE_WINDOW_PAD = 2

_BUCKET_ORDER = ["<0.1x", "0.1x-0.5x", "0.5x-1.0x", "1.0x-2.0x", ">2.0x"]


def _reject_unsupported_objective(battery_settings: BatterySettings) -> None:
    """Fail loudly on a scenario whose production objective this harness does
    not reproduce.

    With export curtailment active, `optimize_battery_schedule` solves and
    accounts against a *floored* `reward_sell_price` (periods below
    `export_curtailment_price_floor` priced at 0.0) while reporting the raw
    `sell_price` on PeriodData. This harness threads a single `sell_price`
    into both the exact solve and the replay, so on such a scenario it would
    compare two different objectives and report the discrepancy as a coverage
    finding. No fixture sets this today; the guard is here so that stays a
    hard failure rather than a silent wrong number when one does.

    Not threaded rather than not supported: adding a floored price path with
    no fixture to exercise it would be untested code on the measurement rig
    itself. Task 5 should thread `reward_sell_price` through both this
    module's functions when a curtailment scenario is first added.

    Same gap, not guardable from here: `max_charge_power_per_period` and
    `discharge_resolution_kw` are optimizer *call arguments* production
    threads into its window solves and this module omits. `_scenario_inputs`
    never sets either today, so no scenario can currently reach the mismatch;
    a caller that starts passing them must thread them into both
    `run_pwl_window_backward_induction` and `resolve_pwl_window` here.
    """
    if battery_settings.export_curtailment_enabled:
        raise NotImplementedError(
            "measure_tie_coverage cannot measure a scenario with export "
            "curtailment enabled: production solves against a floored "
            "reward_sell_price while this harness uses the raw sell_price for "
            "both the exact solve and the replay, so any delta it reported "
            "would be an objective mismatch rather than a coverage finding. "
            "Thread reward_sell_price through replay_schedule and "
            "segment_reference_cost before measuring such a scenario."
        )


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


def near_miss_segment(
    tie_margins: list[float],
    value_slopes: list[float],
    soe_step_kwh: float,
    pad: int = TIE_WINDOW_PAD,
) -> Window | None:
    """The window `detect_tie_windows` *would* have built around the period
    that came closest to the detection threshold without crossing it.

    This is the segment the coverage suite measures. Flagged periods are
    excluded on purpose: the hybrid already re-solved those exactly, so
    measuring one answers nothing about coverage (that case is the rig's
    self-consistency control, not its measurement). The interesting period is
    the nearest *miss* -- the decision the detector came closest to catching
    and didn't -- because that is where a silently-wrong choice is most likely
    to still be worth real money.

    "Closest" is `tie_margin / epsilon`, epsilon being `tie_detection`'s own
    per-period threshold (`TIE_NOISE_FACTOR x soe_step x |dV/dSoE|`), so the
    ratio is a distance to the *detector's* boundary and 1.0 is exactly the
    boundary. Note this differs from `classify_margin_ratios` above, which
    divides by the raw snap noise (no `TIE_NOISE_FACTOR`) to describe the
    theoretical noise floor. Same margins, two deliberately different
    denominators: this one asks "how close to being flagged", that one asks
    "how close to being genuinely reorderable".

    Two period kinds can never be selected, mirroring the detector's own
    documented blind spots: a zero epsilon (flat value function) and an
    infinite margin (no behaviourally distinct alternative to compare
    against) both make the ratio meaningless rather than large. They are
    skipped rather than sorted to the end -- a blind spot is not a near miss,
    and the suite must not report one as if a number had been measured. When
    no period yields a formable ratio, returns `None`: "this scenario has
    nothing measurable", which callers must report as such rather than
    substituting an arbitrary segment.

    `pad` matches `detect_tie_windows`' default so the measured segment is
    exactly the one production would have re-solved -- that identity is what
    makes the resulting delta a genuine counterfactual ("what flagging this
    period would have been worth") instead of an arbitrary slice's economics.
    """
    horizon = len(tie_margins)
    if len(value_slopes) != horizon:
        raise ValueError(
            f"value_slopes has {len(value_slopes)} entries but tie_margins has "
            f"{horizon} -- they must be recorded per period in the same pass"
        )

    best_period: int | None = None
    best_ratio = float("inf")
    for t in range(horizon):
        epsilon = epsilon_for_period(value_slopes[t], soe_step_kwh)
        margin = tie_margins[t]
        if epsilon <= 0.0 or margin == float("inf"):
            continue
        if margin < epsilon:  # already flagged and re-solved by the hybrid
            continue
        ratio = margin / epsilon
        if ratio < best_ratio:
            best_ratio = ratio
            best_period = t

    if best_period is None:
        return None
    return Window(
        start=max(0, best_period - pad),
        end=min(horizon, best_period + pad + 1),
    )


def replay_schedule(
    result: OptimizationResult,
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    solar_production: list[float],
    battery_settings: BatterySettings,
    dt: float,
    initial_soe: float,
    initial_cost_basis: float | None,
    self_throttle_export_threshold_kwh: float,
    import_cap_kwh: float | None,
) -> tuple[list[float], list[float]]:
    """Per-period objective cost and per-period opening cost basis of an
    `OptimizationResult`'s schedule.

    `OptimizationResult` reports only the horizon total
    (`reward_objective_cost`), but a segment comparison needs that total's
    share for a slice of periods, and the exact reference solve needs the cost
    basis the DP was carrying when the segment opened. Both come from
    replaying the returned `PeriodData` through `_compute_reward` -- the same
    function, in the same order, that produced the reported total, so
    `sum(period_costs)` reproduces it exactly (pinned by
    `test_replay_reproduces_the_reported_reward_objective_cost`).

    `power` is reconstructed from `decision.battery_action` (kWh, + charge /
    - discharge), never from `energy.battery_charged`: an IDLE period whose
    surplus solar passively charges the battery reports a positive
    `battery_charged` while not being a STORE action, and feeding that back as
    `power` flips it into the charge branch of `_compute_reward` (measured:
    -2.18 vs the true -5.98 SEK on the #450 fixture). STORE's own power
    magnitude is not recoverable -- `_build_period_data` reports achieved
    throughput instead (#203) -- but STORE physics are binary, so any power
    above the tolerance replays the identical action.

    Returns `(period_costs, cost_bases)` where `cost_bases[t]` is the basis
    *entering* period `t`, so `cost_bases[segment.start]` is what
    `segment_reference_cost` should be seeded with.
    """
    _reject_unsupported_objective(battery_settings)
    soe = initial_soe
    cost_basis = (
        initial_cost_basis
        if initial_cost_basis is not None
        else battery_settings.cycle_cost_per_kwh
    )
    period_costs: list[float] = []
    cost_bases: list[float] = []
    for t, period in enumerate(result.period_data):
        action_kwh = period.decision.battery_action or 0.0
        if action_kwh > POWER_TOLERANCE_KW * dt:
            power = POWER_STEP_KW
        elif action_kwh < -POWER_TOLERANCE_KW * dt:
            power = action_kwh / dt
        else:
            power = 0.0
        next_soe = period.energy.battery_soe_end
        cost_bases.append(cost_basis)
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
        period_costs.append(-reward)
        soe = next_soe
    return period_costs, cost_bases


def segment_reference_cost(
    segment: Window,
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    solar_production: list[float],
    battery_settings: BatterySettings,
    dt: float,
    soe_trajectory: list[float],
    cost_basis: float,
    self_throttle_export_threshold_kwh: float,
    import_cap_kwh: float | None,
) -> float:
    """Objective cost over `segment` as re-solved by the continuous-SOE PWL
    DP, pinned to the schedule's own SOE at both ends.

    NOT A PROVEN OPTIMUM, and the difference is load-bearing for how a caller
    may phrase a delta. This is "what the PWL solver achieves on these
    periods", not "what the best possible schedule costs". The PWL backward
    induction is itself measurably suboptimal on real data: on
    `historical_2024_08_16_high_spread_no_solar` segment 7-12 it returns
    42.679610 SEK against a DP path costing 42.648857 -- 0.031 SEK *worse*
    -- with both endpoints identical, the pin honoured exactly, and every
    action on the cheaper path inside `_backward_discharge_levels`' own grid
    (the paths differ only at one intermediate SOE, 5.46 vs 5.64 kWh). The
    solver's `V[0]` agrees with its own replayed cost to 1e-6, so the loss is
    in the backward induction, not the forward resolver -- i.e. a row is
    missing a kink its refinement did not detect, which its
    `PWL_EPS_REFINE`-based certification did not catch. Pinned by
    `test_reference_can_undershoot_the_hybrid_a_known_solver_limitation`.

    Reading a delta (`hybrid_cost - reference_cost`) in light of that:
    - POSITIVE is a sound constructive witness. The reference is a concrete
      feasible schedule with identical endpoints, replayed through the DP's
      own reward function, so a positive delta proves the DP left that much on
      the table -- whether or not the PWL solver found the true optimum.
    - NEGATIVE means the PWL solver undershot on this segment. It is solver
      noise, NOT a harness failure and not a signal the DP did something
      right; there is nothing for a caller to investigate. Callers should
      report such segments as "no measurable miss" (floor the delta at zero)
      rather than as a negative saving.
    - Either way the magnitude is a LOWER BOUND on the true miss cost: pinning
      both ends forbids the reference from banking energy differently outside
      the segment, so a better global plan needing a different boundary SOE is
      out of reach by construction.

    Scope: this answers "what would re-solving these periods have been worth,
    holding everything outside them fixed" -- the counterfactual value of
    flagging one period -- not "what would a globally optimal schedule have
    cost". Reporting it as the total cost of a missed tie would overstate what
    was verified.

    That scoping is forced, not chosen. The solver's breakpoint set
    compounds per backward step (it seeds every discharge preimage of the next
    row's breakpoints), exhausting `PWL_MAX_PREIMAGE_SEED_POINTS` at a horizon
    of 8 periods on the #450 fixture -- a 78-period exact solve is not
    reachable by raising budgets. See
    `test_segment_reference_refuses_a_segment_longer_than_the_solver_can_certify`.
    The upside of the constraint is that cost is independent of the scenario's
    length: a 192-period scenario measures exactly as fast as a 24-period one.

    Pinning to the incumbent SOE at both ends is the same technique the
    production hybrid path uses when it splices a re-solved window
    (`dp_battery_algorithm.py` Step 2b).

    A segment may legitimately overlap a window the hybrid already resolved
    with this same solver; the delta is then zero by construction. That is a
    correct result, not a measurement -- such a segment carries no information
    about detector coverage, since the detector did catch it.

    `soe_trajectory` is the schedule's realized SOE per period boundary,
    length `horizon + 1`; the pins are read from it at `segment.start` and
    `segment.end`. Pass the *post-splice* trajectory (from
    `result.period_data`), not `tie_diagnostics["soe_trajectory"]`, which is
    recorded before the hybrid splices and so differs inside a resolved
    window.

    `cost_basis` should be the basis entering `segment.start` (from
    `replay_schedule`), but the returned cost does not depend on it: it is
    threaded only for parity with production's `resolve_pwl_window` call.
    `_compute_reward`'s `total_cost` is import cost minus export revenue plus
    wear, none of which read the basis -- the basis is carried for
    profitability reporting and rolls forward as `new_cost_basis`. Verified by
    `test_reference_cost_does_not_depend_on_cost_basis`; do not infer from
    this parameter that a mis-seeded basis would corrupt a measurement.

    The returned number is directly comparable to a slice of
    `replay_schedule`'s `period_costs`: same accumulation (negated
    `_compute_reward`, summed), and terminal value enters neither, so equal
    end SOE makes the comparison exact.

    Raises `PWLWindowUnderRefinedError` if the segment is too long for the
    solver to certify, and `RuntimeError` if the pinned end SOE is
    unreachable. Neither is caught here: an uncertifiable or infeasible table
    has no honest use as a reference, and a caller that swallowed either would
    report a fabricated 0.00 SEK delta.
    """
    _reject_unsupported_objective(battery_settings)
    sl = slice(segment.start, segment.end)
    window_horizon = segment.end - segment.start
    segment_buy = buy_price[sl]
    segment_sell = sell_price[sl]
    segment_load = home_consumption[sl]
    segment_solar = solar_production[sl]
    start_soe = soe_trajectory[segment.start]

    V = run_pwl_window_backward_induction(
        window_horizon=window_horizon,
        buy_price=segment_buy,
        sell_price=segment_sell,
        home_consumption=segment_load,
        solar_production=segment_solar,
        battery_settings=battery_settings,
        dt=dt,
        end_soe_target=soe_trajectory[segment.end],
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        import_cap_kwh=import_cap_kwh,
    )
    actions = resolve_pwl_window(
        V,
        start_soe=start_soe,
        window_horizon=window_horizon,
        buy_price=segment_buy,
        sell_price=segment_sell,
        home_consumption=segment_load,
        solar_production=segment_solar,
        battery_settings=battery_settings,
        dt=dt,
        cost_basis=cost_basis,
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        import_cap_kwh=import_cap_kwh,
    )

    soe = start_soe
    basis = cost_basis
    reference_cost = 0.0
    for t, (power, next_soe) in enumerate(actions):
        reward, basis, _grid_imported = _compute_reward(
            power=power,
            soe=soe,
            next_soe=next_soe,
            period=t,
            home_consumption=segment_load[t],
            battery_settings=battery_settings,
            dt=dt,
            buy_price=segment_buy,
            sell_price=segment_sell,
            solar_production=segment_solar[t],
            cost_basis=basis,
            self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
            import_cap_kwh=import_cap_kwh,
        )
        reference_cost -= reward
        soe = next_soe

    return reference_cost
