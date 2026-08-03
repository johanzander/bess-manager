"""Prototype: continuous-state (exact-PWL, eps-certified) backward induction
for the BESS DP -- premise test for issue #450.

Replaces the uniform SOE grid + nearest-snap V table with an adaptive
piecewise-linear representation of V[t](soe) whose breakpoints are refined
until the representation is within EPS_REFINE of the true value function.
All rewards/transitions are evaluated through the PRODUCTION vectorized
functions (_compute_reward_grid / _state_transition_grid), so the economics
are bit-identical to the shipped DP -- only the state representation changes.

Action set (both passes, deliberately identical so Sum(rewards) must equal
V[0](s0) -- the internal exactness check):
  - IDLE            (power 0, forced passive charge)  -- production semantics
  - SOLAR_EXPORT bypass (#313, next_soe == soe)
  - STORE           (binary physics, one representative positive power;
                     feasible iff _charge_candidate would exist: room power
                     > POWER_CLASSIFICATION_THRESHOLD_KW)
  - DISCHARGE at the hardware-true integer-percent grid
                     (pct*max_discharge/100, pct=2..100 -- the same set
                     _discharge_candidates enumerates at replay)

Gates:
  1. #450 fixture: intents at periods 34-37 flip to EXPORT,STORE,STORE,STORE
  2. Dominance: prototype planned cost <= production planned cost
  3. Consistency: |Sum(replay rewards) - V0(initial_soe)| ~ 0
  4. Economic law: steady-state shadow price == sell_price (0.30)
  5. Runtime + breakpoint growth at 192 periods
"""

import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.environ["BESS_REPO"])

from core.bess.dp_battery_algorithm import (  # noqa: E402
    BATTERY_EXPORT_THRESHOLD_KWH,
    _best_action_at_continuous_state,  # only for signature reference
    _build_period_data,
    _charge_candidate,
    _compute_reward,
    _compute_reward_grid,
    _discharge_candidates,
    _effective_ac_cap_kwh,
    _state_transition,
    _state_transition_grid,
    optimize_battery_schedule,
)
from core.bess.dp_constants import POWER_CLASSIFICATION_THRESHOLD_KW  # noqa: E402
from core.bess.settings import BatterySettings  # noqa: E402

EPS_REFINE = float(os.environ.get("PWL_EPS", "1e-6"))  # SEK: max allowed gap between PWL rep and true V per period
EPS_PRUNE = float(os.environ.get("PWL_EPS", "1e-6"))  # SEK: collinearity threshold for dropping breakpoints
MAX_REFINE_ITERS = 40
MAX_POINTS = 30000


# ---------------------------------------------------------------------------
# PWL value function: (xs sorted, vs) with linear interpolation between.
# ---------------------------------------------------------------------------

def pwl_eval(xs, vs, q):
    return np.interp(q, xs, vs)


def pwl_left_slope(xs, vs, s, h=0.05):
    """Shadow price = marginal value over an ACTIONABLE energy increment.

    The exact discrete-action V is locally staircase-like at micro scales (a
    marginal 1e-6 kWh cannot be monetized by any integer-percent action), so
    the infinitesimal slope is ~0 near capacity and not the economically
    meaningful marginal value. Use the same 0.05 kWh backward difference
    production's shadow_price reporting already uses."""
    s = min(max(s, xs[0] + h), xs[-1])
    return (np.interp(s, xs, vs) - np.interp(s - h, xs, vs)) / h


def prune_collinear(xs, vs, eps=EPS_PRUNE):
    while len(xs) > 2:
        x0, x1, x2 = xs[:-2], xs[1:-1], xs[2:]
        v0, v1, v2 = vs[:-2], vs[1:-1], vs[2:]
        frac = (x1 - x0) / (x2 - x0)
        chord = v0 + frac * (v2 - v0)
        err = np.abs(v1 - chord)
        removable = err <= eps
        if not removable.any():
            break
        # remove every other removable interior point per pass (avoid
        # removing two neighbors whose chord errors were computed jointly)
        keep = np.ones(len(xs), dtype=bool)
        last_removed = -2
        for i in np.nonzero(removable)[0]:
            idx = i + 1
            if idx - last_removed >= 2:
                keep[idx] = False
                last_removed = idx
        xs, vs = xs[keep], vs[keep]
    return xs, vs


# ---------------------------------------------------------------------------
# Backward pass
# ---------------------------------------------------------------------------

def _discharge_power_grid(bs):
    """Hardware-true integer-percent discharge levels, replay-compatible:
    pct*max/100 for pct where the level clears the classification floor
    (mirrors _discharge_candidates' min_pct)."""
    rate_step = bs.max_discharge_power_kw / 100
    min_pct = int(np.floor(POWER_CLASSIFICATION_THRESHOLD_KW / rate_step)) + 1
    return np.array([pct * rate_step for pct in range(min_pct, 101)])


def _candidate_matrix(X, t, xs_next, vs_next, ctx):
    """Value of every action at every soe in X: (len(X), n_actions)."""
    bs, dt, buy, sell, cons, solar, thr = ctx
    soe_col = X.reshape(-1, 1)

    power_row = ctx_power_row(bs)
    next_soe = _state_transition_grid(
        soe_col, power_row, bs, dt,
        solar_production=solar[t], home_consumption=cons[t],
    )
    reward = _compute_reward_grid(
        power_row, soe_col, next_soe,
        home_consumption=cons[t], battery_settings=bs, dt=dt,
        current_buy_price=buy[t], current_sell_price=sell[t],
        solar_production=solar[t],
        self_throttle_export_threshold_kwh=thr,
    )

    min_soe, max_soe = bs.min_soe_kwh, bs.max_soe_kwh
    is_charge = power_row > 0.001
    is_discharge = power_row < -0.001

    # STORE feasibility: replay's _charge_candidate rule
    max_charge_power = (max_soe - soe_col) / dt / bs.efficiency_charge
    feasible = ~is_charge | (max_charge_power > POWER_CLASSIFICATION_THRESHOLD_KW)

    # discharge feasibility: production masks
    max_discharge_power = (soe_col - min_soe) / dt * bs.efficiency_discharge
    feasible = feasible & (~is_discharge | (np.abs(power_row) <= max_discharge_power))
    ac_cap_kwh = _effective_ac_cap_kwh(bs, dt)
    if ac_cap_kwh is not None:
        ac_headroom = max(0.0, ac_cap_kwh - min(solar[t], ac_cap_kwh))
        feasible = feasible & (~is_discharge | (np.abs(power_row) * dt <= ac_headroom))
    feasible = feasible & (next_soe >= min_soe) & (next_soe <= max_soe)

    value = reward + pwl_eval(xs_next, vs_next, next_soe)
    value = np.where(feasible, value, -np.inf)

    # SOLAR_EXPORT bypass (#313): next_soe == soe exactly
    zeros_col = np.zeros_like(soe_col)
    reward_bypass = _compute_reward_grid(
        zeros_col, soe_col, soe_col,
        home_consumption=cons[t], battery_settings=bs, dt=dt,
        current_buy_price=buy[t], current_sell_price=sell[t],
        solar_production=solar[t],
        self_throttle_export_threshold_kwh=thr,
    )
    value_bypass = reward_bypass + pwl_eval(xs_next, vs_next, soe_col)
    return np.hstack([value, value_bypass])


_POWER_ROW_CACHE = {}


def ctx_power_row(bs):
    key = id(bs)
    if key not in _POWER_ROW_CACHE:
        d = _discharge_power_grid(bs)
        _POWER_ROW_CACHE[key] = np.concatenate([[0.0, 0.2], -d]).reshape(1, -1)
    return _POWER_ROW_CACHE[key]


def _seed_points(t, xs_next, ctx):
    """Initial breakpoint candidates: previous breakpoints and their one-step
    preimages under the translation-like actions, plus known transition
    kinks, plus a coarse safety net grid. Hidden kinks (e.g. discharge-shift
    preimages) are found by adaptive probing."""
    bs, dt, buy, sell, cons, solar, thr = ctx
    min_soe, max_soe = bs.min_soe_kwh, bs.max_soe_kwh
    surplus = max(0.0, solar[t] - cons[t])
    rate_t = bs.max_charge_power_kw * dt
    c_store = rate_t * bs.efficiency_charge
    c_idle = min(surplus, rate_t) * bs.efficiency_charge

    pts = [xs_next, xs_next - c_store, np.array([min_soe, max_soe])]
    if c_idle > 0:
        pts.append(xs_next - c_idle)
    # transition/reward kinks
    kinks = [max_soe - rate_t * bs.efficiency_charge,
             max_soe - surplus * bs.efficiency_charge,
             max_soe - c_idle,
             max_soe - POWER_CLASSIFICATION_THRESHOLD_KW * dt * bs.efficiency_charge]
    # discharge feasibility onsets (99 pts, cheap, exact)
    e_d = np.abs(_discharge_power_grid(bs)) * dt / bs.efficiency_discharge
    pts.append(min_soe + e_d)
    pts.append(np.array(kinks))
    pts.append(np.arange(min_soe, max_soe + 0.1, 0.1))  # safety net
    X = np.unique(np.clip(np.concatenate(pts), min_soe, max_soe))
    # dedupe within 1e-9
    keep = np.concatenate([[True], np.diff(X) > 1e-9])
    return X[keep]


def backward_pass_pwl(horizon, buy, sell, cons, solar, bs, dt,
                      terminal_value_per_kwh=0.0,
                      thr=BATTERY_EXPORT_THRESHOLD_KWH,
                      eps=EPS_REFINE, verbose=False):
    ctx = (bs, dt, buy, sell, cons, solar, thr)
    min_soe, max_soe = bs.min_soe_kwh, bs.max_soe_kwh
    xs = np.array([min_soe, max_soe])
    vs = np.array([0.0, terminal_value_per_kwh * (max_soe - min_soe)])
    V = [None] * (horizon + 1)
    V[horizon] = (xs, vs)
    max_pts = 0
    for t in reversed(range(horizon)):
        xs_next, vs_next = V[t + 1]
        X = _seed_points(t, xs_next, ctx)
        for _ in range(MAX_REFINE_ITERS):
            vals = _candidate_matrix(X, t, xs_next, vs_next, ctx)
            Vt = vals.max(axis=1)
            w = np.diff(X)
            wide = w > 1e-8
            if not wide.any():
                break
            x0 = X[:-1][wide]
            ww = w[wide]
            probes = np.concatenate([x0 + 0.5 * ww, x0 + 0.381966 * ww])
            pv = _candidate_matrix(probes, t, xs_next, vs_next, ctx).max(axis=1)
            lin = np.interp(probes, X, Vt)
            bad = np.abs(pv - lin) > eps
            if not bad.any():
                break
            X = np.sort(np.concatenate([X, probes[bad]]))
            keep = np.concatenate([[True], np.diff(X) > 1e-12])
            X = X[keep]
            if len(X) > MAX_POINTS:
                print(f"  t={t}: point cap hit ({len(X)}), stopping refinement")
                break
        vals = _candidate_matrix(X, t, xs_next, vs_next, ctx)
        Vt = vals.max(axis=1)
        xs_t, vs_t = prune_collinear(X, Vt)
        V[t] = (xs_t, vs_t)
        max_pts = max(max_pts, len(xs_t))
        if verbose:
            print(f"  t={t}: {len(xs_t)} breakpoints (pre-prune {len(X)})", flush=True)
    return V, max_pts


# ---------------------------------------------------------------------------
# Replay (Step 2) against the PWL V -- mirrors _best_action_at_continuous_state
# ---------------------------------------------------------------------------

def replay_pwl(V, horizon, buy, sell, cons, solar, bs, dt, initial_soe,
               initial_cost_basis, thr=BATTERY_EXPORT_THRESHOLD_KWH):
    ac_cap_kwh = _effective_ac_cap_kwh(bs, dt)
    s = initial_soe
    cb = initial_cost_basis
    periods = []
    total_reward = 0.0
    for t in range(horizon):
        xs_next, vs_next = V[t + 1]
        best = None  # (value, power, next_soe, new_cb, reward, forced_next)
        candidates = [(0.0, None)]  # IDLE
        for p in _discharge_candidates(
            s, bs, dt, cons[t], solar[t],
            self_throttle_export_threshold_kwh=thr, ac_cap_kwh=ac_cap_kwh,
        ):
            candidates.append((-p, None))
        cc = _charge_candidate(s, bs, dt, None)
        if cc is not None:
            candidates.append((cc, None))
        candidates.append((0.0, s))  # bypass: forced next_soe == soe

        for power, forced_next in candidates:
            if forced_next is None:
                nxt = _state_transition(s, power, bs, dt,
                                        solar_production=solar[t],
                                        home_consumption=cons[t])
                floor = bs.min_soe_kwh if s >= bs.min_soe_kwh else s
                if nxt < floor or nxt > bs.max_soe_kwh:
                    continue
            else:
                nxt = forced_next
            reward, new_cb = _compute_reward(
                power=power, soe=s, next_soe=nxt, period=t,
                home_consumption=cons[t], battery_settings=bs, dt=dt,
                buy_price=buy, sell_price=sell, solar_production=solar[t],
                cost_basis=cb, self_throttle_export_threshold_kwh=thr,
            )
            value = reward + pwl_eval(xs_next, vs_next, nxt)
            if best is None or value > best[0]:
                best = (value, power, nxt, new_cb, reward)

        value, power, nxt, new_cb, reward = best
        pd = _build_period_data(
            power=power, soe=s, next_soe=nxt, period=t,
            home_consumption=cons[t], battery_settings=bs, dt=dt,
            buy_price=buy, sell_price=sell, solar_production=solar[t],
            new_cost_basis=new_cb, currency="SEK",
            continuation_value=float(pwl_eval(xs_next, vs_next, nxt)),
        )
        pd.decision.shadow_price = float(pwl_left_slope(*V[t], s))
        periods.append(pd)
        total_reward += reward
        s, cb = nxt, new_cb
    return periods, total_reward


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------

def load_fixture():
    path = os.path.join(os.environ["BESS_REPO"],
                        "core/bess/tests/unit/data/regression_2026_08_02_043728.json")
    with open(path) as f:
        sc = json.load(f)
    b = sc["battery"]
    bs = BatterySettings(
        total_capacity=b["max_soe_kwh"],
        min_soc=(b["min_soe_kwh"] / b["max_soe_kwh"]) * 100.0,
        max_soc=100.0,
        max_charge_power_kw=b["max_charge_power_kw"],
        max_discharge_power_kw=b["max_discharge_power_kw"],
        efficiency_charge=b["efficiency_charge"],
        efficiency_discharge=b["efficiency_discharge"],
        cycle_cost_per_kwh=b["cycle_cost_per_kwh"],
        inverter_max_ac_power_kw=b.get("inverter_max_ac_power_kw", 0.0),
        inverter_ac_power_margin=b.get("inverter_ac_power_margin", 0.0),
    )
    return sc, bs, b["initial_soe"], b["initial_cost_basis"]


def experiment_fixture():
    print("=" * 72)
    print("EXPERIMENT 1: #450 fixture (real #448 debug bundle inputs)")
    print("=" * 72)
    sc, bs, s0, cb0 = load_fixture()
    buy, sell = sc["buy_price"], sc["sell_price"]
    cons, solar = sc["home_consumption"], sc["solar_production"]
    horizon, dt = len(buy), sc["period_duration_hours"]

    prod = optimize_battery_schedule(
        buy_price=buy, sell_price=sell, home_consumption=cons,
        battery_settings=bs, solar_production=solar,
        initial_soe=s0, initial_cost_basis=cb0, period_duration_hours=dt,
    )
    prod_intents = [pd.decision.strategic_intent for pd in prod.period_data]
    prod_cost = prod.economic_summary.battery_solar_cost
    print(f"production intents[34:38] = {prod_intents[34:38]}")
    print(f"production planned cost   = {prod_cost:.7f}")

    t0 = time.perf_counter()
    V, max_pts = backward_pass_pwl(horizon, buy, sell, cons, solar, bs, dt, verbose=True)
    t_bwd = time.perf_counter() - t0
    t0 = time.perf_counter()
    periods, total_reward = replay_pwl(V, horizon, buy, sell, cons, solar,
                                       bs, dt, s0, cb0)
    t_rep = time.perf_counter() - t0
    proto_intents = [pd.decision.strategic_intent for pd in periods]
    proto_cost = sum(pd.economic.hourly_cost for pd in periods)
    v0 = float(pwl_eval(*V[0], s0))
    print(f"prototype  intents[34:38] = {proto_intents[34:38]}")
    print(f"prototype  planned cost   = {proto_cost:.7f}")
    print(f"V0(s0) = {v0:.9f}   sum(rewards) = {total_reward:.9f}   "
          f"consistency gap = {abs(v0 - total_reward):.2e}")
    print(f"timing: backward {t_bwd:.2f}s, replay {t_rep:.2f}s, "
          f"max breakpoints {max_pts}")

    gate1 = proto_intents[34:38] == ["SOLAR_EXPORT", "SOLAR_STORAGE",
                                     "SOLAR_STORAGE", "SOLAR_STORAGE"]
    gate2 = proto_cost <= prod_cost + 1e-6
    gate3 = abs(v0 - total_reward) < 1e-3
    print(f"GATE window-flip: {'PASS' if gate1 else 'FAIL'}")
    print(f"GATE dominance  : {'PASS' if gate2 else 'FAIL'} "
          f"(delta = {prod_cost - proto_cost:+.7f} SEK in prototype's favor)")
    print(f"GATE consistency: {'PASS' if gate3 else 'FAIL'}")
    # show the window detail
    for i in range(33, 39):
        pd_p, pd_o = periods[i], prod.period_data[i]
        print(f"  idx {i} (period {i+18}): proto={pd_p.decision.strategic_intent:14s}"
              f" soe {pd_p.energy.battery_soe_start:6.3f}->{pd_p.energy.battery_soe_end:6.3f}"
              f" | prod={pd_o.decision.strategic_intent:14s}"
              f" soe {pd_o.energy.battery_soe_start:6.3f}->{pd_o.energy.battery_soe_end:6.3f}")
    return gate1 and gate2 and gate3


def experiment_law():
    print("=" * 72)
    print("EXPERIMENT 2: Governing Economic Law (steady-state shadow = sell)")
    print("=" * 72)
    bs = BatterySettings(
        total_capacity=20.0, min_soc=11.0, max_soc=100.0,
        max_charge_power_kw=10.0, max_discharge_power_kw=10.0,
        efficiency_charge=0.97, efficiency_discharge=0.95,
        cycle_cost_per_kwh=0.40,
    )
    buy = [1.0] * 8 + [5.0] * 8
    sell = [0.3] * 16
    solar = [4.0] * 8 + [0.0] * 8
    cons = [0.5] * 8 + [2.0] * 8
    dt = 0.25
    V, _ = backward_pass_pwl(16, buy, sell, cons, solar, bs, dt)
    periods, _ = replay_pwl(V, 16, buy, sell, cons, solar, bs, dt,
                            bs.max_soe_kwh, bs.cycle_cost_per_kwh)
    ok = True
    for t in range(8):
        sp = periods[t].decision.shadow_price
        mark = ""
        if t >= 1:
            if abs(sp - sell[t]) > 0.01:
                ok = False
                mark = "  <-- VIOLATION"
        print(f"  t={t}: shadow_price = {sp:.6f} (sell = {sell[t]}){mark}")
    print(f"GATE economic-law: {'PASS' if ok else 'FAIL'}")
    return ok


def experiment_scaling():
    print("=" * 72)
    print("EXPERIMENT 3: runtime + breakpoint growth at 192 periods")
    print("=" * 72)
    sc, bs, s0, cb0 = load_fixture()
    reps = 3  # 78 * 3 = 234 -> trim to 192
    buy = (sc["buy_price"] * reps)[:192]
    sell = (sc["sell_price"] * reps)[:192]
    cons = (sc["home_consumption"] * reps)[:192]
    solar = (sc["solar_production"] * reps)[:192]
    dt = sc["period_duration_hours"]
    t0 = time.perf_counter()
    V, max_pts = backward_pass_pwl(192, buy, sell, cons, solar, bs, dt)
    t_bwd = time.perf_counter() - t0
    t0 = time.perf_counter()
    _, _ = replay_pwl(V, 192, buy, sell, cons, solar, bs, dt, s0, cb0)
    t_rep = time.perf_counter() - t0
    print(f"backward {t_bwd:.2f}s, replay {t_rep:.2f}s, "
          f"max breakpoints {max_pts}")
    ok = t_bwd + t_rep < 60.0
    print(f"GATE runtime (<60s prototype budget): {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    exps = os.environ.get("PWL_EXPERIMENTS", "123")
    g1 = experiment_fixture() if "1" in exps else True
    g2 = experiment_law() if "2" in exps else True
    g3 = experiment_scaling() if "3" in exps else True
    print("=" * 72)
    print(f"OVERALL: {'ALL GATES PASS' if (g1 and g2 and g3) else 'GATES FAILED'}")
