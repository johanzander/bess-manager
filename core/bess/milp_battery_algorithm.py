"""MILP battery schedule optimizer (#450 pivot, build-phase slice 1).

Replaces the DP's uniform-grid backward induction with a mixed-integer
linear program over hardware modes (STORE / IDLE / BYPASS / DISCHARGE),
solved to global optimality by HiGHS via `scipy.optimize.milp`. See
docs/superpowers/specs/2026-08-03-milp-optimizer-pivot-450.md for why: the
DP's SOE-grid snap noise mis-picks between financially near-tied windows
(#450), and the exact-PWL alternative on this branch
(dp_battery_algorithm.py) is correct but too slow (3.2s/78p, 37s/192p).

This module is the feasibility spike
(docs/superpowers/specs/2026-08-03-milp-spike-450.py) generalized into a
reusable function covering the pivot spec's full "Key design decisions
for the build phase" semantics list. Remaining build items (highspy
dependency swap, production wiring into dp_schedule.py/
battery_system_manager.py) are integration/packaging, not new model
semantics.

Negative sell prices (spec point 3): the spike assumed buy > sell > 0 and
relied on that spread alone to keep import/export exclusive, which is
still required here (see the NotImplementedError below) -- but the actual
bug the spec flagged was different: the self-throttle export-credit
mechanism (#240) let the solver zero out `credited_exp` for *any* export
outside DISCHARGE mode when sell < 0, dodging a cost it cannot physically
avoid (forced solar-surplus export has no curtailment option in this
system). Fixed by pinning credited_exp == exp whenever mode_discharge is
not active; self-throttle's below-threshold zero-credit stays
DISCHARGE-mode-only, per its actual hardware semantics.
"""

from dataclasses import dataclass

import numpy as np
from scipy import sparse
from scipy.optimize import Bounds, LinearConstraint, linprog, milp

from core.bess.dp_constants import SOE_STEP_KWH

# Self-throttle (#240): export below this threshold in DISCHARGE mode is not
# credited -- see BATTERY_EXPORT_THRESHOLD_KWH in dp_battery_algorithm.py.
SELF_THROTTLE_EXPORT_THRESHOLD_KWH = 0.01

# Big-M values: loose but finite bounds on the physical quantities they
# gate, not arbitrary large numbers -- kept close to the true bound so the
# LP relaxation stays tight.
_EXPORT_BIG_M_KWH = 6.0

# Minimum nonzero discharge percent when DISCHARGE mode is active -- matches
# POWER_CLASSIFICATION_THRESHOLD_KW's role in dp_constants.py: without a
# floor, DISCHARGE mode with an arbitrarily small rate is a degenerate
# near-BYPASS state that isn't a real hardware-executable action.
_MIN_DISCHARGE_PCT = 2


@dataclass
class MilpScheduleResult:
    status: str
    cost: float
    soe: np.ndarray  # length horizon + 1, SOE at each period boundary
    imp: np.ndarray = None  # length horizon, AC import (kWh)
    exp: np.ndarray = None  # length horizon, AC export (kWh, raw)
    credited_exp: np.ndarray = None  # length horizon, export actually priced
    discharge_pct: np.ndarray = None  # length horizon, discharge rate (%)
    shadow_price: float | None = None  # marginal value of the current SOE
    shadow_prices: np.ndarray = None  # length horizon, per-period LP-dual shadow price


def _to_linprog_format(a_matrix, rlb, rub):
    """Convert the unified two-sided (A, rlb, rub) row format `milp()`
    accepts into `linprog`'s split A_eq/b_eq/A_ub/b_ub format (linprog has
    no equivalent of `LinearConstraint`). Returns `eq_position`, a dict
    mapping each ORIGINAL row index that turned out to be an equality
    (rlb[i] == rub[i]) to its position in `b_eq` -- the only way to later
    look up `linprog`'s `.eqlin.marginals[eq_position[original_row]]` for
    a specific constraint of interest (e.g. one period's SOE recursion).
    """
    csr = a_matrix.tocsr()
    a_eq_rows, b_eq = [], []
    a_ub_rows, b_ub = [], []
    eq_position: dict[int, int] = {}
    for i in range(len(rlb)):
        lo, hi = rlb[i], rub[i]
        row = csr.getrow(i)
        if lo == hi:
            eq_position[i] = len(b_eq)
            a_eq_rows.append(row)
            b_eq.append(lo)
        else:
            if hi < np.inf:
                a_ub_rows.append(row)
                b_ub.append(hi)
            if lo > -np.inf:
                a_ub_rows.append(-row)
                b_ub.append(-lo)
    a_eq = sparse.vstack(a_eq_rows) if a_eq_rows else None
    a_ub = sparse.vstack(a_ub_rows) if a_ub_rows else None
    return a_eq, np.array(b_eq), a_ub, np.array(b_ub), eq_position


def solve_milp_schedule(
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    solar_production: list[float],
    battery: dict,
    dt: float,
    terminal_value_per_kwh: float = 0.0,
    integer_rates: bool = False,
    compute_shadow_price: bool = False,
    compute_shadow_price_array: bool = False,
    max_charge_power_per_period: list[float] | None = None,
) -> MilpScheduleResult:
    """Solve the #450 MILP core model to global optimality.

    `battery` carries the same fields as the fixture's `battery` block:
    initial_soe, min_soe_kwh, max_soe_kwh, efficiency_charge,
    efficiency_discharge, cycle_cost_per_kwh, max_charge_power_kw,
    max_discharge_power_kw, inverter_max_ac_power_kw,
    inverter_ac_power_margin.

    `integer_rates`: hardware discharge rate is a percent register (#282),
    not a continuous kW value -- continuous rates aren't executable as-is.
    When True, this solves the fast continuous relaxation first, then fixes
    only the four hardware-mode binaries (mode_store/idle/bypass/discharge)
    to their solved values and re-solves the remaining MIP (auxiliary
    branch-select binaries + discharge_pct, now integer) to the
    hardware-executable optimum, per the pivot spec's two-stage design.
    Fixing the auxiliary piecewise-linear branch-select binaries
    (store_active/s2b_active/idle_active/throttled) too, not just the mode
    binaries, was tried first and measured to cost ~3.8 ore/day extra on
    the #450 fixture versus the true joint-integer optimum -- those
    encode "which branch of a min()" given the mode, and must stay free to
    re-adapt once rates are forced onto the integer lattice, or stage 2
    silently ships a suboptimal schedule. Verified: mode-only fixing
    reproduces the joint-integer solve's cost to ~1e-9 on 78 periods
    (0.78s) and near-matches a 120s-time-limited (non-optimal) joint solve
    on 192 periods (2.0s) -- joint solving alone isn't tractable at that
    horizon (hit the 120s limit without proving optimality), so two-stage
    is load-bearing at production horizons, not just an optimization.

    `compute_shadow_price`: requires integer_rates=True. Marginal value of
    the CURRENT period's SOE only (not the full per-period array the DP
    produces -- see dp_battery_algorithm.py's `period_data.decision.
    shadow_price`, computed per period from the DP's value-to-go function
    V[t]). Computed as a direct backward finite difference matching that
    definition exactly -- deliberately NOT an LP dual, even though the
    pivot spec's point 2 suggests LP duals (binaries fixed, one linprog
    solve) as a cheaper implementation: getting the dual's sign/
    formulation subtly wrong in a financial decision path is a worse risk
    than the extra ~2 re-solves this costs. Snaps initial_soe to the same
    SOE_STEP_KWH-aligned anchor the DP uses before differencing (`anchor
    = min_soe_kwh + SOE_STEP_KWH * round((initial_soe - min_soe_kwh) /
    SOE_STEP_KWH)`), and returns None (no shadow price) when the anchor is
    below `min_soe_kwh + SOE_STEP_KWH / 2`, matching the DP's own guard
    (a backward difference below the grid's first point is undefined).

    `compute_shadow_price_array`: requires integer_rates=True. The FULL
    per-period array (unlike `compute_shadow_price` above), needed for
    production wiring -- battery_system_manager.py's intra-period
    discharge gate reads `shadow_price` for every period in the stored
    schedule, not just the current one. A per-period finite-difference
    (horizon-many re-solves) is not viable in production, so this uses
    the LP-dual approach `compute_shadow_price` deliberately avoided: one
    additional `linprog` solve with every binary fixed to the integer
    solution's values (the "which branch of a min()" choices, not just
    hardware mode), leaving continuous rates free, then reading the dual
    of each period's SOE-recursion constraint -- period t's shadow price
    is the (negated) dual of the recursion row linking e[t-1] to e[t] (or,
    for period 0, of an explicit `e[0] = initial_soe` equality row added
    for this solve only, replacing the bound pin so its dual is
    accessible the same way). Negated because `linprog`'s dual convention
    is d(cost)/d(b_eq), and injecting energy should decrease cost, not
    increase it -- verified empirically before trusting the sign (see the
    module's tests), not assumed from a derivation alone.

    `max_charge_power_per_period`: per-period charge power cap (kW),
    typically from temperature derating. When provided, the STORE/IDLE
    charge rate for period t is capped at
    `min(battery["max_charge_power_kw"], max_charge_power_per_period[t])`
    instead of the flat battery-wide rate -- matches
    dp_battery_algorithm.py's own per-period clamp.
    """
    buy = np.asarray(buy_price, dtype=float)
    sell = np.asarray(sell_price, dtype=float)
    cons = np.asarray(home_consumption, dtype=float)
    solar = np.asarray(solar_production, dtype=float)
    horizon = len(buy)

    e0 = battery["initial_soe"]
    e_min = battery["min_soe_kwh"]
    e_max = battery["max_soe_kwh"]
    eta_c = battery["efficiency_charge"]
    eta_d = battery["efficiency_discharge"]
    wear = battery["cycle_cost_per_kwh"]
    if max_charge_power_per_period is not None:
        charge_power_kw = np.minimum(
            battery["max_charge_power_kw"],
            np.asarray(max_charge_power_per_period, dtype=float),
        )
    else:
        charge_power_kw = np.full(horizon, battery["max_charge_power_kw"])
    rate_throughput_kwh = charge_power_kw * dt  # per-period array
    discharge_step_kwh = battery["max_discharge_power_kw"] / 100 * dt
    ac_cap_kwh = (
        battery["inverter_max_ac_power_kw"]
        * (1 - battery["inverter_ac_power_margin"])
        * dt
    )

    if not (buy > sell).all():
        raise NotImplementedError(
            "solve_milp_schedule requires buy > sell in every period -- "
            "without that spread, the import/export split has no unique "
            "LP optimum (unbounded degeneracy), which is out of scope"
        )
    surplus = np.maximum(0.0, solar - cons)
    idle_charge_kwh = np.minimum(surplus, rate_throughput_kwh) * eta_c
    ac_headroom_kwh = np.maximum(0.0, ac_cap_kwh - np.minimum(solar, ac_cap_kwh))

    names: list[str] = []

    def var(name: str, n: int = 1) -> np.ndarray:
        i = len(names)
        names.extend(f"{name}[{j}]" for j in range(n))
        return np.arange(i, i + n)

    e = var("e", horizon + 1)
    store_kwh = var("store_kwh", horizon)
    solar_to_battery_kwh = var("solar_to_battery_kwh", horizon)
    idle_kwh = var("idle_kwh", horizon)
    discharge_pct = var("discharge_pct", horizon)
    imp = var("imp", horizon)
    exp = var("exp", horizon)
    credited_exp = var("credited_exp", horizon)
    ac_solar = var("ac_solar", horizon)
    mode_store = var("mode_store", horizon)
    mode_idle = var("mode_idle", horizon)
    mode_bypass = var("mode_bypass", horizon)
    mode_discharge = var("mode_discharge", horizon)
    store_active = var("store_active", horizon)
    s2b_active = var("s2b_active", horizon)
    idle_active = var("idle_active", horizon)
    throttled = var("throttled", horizon)
    ac_cap_active = var("ac_cap_active", horizon)
    n_vars = len(names)

    integrality = np.zeros(n_vars)
    binary_groups = (
        mode_store,
        mode_idle,
        mode_bypass,
        mode_discharge,
        store_active,
        s2b_active,
        idle_active,
        throttled,
        ac_cap_active,
    )
    for g in binary_groups:
        integrality[g] = 1

    lb = np.zeros(n_vars)
    ub = np.full(n_vars, np.inf)
    ub[e] = e_max
    # Below-floor tolerance (#233): if initial_soe starts below min_soe_kwh
    # (common after a restart or deep discharge), don't fabricate a jump
    # to the floor -- only require reaching it as fast as physically
    # reachable. store_rate_m (per-period, since max_charge_power_per_period
    # can vary the rate by period) is STORE mode's per-period charge cap
    # and an upper bound on ANY mode's charge rate (IDLE can only charge
    # from solar, which is <= the same cap), so e0 + cumsum(store_rate_m)
    # up to period t is a safe (non-tight, always-valid) bound on how much
    # SOE could possibly have risen by period t regardless of price. When
    # initial_soe >= min_soe_kwh this reduces to the flat e_min floor
    # unconditionally (reachable_from_start >= e0 >= e_min already), so
    # there's no behavior change for the normal case.
    store_rate_m = rate_throughput_kwh * eta_c
    reachable_from_start = e0 + np.cumsum(store_rate_m)
    soe_floor = np.minimum(e_min, reachable_from_start)
    lb[e[1:]] = soe_floor
    lb[e[0]] = ub[e[0]] = e0
    ub[store_kwh] = rate_throughput_kwh * eta_c
    ub[solar_to_battery_kwh] = np.maximum(surplus, 0)
    ub[idle_kwh] = np.maximum(idle_charge_kwh, 0)
    ub[ac_solar] = ac_cap_kwh
    ub[discharge_pct] = 100
    ub[exp] = _EXPORT_BIG_M_KWH
    ub[imp] = 50
    ub[credited_exp] = _EXPORT_BIG_M_KWH
    for g in binary_groups:
        ub[g] = 1

    rows: list[int] = []
    cols: list[int] = []
    vals: list[float] = []
    rlb: list[float] = []
    rub: list[float] = []

    def con(coeffs: list[tuple[int, float]], lo: float, hi: float) -> int:
        r = len(rlb)
        for c_i, v in coeffs:
            rows.append(r)
            cols.append(c_i)
            vals.append(v)
        rlb.append(lo)
        rub.append(hi)
        return r

    # Big-M for the STORE/IDLE capacity-branch min() encoding below. Using
    # capacity_span (e_max - e_min) here implicitly assumes e[t] >= e_min
    # always -- when a below-floor start (#233 above) pushes e[t] below
    # e_min, that M is too small to make the inactive branch's slack
    # non-binding, producing a spurious infeasibility even though a
    # feasible schedule exists (found via a below-floor scenario that
    # returned status="infeasible" with no real infeasibility). Sized
    # against the true minimum reachable e[t] instead.
    soe_force_big_m = e_max - min(e0, e_min)
    soe_recursion_rows: list[int] = []
    for t in range(horizon):
        con(
            [
                (mode_store[t], 1),
                (mode_idle[t], 1),
                (mode_bypass[t], 1),
                (mode_discharge[t], 1),
            ],
            1,
            1,
        )

        # SOE recursion.
        soe_recursion_rows.append(
            con(
                [
                    (e[t + 1], 1),
                    (e[t], -1),
                    (store_kwh[t], -1),
                    (idle_kwh[t], -1),
                    (discharge_pct[t], discharge_step_kwh / eta_d),
                ],
                0,
                0,
            )
        )

        # STORE: store_kwh = min(rate_throughput*eta_c, e_max - e[t]) if active.
        con([(store_kwh[t], 1), (mode_store[t], -store_rate_m[t])], -np.inf, 0)
        con([(store_kwh[t], 1), (e[t], 1)], -np.inf, e_max)
        con(
            [
                (store_kwh[t], 1),
                (store_active[t], store_rate_m[t]),
                (mode_store[t], -store_rate_m[t]),
            ],
            0.0,
            np.inf,
        )
        con(
            [
                (store_kwh[t], 1),
                (e[t], 1),
                (store_active[t], -soe_force_big_m),
                (mode_store[t], -soe_force_big_m),
            ],
            e_max - 2 * soe_force_big_m,
            np.inf,
        )

        # STORE: solar_to_battery = min(surplus, store_kwh/eta_c) if active.
        surplus_m = max(surplus[t], 1e-9)
        con([(solar_to_battery_kwh[t], 1), (mode_store[t], -surplus_m)], -np.inf, 0)
        con(
            [(solar_to_battery_kwh[t], 1), (store_kwh[t], -1 / eta_c)],
            -np.inf,
            0,
        )
        con(
            [
                (solar_to_battery_kwh[t], 1),
                (s2b_active[t], surplus_m),
                (mode_store[t], -surplus_m),
            ],
            surplus[t] - surplus_m,
            np.inf,
        )
        rate_m = rate_throughput_kwh[t]
        con(
            [
                (solar_to_battery_kwh[t], 1),
                (store_kwh[t], -1 / eta_c),
                (s2b_active[t], -rate_m),
                (mode_store[t], -rate_m),
            ],
            -2 * rate_m,
            np.inf,
        )

        # IDLE: idle_kwh = min(idle_charge, e_max - e[t]) if active.
        idle_m = max(idle_charge_kwh[t], 1e-9)
        con([(idle_kwh[t], 1), (mode_idle[t], -idle_m)], -np.inf, 0)
        con([(idle_kwh[t], 1), (e[t], 1)], -np.inf, e_max)
        con(
            [
                (idle_kwh[t], 1),
                (idle_active[t], idle_m),
                (mode_idle[t], -idle_m),
            ],
            idle_charge_kwh[t] - idle_m,
            np.inf,
        )
        con(
            [
                (idle_kwh[t], 1),
                (e[t], 1),
                (idle_active[t], -soe_force_big_m),
                (mode_idle[t], -soe_force_big_m),
            ],
            e_max - 2 * soe_force_big_m,
            np.inf,
        )

        # DISCHARGE: percent rate active only in DISCHARGE mode, AC-capped.
        con([(discharge_pct[t], 1), (mode_discharge[t], -100)], -np.inf, 0)
        con(
            [(discharge_pct[t], 1), (mode_discharge[t], -_MIN_DISCHARGE_PCT)],
            0,
            np.inf,
        )
        # e[t] >= min_soe_kwh + discharge_amount when discharging, gated by
        # mode_discharge -- ungated (as inherited from the spike, which
        # never exercised a below-floor start) this silently re-imposes
        # the hard e_min floor on every period regardless of mode,
        # conflicting with the below-floor relaxation above whenever
        # discharge_pct is legitimately 0.
        con(
            [
                (discharge_pct[t], discharge_step_kwh / eta_d),
                (e[t], -1),
                (mode_discharge[t], e_max),
            ],
            -np.inf,
            e_max - e_min,
        )
        con(
            [(discharge_pct[t], discharge_step_kwh)],
            -np.inf,
            ac_headroom_kwh[t],
        )

        # AC-cap clipping: solar not routed DC-side to the battery
        # (residual_solar = solar - solar_to_battery - idle_kwh/eta_c)
        # must pass through the inverter's AC stage; anything above the
        # AC cap is clipped -- lost, zero credit, not exportable and not
        # curtailable by choice (matches dp_battery_algorithm.py's
        # _ac_flows). ac_solar = min(residual_solar, ac_cap_kwh) is forced
        # to equality (not just bounded above) because the solver would
        # otherwise "curtail" ac_solar for free whenever sell < 0 to dodge
        # export cost -- the same loophole class as slice 2's negative-
        # sell fix, here for the clip rather than the self-throttle path.
        residual_m = max(solar[t], 1e-9)
        con(
            [
                (ac_solar[t], 1),
                (solar_to_battery_kwh[t], 1),
                (idle_kwh[t], 1 / eta_c),
            ],
            -np.inf,
            solar[t],
        )
        con(
            [
                (ac_solar[t], 1),
                (solar_to_battery_kwh[t], 1),
                (idle_kwh[t], 1 / eta_c),
                (ac_cap_active[t], residual_m),
            ],
            solar[t],
            np.inf,
        )
        con(
            [(ac_solar[t], 1), (ac_cap_active[t], -ac_cap_kwh)],
            0,
            np.inf,
        )

        # AC balance identity.
        con(
            [
                (exp[t], 1),
                (imp[t], -1),
                (ac_solar[t], -1),
                (discharge_pct[t], -discharge_step_kwh),
            ],
            -cons[t],
            -cons[t],
        )

        # Export credit: full, except self-throttled below threshold in
        # DISCHARGE mode (#240). Outside DISCHARGE mode, credited_exp must
        # equal exp exactly -- self-throttle is a DISCHARGE-mode-only
        # hardware quirk, and export forced by the AC balance (solar
        # surplus that can't be stored) is always a real, priced
        # transaction, even at a negative sell price. Without this floor
        # the solver can zero out credited_exp for free whenever sell < 0.
        con([(credited_exp[t], 1), (exp[t], -1)], -np.inf, 0)
        con(
            [
                (credited_exp[t], 1),
                (exp[t], -1),
                (mode_discharge[t], _EXPORT_BIG_M_KWH),
            ],
            0,
            np.inf,
        )
        con(
            [
                (credited_exp[t], 1),
                (throttled[t], -_EXPORT_BIG_M_KWH),
                (mode_discharge[t], _EXPORT_BIG_M_KWH),
            ],
            -np.inf,
            _EXPORT_BIG_M_KWH,
        )
        con(
            [
                (exp[t], 1),
                (throttled[t], -SELF_THROTTLE_EXPORT_THRESHOLD_KWH),
                (mode_discharge[t], -_EXPORT_BIG_M_KWH),
            ],
            -_EXPORT_BIG_M_KWH,
            np.inf,
        )

    c_obj = np.zeros(n_vars)
    c_obj[imp] = buy
    c_obj[store_kwh] = buy / eta_c + wear
    c_obj[solar_to_battery_kwh] = -buy
    c_obj[credited_exp] = -sell
    c_obj[idle_kwh] += wear
    c_obj[e[horizon]] -= terminal_value_per_kwh

    a_matrix = sparse.csc_matrix((vals, (rows, cols)), shape=(len(rlb), n_vars))
    result = milp(
        c=c_obj,
        constraints=LinearConstraint(a_matrix, rlb, rub),
        integrality=integrality,
        bounds=Bounds(lb, ub),
        options={"time_limit": 60, "mip_rel_gap": 1e-6},
    )

    if result.x is None:
        return MilpScheduleResult(
            status="infeasible", cost=float("nan"), soe=np.array([])
        )

    if integer_rates:
        # Stage 2: fix every mode/active binary to its stage-1 value and
        # re-solve the much smaller remaining MIP (only discharge_pct
        # integer) to the hardware-executable optimum.
        lb2 = lb.copy()
        ub2 = ub.copy()
        # Fix only the four hardware-mode binaries -- the structural
        # window/mode-sequence decision the continuous relaxation gets
        # right. Leave the auxiliary piecewise-linear branch-select
        # binaries (store_active, s2b_active, idle_active, throttled) and
        # discharge_pct free: those encode "which branch of a min()" given
        # the mode, and must be free to re-adapt once rates are forced
        # onto the integer lattice, or stage 2 loses meaningfully more
        # than integer rounding alone costs (measured ~3.8 ore/day on the
        # #450 fixture when they were fixed too).
        mode_binaries = (mode_store, mode_idle, mode_bypass, mode_discharge)
        for g in mode_binaries:
            fixed = np.round(result.x[g])
            lb2[g] = fixed
            ub2[g] = fixed
        integrality2 = integrality.copy()
        integrality2[discharge_pct] = 1

        stage2 = milp(
            c=c_obj,
            constraints=LinearConstraint(a_matrix, rlb, rub),
            integrality=integrality2,
            bounds=Bounds(lb2, ub2),
            options={"time_limit": 60, "mip_rel_gap": 1e-6},
        )
        if stage2.x is None:
            raise RuntimeError(
                "integer_rates re-integerization: stage-1 mode selection "
                "has no integer-rate solution -- round-and-repair fallback "
                "is not implemented, this needs investigating rather than "
                "silently falling back to the continuous stage-1 result"
            )
        result = stage2

    shadow_price = None
    if compute_shadow_price:
        if not integer_rates:
            raise NotImplementedError(
                "compute_shadow_price requires integer_rates=True -- "
                "shadow price is defined against the hardware-executable "
                "schedule, matching the DP's own definition"
            )
        anchor = e_min + SOE_STEP_KWH * round((e0 - e_min) / SOE_STEP_KWH)
        if anchor >= e_min + SOE_STEP_KWH / 2:
            cost_at = solve_milp_schedule(
                buy_price,
                sell_price,
                home_consumption,
                solar_production,
                {**battery, "initial_soe": anchor},
                dt,
                terminal_value_per_kwh,
                integer_rates=True,
            ).cost
            cost_below = solve_milp_schedule(
                buy_price,
                sell_price,
                home_consumption,
                solar_production,
                {**battery, "initial_soe": anchor - SOE_STEP_KWH},
                dt,
                terminal_value_per_kwh,
                integer_rates=True,
            ).cost
            shadow_price = (cost_below - cost_at) / SOE_STEP_KWH

    shadow_prices = None
    if compute_shadow_price_array:
        if not integer_rates:
            raise NotImplementedError(
                "compute_shadow_price_array requires integer_rates=True -- "
                "shadow price is defined against the hardware-executable "
                "schedule, matching the DP's own definition"
            )
        lb3 = lb.copy()
        ub3 = ub.copy()
        mode_binaries_dual = (mode_store, mode_idle, mode_bypass, mode_discharge)
        for g in mode_binaries_dual:
            fixed = np.round(result.x[g])
            lb3[g] = fixed
            ub3[g] = fixed
        # Fix each period's auxiliary branch-select binary ONLY when it's
        # actually relevant to that period's chosen mode -- an inert
        # binary (e.g. store_active when mode_store=0, where its own
        # constraints go vacuous via the mode's big-M term) still gets an
        # arbitrary tied value from the stage-2 solve; fixing it anyway
        # injects that arbitrary tie-break into the dual computation.
        # Leaving it at its natural [0,1] bound instead makes it a free,
        # economically-inert LP variable, which is what it actually is.
        # ac_cap_active is always relevant (AC clipping applies regardless
        # of mode), so it's always fixed. discharge_pct is left continuous
        # throughout -- constrained to 0 by the existing mode_discharge=0
        # constraint in every non-DISCHARGE period regardless.
        mode_store_x = np.round(result.x[mode_store]).astype(bool)
        mode_idle_x = np.round(result.x[mode_idle]).astype(bool)
        mode_discharge_x = np.round(result.x[mode_discharge]).astype(bool)
        for t in range(horizon):
            if mode_store_x[t]:
                for g in (store_active, s2b_active):
                    fixed = np.round(result.x[g[t]])
                    lb3[g[t]] = fixed
                    ub3[g[t]] = fixed
            if mode_idle_x[t]:
                fixed = np.round(result.x[idle_active[t]])
                lb3[idle_active[t]] = fixed
                ub3[idle_active[t]] = fixed
            if mode_discharge_x[t]:
                fixed = np.round(result.x[throttled[t]])
                lb3[throttled[t]] = fixed
                ub3[throttled[t]] = fixed
            fixed = np.round(result.x[ac_cap_active[t]])
            lb3[ac_cap_active[t]] = fixed
            ub3[ac_cap_active[t]] = fixed
        # Free e[0] -- pinned via an explicit equality row instead (below)
        # so its dual is reachable through .eqlin.marginals like every
        # other period, rather than needing separate bound-dual handling.
        lb3[e[0]] = 0.0
        ub3[e[0]] = e_max
        e0_row = con([(e[0], 1)], e0, e0)
        a_matrix3 = sparse.csc_matrix((vals, (rows, cols)), shape=(len(rlb), n_vars))
        a_eq, b_eq, a_ub, b_ub, eq_position = _to_linprog_format(a_matrix3, rlb, rub)
        lp = linprog(
            c=c_obj,
            A_eq=a_eq,
            b_eq=b_eq,
            A_ub=a_ub,
            b_ub=b_ub,
            bounds=list(zip(lb3, ub3, strict=True)),
            method="highs",
        )
        if lp.status != 0:
            raise RuntimeError(
                "shadow-price LP (binaries fixed) failed to solve -- "
                f"status={lp.status}: {lp.message}"
            )
        marginals = lp.eqlin.marginals
        shadow_prices = np.empty(horizon)
        shadow_prices[0] = -marginals[eq_position[e0_row]]
        for t in range(1, horizon):
            shadow_prices[t] = -marginals[eq_position[soe_recursion_rows[t - 1]]]

    return MilpScheduleResult(
        status="optimal",
        cost=float(result.fun) + terminal_value_per_kwh * e_min,
        soe=result.x[e],
        imp=result.x[imp],
        exp=result.x[exp],
        credited_exp=result.x[credited_exp],
        discharge_pct=result.x[discharge_pct],
        shadow_price=shadow_price,
        shadow_prices=shadow_prices,
    )
