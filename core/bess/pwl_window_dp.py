"""Windowed piecewise-linear (PWL) DP for exact resolution of near-tied
decisions flagged by core.bess.tie_detection (#450).

This is the exact-PWL backward induction originally prototyped as the
reference implementation on the PR #461 branch (continuous SOE, no grid
snapping, proven exact to ~1e-10 against the true optimum), narrowed here
to run over a short sub-horizon window with pinned start/end SOE instead
of the full schedule -- see
docs/superpowers/specs/2026-08-04-hybrid-dp-pwl-tie-resolution-design.md
for why only the tied window gets this treatment instead of the whole
horizon.
"""

import numpy as np

from core.bess.dp_battery_algorithm import (
    BATTERY_EXPORT_THRESHOLD_KWH,
    POWER_CLASSIFICATION_THRESHOLD_KW,
    POWER_TOLERANCE_KW,
    BatterySettings,
    _charge_candidate,
    _compute_reward,
    _compute_reward_grid,
    _discharge_candidates,
    _effective_ac_cap_kwh,
    _soe_floor,
    _state_transition,
    _state_transition_grid,
)
from core.bess.dp_constants import POWER_STEP_KW

PWL_EPS_REFINE = 1e-6
PWL_EPS_PRUNE = 1e-6


class PWLWindowUnderRefinedError(RuntimeError):
    """The windowed PWL solve hit one of its own accuracy budgets, so the
    value table it would return is an approximation of unknown quality.

    Distinct from the *infeasible* case (`pwl_window_is_feasible`), which is
    an ordinary physical outcome the solver reports honestly. This one means
    the solver cannot certify its own answer at all: the only reason the
    hybrid path (#450) re-solves a window is that the grid DP's result on it
    is not trustworthy to within tie-margin accuracy, so handing back a
    result of *unknown* accuracy and letting it be spliced in as if exact
    would replace one silent inaccuracy with another -- precisely the
    fallback `docs/agents/rules.md` forbids. Raising instead makes the
    condition impossible to miss; the budgets themselves (see
    `PWL_MAX_BREAKPOINTS`, `PWL_MAX_REFINE_ITERS`,
    `PWL_MAX_PREIMAGE_SEED_POINTS`) are the knobs to revisit if it ever
    fires in practice -- it fires on none of the fixture suite's scenarios.
    """


def _pwl_prune(xs: np.ndarray, vs: np.ndarray, eps: float = PWL_EPS_PRUNE):
    """Drop interior breakpoints whose removal changes the PWL function by
    at most `eps` (collinearity within tolerance). Non-adjacent removals per
    pass so each removal's error stays measured against surviving points."""
    while len(xs) > 2:
        x0, x1, x2 = xs[:-2], xs[1:-1], xs[2:]
        v0, v1, v2 = vs[:-2], vs[1:-1], vs[2:]
        frac = (x1 - x0) / (x2 - x0)
        chord = v0 + frac * (v2 - v0)
        removable = np.abs(v1 - chord) <= eps
        if not removable.any():
            break
        keep = np.ones(len(xs), dtype=bool)
        last_removed = -2
        for i in np.nonzero(removable)[0]:
            idx = i + 1
            if idx - last_removed >= 2:
                keep[idx] = False
                last_removed = idx
        xs, vs = xs[keep], vs[keep]
    return xs, vs


def _backward_discharge_levels(
    battery_settings: BatterySettings,
    discharge_resolution_kw: float | None,
) -> np.ndarray:
    """Discharge power levels (kW, positive) for the backward pass: the same
    hardware-true integer-percent grid `_discharge_candidates` enumerates at
    replay, including its classification-threshold floor. Using one action
    set in both passes is what makes the replayed schedule achieve exactly
    the value the backward pass promised (no snap/interpolation residual for
    replay to fall short of)."""
    rate_step = (
        discharge_resolution_kw
        if discharge_resolution_kw is not None
        else battery_settings.max_discharge_power_kw / 100
    )
    max_pct = int(np.floor(battery_settings.max_discharge_power_kw / rate_step + 1e-9))
    min_pct = int(np.floor(POWER_CLASSIFICATION_THRESHOLD_KW / rate_step)) + 1
    return np.array([pct * rate_step for pct in range(min_pct, max_pct + 1)])


def _pwl_candidate_values_at(
    X: np.ndarray,
    t: int,
    V_next: tuple[np.ndarray, np.ndarray],
    power_row: np.ndarray,
    horizon_inputs,
    battery_settings: BatterySettings,
    dt: float,
    period_max_charge: float | None,
    self_throttle_export_threshold_kwh: float,
) -> np.ndarray:
    """Best achievable value at each SOE in `X` for period `t`: max over the
    shared action set (IDLE, STORE, discharge grid) plus the
    SOLAR_EXPORT-below-max bypass (#313), with V[t+1] evaluated exactly at
    each candidate's true (continuous) next_soe -- no state snapping."""
    buy_price, sell_price, home_consumption, solar_production = horizon_inputs
    min_soe = battery_settings.min_soe_kwh
    max_soe = battery_settings.max_soe_kwh
    soe_col = X.reshape(-1, 1)

    is_charge = power_row > POWER_TOLERANCE_KW
    is_discharge = power_row < -POWER_TOLERANCE_KW

    next_soe = _state_transition_grid(
        soe_col,
        power_row,
        battery_settings,
        dt,
        solar_production=solar_production[t],
        home_consumption=home_consumption[t],
    )
    reward = _compute_reward_grid(
        power_row,
        soe_col,
        next_soe,
        home_consumption=home_consumption[t],
        battery_settings=battery_settings,
        dt=dt,
        current_buy_price=buy_price[t],
        current_sell_price=sell_price[t],
        solar_production=solar_production[t],
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
    )

    # STORE feasibility: the same rule replay's _charge_candidate applies
    # (binary store physics -- one representative positive power stands in
    # for every feasible charge action).
    max_charge_power = (max_soe - soe_col) / dt / battery_settings.efficiency_charge
    if period_max_charge is not None:
        max_charge_power = np.minimum(max_charge_power, period_max_charge)
    feasible = ~is_charge | (max_charge_power > POWER_CLASSIFICATION_THRESHOLD_KW)

    max_discharge_power = (
        (soe_col - min_soe) / dt * battery_settings.efficiency_discharge
    )
    feasible &= ~is_discharge | (np.abs(power_row) <= max_discharge_power)
    ac_cap_kwh = _effective_ac_cap_kwh(battery_settings, dt)
    if ac_cap_kwh is not None:
        # Battery discharge shares the inverter's AC stage with PV
        # conversion — only the headroom the (possibly clipped) solar
        # leaves is deliverable.
        ac_headroom_kwh = max(0.0, ac_cap_kwh - min(solar_production[t], ac_cap_kwh))
        feasible &= ~is_discharge | (np.abs(power_row) * dt <= ac_headroom_kwh)
    feasible &= (next_soe >= min_soe) & (next_soe <= max_soe)

    value = reward + _pwl_eval_array(V_next, next_soe)
    value = np.where(feasible, value, -np.inf)

    # SOLAR_EXPORT-below-max candidate (#313): soe held exactly unchanged
    # (next_soe == soe), solar surplus exports directly instead of passively
    # charging. Reusing _compute_reward_grid with next_soe == soe already
    # produces the correct economics (see _idle_battery_flows: zero SOE
    # delta -> battery_charged=0, so grid_exported reflects the full
    # surplus). With the AC cap set, this candidate is also what defers
    # charging to preserve headroom for above-cap solar.
    zeros_col = np.zeros_like(soe_col)
    reward_bypass = _compute_reward_grid(
        zeros_col,
        soe_col,
        soe_col,
        home_consumption=home_consumption[t],
        battery_settings=battery_settings,
        dt=dt,
        current_buy_price=buy_price[t],
        current_sell_price=sell_price[t],
        solar_production=solar_production[t],
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
    )
    value_bypass = reward_bypass + _pwl_eval_array(V_next, soe_col)

    # IDLE and bypass are always feasible with finite reward, so the max
    # over actions can never remain -inf.
    return np.maximum(value.max(axis=1), value_bypass.reshape(-1))


def _pwl_eval_array(
    V_row: tuple[np.ndarray, np.ndarray], soe: np.ndarray
) -> np.ndarray:
    """Evaluate a PWL value-function row `(xs, vs)` at an array of SOE
    values. Between breakpoints this is exact (the representation IS
    piecewise linear); below the first breakpoint the first segment's
    gradient is extrapolated -- see `_pwl_best_action_at_continuous_state`'s
    #336 note."""
    xs, vs = V_row
    result = np.interp(soe, xs, vs)
    if len(xs) > 1:
        first_slope = (vs[1] - vs[0]) / (xs[1] - xs[0])
        result = np.where(soe < xs[0], vs[0] + (soe - xs[0]) * first_slope, result)
    return result


def _pwl_best_action_at_continuous_state(
    soe: float,
    t: int,
    V_next: tuple[np.ndarray, np.ndarray],
    power_levels: np.ndarray,
    home_consumption: list[float],
    battery_settings: BatterySettings,
    dt: float,
    solar_production: list[float],
    buy_price: list[float],
    sell_price: list[float],
    cost_basis: float,
    max_charge_power_per_period: list[float] | None,
    discharge_resolution_kw: float | None = None,
    self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
) -> tuple[float, float, float, float]:
    """One-step Bellman recompute at a true continuous SoE, using the
    already-known V[t+1, :] (linearly interpolated) as the continuation
    value -- the same reward+max(V) logic as the PWL backward pass, applied
    at the true replay state instead of one snapped to the nearest grid
    index. See
    docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md.

    Candidate actions are the exact breakpoints of the piecewise-linear
    reward+continuation objective (see
    docs/superpowers/specs/2026-07-12-dp-continuous-action-reformulation-design.md)
    rather than a fixed power grid -- `power_levels` is unused for the
    search itself, kept only for call-site compatibility with
    `_discretize_state_action_space`.

    Returns (best_action, best_next_soe, best_new_cost_basis, best_reward).
    """
    period_max_charge = (
        max_charge_power_per_period[t]
        if max_charge_power_per_period is not None
        else None
    )
    home = home_consumption[t]
    solar = solar_production[t]
    ac_cap_kwh = _effective_ac_cap_kwh(battery_settings, dt)

    best_value = float("-inf")
    best_action = 0.0
    best_next_soe = soe
    best_new_cost_basis = cost_basis
    best_reward = 0.0

    def consider(power: float) -> None:
        nonlocal best_value, best_action, best_next_soe, best_new_cost_basis
        nonlocal best_reward
        next_soe = _state_transition(
            soe,
            power,
            battery_settings,
            dt,
            solar_production=solar,
            home_consumption=home,
        )
        # See _soe_floor's docstring (#233): the feasible floor for this
        # candidate is soe itself until real charging crosses back above
        # min_soe_kwh.
        if (
            next_soe < _soe_floor(soe, battery_settings)
            or next_soe > battery_settings.max_soe_kwh
        ):
            return
        reward, new_cost_basis = _compute_reward(
            power=power,
            soe=soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home,
            battery_settings=battery_settings,
            dt=dt,
            solar_production=solar,
            buy_price=buy_price,
            sell_price=sell_price,
            cost_basis=cost_basis,
            self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        )
        value = reward + float(_pwl_eval_array(V_next, np.asarray(next_soe)))
        if value > best_value:
            best_value = value
            best_action = power
            best_next_soe = next_soe
            best_new_cost_basis = new_cost_basis
            best_reward = reward

    # IDLE -- always a feasible candidate.
    consider(0.0)

    # SOLAR_EXPORT-below-max (#313): soe held exactly unchanged, this
    # period's own solar surplus exports directly instead of passively
    # charging -- see the PWL backward pass's matching candidate for the
    # full rationale. Bypasses _state_transition (whose power=0 branch
    # always charges as much as room/rate permit) to force next_soe == soe
    # directly, then reuses the same _compute_reward call every other
    # candidate uses.
    reward, new_cost_basis = _compute_reward(
        power=0.0,
        soe=soe,
        next_soe=soe,
        period=t,
        home_consumption=home,
        battery_settings=battery_settings,
        dt=dt,
        solar_production=solar,
        buy_price=buy_price,
        sell_price=sell_price,
        cost_basis=cost_basis,
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
    )
    value = reward + float(_pwl_eval_array(V_next, np.asarray(soe)))
    if value > best_value:
        best_value = value
        best_action = 0.0
        best_next_soe = soe
        best_new_cost_basis = new_cost_basis
        best_reward = reward

    # Discharge -- exact breakpoint enumeration (Finding 1/2/3/5).
    for p in _discharge_candidates(
        soe,
        battery_settings,
        dt,
        home,
        solar,
        discharge_resolution_kw=discharge_resolution_kw,
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        ac_cap_kwh=ac_cap_kwh,
    ):
        consider(-p)

    # Charge (STORE) -- Finding 4: no grid search needed on this side at
    # all, a single representative candidate fully covers it.
    charge_candidate = _charge_candidate(soe, battery_settings, dt, period_max_charge)
    if charge_candidate is not None:
        consider(charge_candidate)

    return best_action, best_next_soe, best_new_cost_basis, best_reward


# Penalty gradient (SEK/kWh) applied outside the pinned terminal band. Chosen
# six orders of magnitude above any realistic window-scale economics (a few
# kWh moved across a spread of a few SEK/kWh), so the pin always dominates
# the objective, while staying finite -- see `_pinned_terminal_row`.
PWL_TERMINAL_PENALTY_PER_KWH = 1e6

# Largest end-SOE miss (kWh) a resolved window may carry and still be spliced
# back into the grid DP's schedule. Well below `SOE_STEP_KWH`, the grid DP's
# own state resolution, so a miss this small cannot change anything
# downstream of the window.
PWL_WINDOW_MAX_PIN_SHORTFALL_KWH = 0.01

# The V[0] value at or below which a window counts as infeasible -- see
# `pwl_window_is_feasible`, which is what callers should use.
PWL_WINDOW_INFEASIBLE_SEK = -(
    PWL_TERMINAL_PENALTY_PER_KWH * PWL_WINDOW_MAX_PIN_SHORTFALL_KWH
)

# Adaptive-refinement guards, matching the reference PWL prototype.
PWL_MAX_REFINE_ITERS = 40

# Ceiling on |X| (breakpoints per row) during refinement.
PWL_MAX_BREAKPOINTS = 30000

# Separate, much larger budget for the *transient* discharge-preimage cross
# product in `_pwl_window_seed_points` (|xs_next| x |discharge levels|). It is
# built, deduped and pruned within a single seeding call, so it is bounded by
# memory (1e6 float64 ~ 8 MB), not by the per-row breakpoint ceiling. These
# were one constant until review: sharing `PWL_MAX_BREAKPOINTS` silently
# disabled exact preimage seeding on every row after the first backward step
# (|xs_next| > ~303 already trips 303 x 98 > 30000), i.e. the mechanism was
# off exactly where it was documented to be required.
PWL_MAX_PREIMAGE_SEED_POINTS = 1_000_000

# Two distinct tolerances that were previously ad-hoc literals:
# points closer than this are the same breakpoint...
_PWL_MERGE_EPS_KWH = 1e-12
# ...and intervals narrower than this are not worth probing again.
_PWL_MIN_PROBE_WIDTH_KWH = 1e-8


def _end_soe_pin_tolerance(
    end_soe_tolerance: float,
    battery_settings: BatterySettings,
    dt: float,
    discharge_resolution_kw: float | None,
) -> float:
    """The pin's half-width, floored at half the discharge action lattice's
    SOE step.

    A tolerance finer than the lattice is unsatisfiable by construction:
    from any SOE the reachable end states are spaced
    `rate_step * dt / efficiency_discharge` apart (0.0132 kWh for a 5 kW
    battery on 15-minute periods), so a 1e-6 band is generically empty. The
    terminal penalty then degenerates into a sawtooth of amplitude
    `PWL_TERMINAL_PENALTY_PER_KWH * step / 2` -- thousands of SEK -- which
    swamps the cents-scale economics the window is being re-solved to
    compare, i.e. it would replace grid-snap tie noise with lattice-snap tie
    noise. Flooring at half a step makes the nearest reachable state always
    land inside the band, so the penalty is exactly 0 across the whole
    reachable region and economics decides, as intended.
    """
    rate_step = (
        discharge_resolution_kw
        if discharge_resolution_kw is not None
        else battery_settings.max_discharge_power_kw / 100
    )
    lattice_step_kwh = rate_step * dt / battery_settings.efficiency_discharge
    return max(float(end_soe_tolerance), lattice_step_kwh / 2)


def _pinned_terminal_row(
    end_soe_target: float,
    end_soe_tolerance: float,
    battery_settings: BatterySettings,
) -> tuple[np.ndarray, np.ndarray]:
    """Terminal PWL row pinning the window's end SOE to `end_soe_target`:
    exactly 0 inside `[target - tol, target + tol]`, then falling away with
    a steep constant gradient (`PWL_TERMINAL_PENALTY_PER_KWH`) on both sides.

    Deviation from the plan's starting-point code, which used a *flat*
    `-1e9` plateau everywhere outside the tolerance band. A flat plateau
    carries no gradient, so backward induction cannot tell a state that
    misses the target by 0.01 kWh from one that misses it by 4 kWh. That
    matters because the achievable end states form a discrete lattice (the
    integer-percent discharge grid of `_backward_discharge_levels`, ~0.013
    kWh apart for a 5 kW / 0.25 h battery), so landing inside a 1e-6 band
    is generically impossible: every state would collapse to the same
    `-1e9` and the window's argmax would be decided by floating-point
    noise -- exactly the tie-breaking pathology #450 is about. The V-shape
    keeps the pin dominant *and* steers trajectories toward the target.

    A kink is never collinear, so both breakpoints survive `_pwl_prune` at
    any tolerance below the penalty gradient -- verified by
    `test_pinned_terminal_penalty_survives_backward_propagation`.
    """
    min_soe = battery_settings.min_soe_kwh
    max_soe = battery_settings.max_soe_kwh
    target = float(end_soe_target)
    if not min_soe <= target <= max_soe:
        # Clipping instead would hand back a legitimate-looking, zero-penalty
        # pin at the WRONG SOE, so `V[0]` would read as perfectly feasible and
        # the window would be spliced against a reconnection point that never
        # existed. A target outside the battery's own range can only come from
        # an upstream bug, so fail loudly.
        raise ValueError(
            f"end_soe_target {target} kWh is outside the battery's usable "
            f"range [{min_soe}, {max_soe}] kWh"
        )
    tol = max(float(end_soe_tolerance), 0.0)
    lo = max(min_soe, target - tol)
    hi = min(max_soe, target + tol)

    xs = np.array([min_soe, lo, hi, max_soe])
    vs = np.array(
        [
            -PWL_TERMINAL_PENALTY_PER_KWH * (lo - min_soe),
            0.0,
            0.0,
            -PWL_TERMINAL_PENALTY_PER_KWH * (max_soe - hi),
        ]
    )
    keep = np.concatenate(([True], np.diff(xs) > 1e-12))
    return xs[keep], vs[keep]


def _pwl_window_seed_points(
    t: int,
    xs_next: np.ndarray,
    battery_settings: BatterySettings,
    dt: float,
    home_consumption: list[float],
    solar_production: list[float],
    discharge_resolution_kw: float | None,
) -> np.ndarray:
    """Initial breakpoint candidates for V[t]: V[t+1]'s breakpoints and their
    one-step preimages under the translation-like actions (STORE, IDLE with
    passive solar), the known transition kinks, the discharge feasibility
    onsets, and a coarse safety-net grid.

    Deviation from the plan's starting-point code, which seeded a fixed
    21-point `linspace`. With the terminal pin's ~1e6 SEK/kWh gradient, a
    0.45 kWh seed spacing would misplace the boundary of the target's
    reachable set by up to half a spacing, i.e. ~2e5 SEK of fictitious
    value -- enough to invert the window's decision. Seeding the exact
    preimages puts a breakpoint *on* each kink instead, and the adaptive
    probe loop in `run_pwl_window_backward_induction` finds the rest.
    """
    min_soe = battery_settings.min_soe_kwh
    max_soe = battery_settings.max_soe_kwh
    surplus = max(0.0, solar_production[t] - home_consumption[t])
    rate_throughput = battery_settings.max_charge_power_kw * dt
    store_gain = rate_throughput * battery_settings.efficiency_charge
    idle_gain = min(surplus, rate_throughput) * battery_settings.efficiency_charge

    points = [xs_next, xs_next - store_gain, np.array([min_soe, max_soe])]
    if idle_gain > 0:
        points.append(xs_next - idle_gain)
    points.append(
        np.array(
            [
                max_soe - store_gain,
                max_soe - surplus * battery_settings.efficiency_charge,
                max_soe - idle_gain,
                max_soe
                - POWER_CLASSIFICATION_THRESHOLD_KW
                * dt
                * battery_settings.efficiency_charge,
            ]
        )
    )
    discharge_energy = (
        _backward_discharge_levels(battery_settings, discharge_resolution_kw)
        * dt
        / battery_settings.efficiency_discharge
    )
    points.append(min_soe + discharge_energy)
    # Discharge preimages: discharge maps x -> x - e, so V[t+1]'s kink at b
    # is a kink of V[t] at b + e for every discharge level e. The reference
    # prototype left these to adaptive probing, which is fine for a smooth
    # terminal reward but far too slow to localise a ~1e6 SEK/kWh pin.
    # Seeding them exactly is not just more accurate but *faster* end to end,
    # because it removes refinement rounds (measured over 12 randomised
    # 5-period windows: 1.00 s -> 0.68 s mean once the budget stopped
    # cutting it off after the first backward step).
    preimage_points = xs_next.size * discharge_energy.size
    if preimage_points > PWL_MAX_PREIMAGE_SEED_POINTS:
        raise PWLWindowUnderRefinedError(
            f"PWL window t={t}: exact discharge-preimage seeding would need "
            f"{preimage_points} points > PWL_MAX_PREIMAGE_SEED_POINTS="
            f"{PWL_MAX_PREIMAGE_SEED_POINTS}. Falling back to adaptive probing "
            f"alone may misplace the terminal pin's reachable-set boundary, so "
            f"V[{t}] cannot be certified exact and must not be spliced."
        )
    points.append(np.add.outer(xs_next, discharge_energy).ravel())
    points.append(np.arange(min_soe, max_soe + 0.1, 0.1))

    X = np.unique(np.clip(np.concatenate(points), min_soe, max_soe))
    keep = np.concatenate(([True], np.diff(X) > _PWL_MERGE_EPS_KWH))
    return X[keep]


def run_pwl_window_backward_induction(
    window_horizon: int,
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    solar_production: list[float],
    battery_settings: BatterySettings,
    dt: float,
    end_soe_target: float,
    end_soe_tolerance: float = 1e-6,
    max_charge_power_per_period: list[float] | None = None,
    self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
    discharge_resolution_kw: float | None = None,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Exact PWL backward induction over a short sub-horizon window whose end
    SOE is pinned to `end_soe_target` (see `_pinned_terminal_row`).

    Returns `window_horizon + 1` PWL rows `(xs, vs)`; `V[window_horizon]` is
    the pinned terminal row. Task 6's resolver forward-replays this table
    from the window's known start SOE, so the window reconnects to the
    untouched grid-DP schedule on both sides.

    Each row is built by evaluating the Bellman objective on a seeded
    breakpoint set, adaptively probing every interval for hidden kinks
    (bisection plus a golden-section probe, so a kink at the midpoint can't
    hide), and finally pruning collinear points. `_pwl_prune`'s tolerance
    stays at the economics-scale `PWL_EPS_PRUNE`: against the pin's ~1e6
    SEK/kWh gradient it is effectively a no-op near the target, which is
    precisely the behaviour needed -- the penalty spike is preserved, only
    genuinely flat economic regions get collapsed.

    `end_soe_tolerance` is floored at half the discharge action lattice --
    see `_end_soe_pin_tolerance`.

    Infeasible targets are not an error: if the window physically cannot
    reach `end_soe_target` from the caller's start SOE (rate limits, the
    inverter AC cap, solar), backward induction still returns a usable
    table, but `V[0]` at that start SOE carries the terminal penalty
    (`-PWL_TERMINAL_PENALTY_PER_KWH * shortfall`) instead of an
    economics-scale value. Callers must gate on
    `pwl_window_is_feasible(V, start_soe)` before splicing -- do not
    re-derive that threshold at the call site.

    An `end_soe_target` outside the battery's usable SOE range raises
    `ValueError` (see `_pinned_terminal_row`).

    Exhausting any of the accuracy budgets (`PWL_MAX_BREAKPOINTS`,
    `PWL_MAX_REFINE_ITERS`, `PWL_MAX_PREIMAGE_SEED_POINTS`) raises
    `PWLWindowUnderRefinedError` rather than returning the approximation --
    unlike infeasibility, an uncertifiable table has no honest use, and
    splicing one in as if exact is the silent degradation this whole path
    exists to remove.
    """
    horizon_inputs = (buy_price, sell_price, home_consumption, solar_production)
    power_row = np.concatenate(
        (
            [0.0],
            _backward_discharge_levels(battery_settings, discharge_resolution_kw) * -1,
            # Single representative STORE candidate: charge physics are
            # binary (see `_charge_candidate`), and POWER_STEP_KW is the
            # exact value replay's `_charge_candidate` returns.
            [POWER_STEP_KW],
        )
    )

    V: list[tuple[np.ndarray, np.ndarray]] = [None] * (window_horizon + 1)  # type: ignore[list-item]
    V[window_horizon] = _pinned_terminal_row(
        end_soe_target,
        _end_soe_pin_tolerance(
            end_soe_tolerance, battery_settings, dt, discharge_resolution_kw
        ),
        battery_settings,
    )

    for t in range(window_horizon - 1, -1, -1):
        xs_next, _vs_next = V[t + 1]
        period_max_charge = (
            max_charge_power_per_period[t]
            if max_charge_power_per_period is not None
            else None
        )

        def values_at(X: np.ndarray, _t: int = t, _pmc=period_max_charge) -> np.ndarray:
            return _pwl_candidate_values_at(
                X,
                _t,
                V[_t + 1],
                power_row,
                horizon_inputs,
                battery_settings,
                dt,
                _pmc,
                self_throttle_export_threshold_kwh,
            )

        X = _pwl_window_seed_points(
            t,
            xs_next,
            battery_settings,
            dt,
            home_consumption,
            solar_production,
            discharge_resolution_kw,
        )
        V_t = values_at(X)
        converged = False
        for _ in range(PWL_MAX_REFINE_ITERS):
            widths = np.diff(X)
            wide = widths > _PWL_MIN_PROBE_WIDTH_KWH
            if not wide.any():
                converged = True
                break
            left = X[:-1][wide]
            width = widths[wide]
            probes = np.concatenate((left + 0.5 * width, left + 0.381966 * width))
            probe_values = values_at(probes)
            linear = np.interp(probes, X, V_t)
            # Absolute accuracy where the economics live, relative accuracy
            # where the terminal pin dominates: `PWL_EPS_REFINE` SEK is a
            # meaningless accuracy target at |V| ~ 1e5, because a state that
            # far outside the pin is never chosen at any of those digits.
            # (Measured: this changed no replayed decision and no runtime
            # either -- it is kept because chasing absolute 1e-6 SEK in the
            # penalty region is not a claim this code can honestly make, not
            # because it bought a speedup.)
            tolerance = PWL_EPS_REFINE * (1.0 + np.abs(linear))
            bad = np.abs(probe_values - linear) > tolerance
            if not bad.any():
                converged = True
                break
            X = np.sort(np.concatenate((X, probes[bad])))
            X = X[np.concatenate(([True], np.diff(X) > _PWL_MERGE_EPS_KWH))]
            # Prune inside the loop, not just at the end: every probe round
            # costs O(|X| x |actions|), so letting X accumulate tens of
            # thousands of provably-redundant points makes the row an order
            # of magnitude more expensive to build. Pruning cannot ping-pong
            # with refinement because a point is only dropped when its error
            # is <= PWL_EPS_PRUNE, while re-adding it requires an error
            # above PWL_EPS_REFINE * (1 + |V|) >= PWL_EPS_PRUNE.
            X, V_t = _pwl_prune(X, values_at(X), eps=PWL_EPS_PRUNE)
            if len(X) > PWL_MAX_BREAKPOINTS:
                raise PWLWindowUnderRefinedError(
                    f"PWL window t={t}: breakpoint ceiling hit ({len(X)} > "
                    f"PWL_MAX_BREAKPOINTS={PWL_MAX_BREAKPOINTS}); V[{t}] is an "
                    f"under-refined approximation and the window's result must "
                    f"not be treated as exact."
                )
        if not converged:
            raise PWLWindowUnderRefinedError(
                f"PWL window t={t}: refinement did not converge within "
                f"PWL_MAX_REFINE_ITERS={PWL_MAX_REFINE_ITERS} ({len(X)} "
                f"breakpoints); V[{t}] may still carry representation error "
                f"above PWL_EPS_REFINE and must not be treated as exact."
            )

        V[t] = _pwl_prune(X, V_t, eps=PWL_EPS_PRUNE)

    return V


def pwl_window_is_feasible(
    V: list[tuple[np.ndarray, np.ndarray]], start_soe: float
) -> bool:
    """Whether a window solved by `run_pwl_window_backward_induction` can
    actually reach its pinned end SOE from `start_soe`.

    Callers must check this before splicing a resolved window back into the
    grid DP's schedule. A window can be infeasible for ordinary physical
    reasons -- charge/discharge rate limits, the inverter AC cap, solar
    forcing SOE up -- and in that case backward induction still returns a
    perfectly well-formed table; it just describes the best trajectory that
    *misses* the reconnection point. Splicing that in would corrupt every
    period after the window.

    Mechanics: `V[0]` at `start_soe` is `economics - PWL_TERMINAL_PENALTY_PER_KWH
    x shortfall`, where `shortfall` is how far outside the pin band the best
    reachable end SOE lands. Window economics are at most a few hundred SEK,
    so a value at or below `PWL_WINDOW_INFEASIBLE_SEK` (-1e4 SEK, i.e. a
    `PWL_WINDOW_MAX_PIN_SHORTFALL_KWH` = 0.01 kWh shortfall) cannot be
    economics and must be penalty.

    The boundary is a continuum, not a cliff -- a shortfall just under
    `PWL_WINDOW_MAX_PIN_SHORTFALL_KWH` returns True with several thousand SEK
    of penalty still in `V[0]`, so that number is *not* a usable estimate of
    the window's economics. That is deliberate and safe: the threshold sits
    an order of magnitude below `SOE_STEP_KWH`, the grid DP's own state
    resolution, so any miss this predicate accepts is smaller than the
    reconnection point's own quantisation. Use it as a splice/don't-splice
    gate only; take the window's economics from the replayed rewards.
    """
    return bool(
        _pwl_eval_array(V[0], np.array([start_soe]))[0] > PWL_WINDOW_INFEASIBLE_SEK
    )


def resolve_pwl_window(
    V: list[tuple[np.ndarray, np.ndarray]],
    start_soe: float,
    window_horizon: int,
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    solar_production: list[float],
    battery_settings: BatterySettings,
    dt: float,
    cost_basis: float,
    max_charge_power_per_period: list[float] | None = None,
    self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
    discharge_resolution_kw: float | None = None,
) -> list[tuple[float, float]]:
    """Forward-replay the window's resolved value table `V` (from
    `run_pwl_window_backward_induction`) into a concrete action sequence,
    greedily applying `_pwl_best_action_at_continuous_state` at each period
    from the true continuous `start_soe` -- the mirror image of
    `dp_battery_algorithm.py`'s grid-DP forward replay, but reading `V` as
    PWL rows instead of a grid array.

    Raises `RuntimeError` if `start_soe` cannot actually reach the window's
    pinned end SOE (per `pwl_window_is_feasible`): replaying through V[0]'s
    terminal-penalty region would silently produce actions that look
    plausible but never reconnect to the pinned target, which is exactly the
    failure Task 5's feasibility predicate exists to catch before it reaches
    the splice.

    Returns `[(power, next_soe), ...]` for each of the window's periods.
    """
    if not pwl_window_is_feasible(V, start_soe):
        raise RuntimeError(
            f"PWL window is infeasible from start_soe={start_soe} kWh: the "
            "pinned end SOE cannot be reached (V[0] carries the terminal "
            "penalty -- see pwl_window_is_feasible). Refusing to forward-"
            "replay a trajectory that would not actually reconnect to the "
            "pinned target."
        )

    soe = start_soe
    basis = cost_basis
    actions: list[tuple[float, float]] = []
    for t in range(window_horizon):
        action, next_soe, basis, _reward = _pwl_best_action_at_continuous_state(
            soe=soe,
            t=t,
            V_next=V[t + 1],
            power_levels=np.array([]),
            home_consumption=home_consumption,
            battery_settings=battery_settings,
            dt=dt,
            solar_production=solar_production,
            buy_price=buy_price,
            sell_price=sell_price,
            cost_basis=basis,
            max_charge_power_per_period=max_charge_power_per_period,
            discharge_resolution_kw=discharge_resolution_kw,
            self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        )
        actions.append((action, next_soe))
        soe = next_soe
    return actions
