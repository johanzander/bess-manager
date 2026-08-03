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
reusable function plus a terminal-value term and negative-sell-price
handling. It is NOT yet feature complete -- see the spec's "Key design
decisions for the build phase" for what's still missing: two-stage
integer-rate re-integerization (this slice solves continuous discharge
rates only), LP-dual shadow prices, below-floor tolerance (#233), AC-cap
clipping under negative prices, and per-period charge caps.

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
from scipy.optimize import Bounds, LinearConstraint, milp

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


def solve_milp_schedule(
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    solar_production: list[float],
    battery: dict,
    dt: float,
    terminal_value_per_kwh: float = 0.0,
    integer_rates: bool = False,
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
    every mode/active binary to its solved value and re-solves the much
    smaller remaining MIP (only discharge_pct integer) to the
    hardware-executable optimum, per the pivot spec's two-stage design
    (re-solving with binaries fixed rather than round-and-repair, since
    the small fixed-mode MIP is cheap and exact).
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
    rate_throughput_kwh = battery["max_charge_power_kw"] * dt
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
    if not (solar <= ac_cap_kwh).all():
        raise NotImplementedError(
            "solve_milp_schedule assumes solar production never exceeds "
            "the AC cap (slice 1 scope) -- AC-clip handling is a deferred "
            "build-phase item, see the pivot spec point 4"
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
    mode_store = var("mode_store", horizon)
    mode_idle = var("mode_idle", horizon)
    mode_bypass = var("mode_bypass", horizon)
    mode_discharge = var("mode_discharge", horizon)
    store_active = var("store_active", horizon)
    s2b_active = var("s2b_active", horizon)
    idle_active = var("idle_active", horizon)
    throttled = var("throttled", horizon)
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
    )
    for g in binary_groups:
        integrality[g] = 1

    lb = np.zeros(n_vars)
    ub = np.full(n_vars, np.inf)
    lb[e] = e_min
    ub[e] = e_max
    lb[e[0]] = ub[e[0]] = e0
    ub[store_kwh] = rate_throughput_kwh * eta_c
    ub[solar_to_battery_kwh] = np.maximum(surplus, 0)
    ub[idle_kwh] = np.maximum(idle_charge_kwh, 0)
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

    def con(coeffs: list[tuple[int, float]], lo: float, hi: float) -> None:
        r = len(rlb)
        for c_i, v in coeffs:
            rows.append(r)
            cols.append(c_i)
            vals.append(v)
        rlb.append(lo)
        rub.append(hi)

    capacity_span = e_max - e_min
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

        # STORE: store_kwh = min(rate_throughput*eta_c, e_max - e[t]) if active.
        store_rate_m = rate_throughput_kwh * eta_c
        con([(store_kwh[t], 1), (mode_store[t], -store_rate_m)], -np.inf, 0)
        con([(store_kwh[t], 1), (e[t], 1)], -np.inf, e_max)
        con(
            [
                (store_kwh[t], 1),
                (store_active[t], store_rate_m),
                (mode_store[t], -store_rate_m),
            ],
            0.0,
            np.inf,
        )
        con(
            [
                (store_kwh[t], 1),
                (e[t], 1),
                (store_active[t], -capacity_span),
                (mode_store[t], -capacity_span),
            ],
            e_max - 2 * capacity_span,
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
        rate_m = rate_throughput_kwh
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
                (idle_active[t], -capacity_span),
                (mode_idle[t], -capacity_span),
            ],
            e_max - 2 * capacity_span,
            np.inf,
        )

        # DISCHARGE: percent rate active only in DISCHARGE mode, AC-capped.
        con([(discharge_pct[t], 1), (mode_discharge[t], -100)], -np.inf, 0)
        con(
            [(discharge_pct[t], 1), (mode_discharge[t], -_MIN_DISCHARGE_PCT)],
            0,
            np.inf,
        )
        con(
            [(discharge_pct[t], discharge_step_kwh / eta_d), (e[t], -1)],
            -np.inf,
            -e_min,
        )
        con(
            [(discharge_pct[t], discharge_step_kwh)],
            -np.inf,
            ac_headroom_kwh[t],
        )

        # AC balance identity.
        con(
            [
                (exp[t], 1),
                (imp[t], -1),
                (solar_to_battery_kwh[t], 1),
                (idle_kwh[t], 1 / eta_c),
                (discharge_pct[t], -discharge_step_kwh),
            ],
            solar[t] - cons[t],
            solar[t] - cons[t],
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
        for g in binary_groups:
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

    return MilpScheduleResult(
        status="optimal",
        cost=float(result.fun) + terminal_value_per_kwh * e_min,
        soe=result.x[e],
        imp=result.x[imp],
        exp=result.x[exp],
        credited_exp=result.x[credited_exp],
        discharge_pct=result.x[discharge_pct],
    )
