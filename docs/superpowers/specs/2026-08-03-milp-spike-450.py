"""MILP feasibility spike for #450 pivot: exact battery schedule via HiGHS.

Models the DP's hardware-mode semantics for the #450 fixture:
  modes: STORE (full-rate charge, solar first + grid top-up),
         IDLE (forced passive solar charge), BYPASS (hold, export surplus),
         DISCHARGE (integer-percent rate, AC-headroom capped)
  self-throttle (#240) on discharge-mode export credit
  wear cost on stored energy; eta_c/eta_d; SOE bounds.

Fixture-specific simplifications (valid for THIS input, checked):
  - buy > sell > 0 every period  -> import/export split needs no binary
  - solar always below the AC cap -> no clipping; cap only bounds discharge
  - initial_soe == min_soe        -> no below-floor handling
Goal: objective within ~1e-3 of the exact-PWL cost (-5.9983584) and
sub-second solve.
"""

import json
import os
import sys
import time

import numpy as np
from scipy import sparse
from scipy.optimize import LinearConstraint, milp

REPO = os.environ["BESS_REPO"]
sc = json.load(open(os.path.join(
    REPO, "core/bess/tests/unit/data/regression_2026_08_02_043728.json")))

buy = np.array(sc["buy_price"])
sell = np.array(sc["sell_price"])
cons = np.array(sc["home_consumption"])
solar = np.array(sc["solar_production"])
b = sc["battery"]
REPS = int(os.environ.get("TILE", "1"))
if REPS > 1:
    import numpy as _np
    buy = _np.tile(buy, REPS)[: 192]
    sell = _np.tile(sell, REPS)[: 192]
    cons = _np.tile(cons, REPS)[: 192]
    solar = _np.tile(solar, REPS)[: 192]
T = len(buy)
dt = sc["period_duration_hours"]
E0 = b["initial_soe"]
EMIN, EMAX = b["min_soe_kwh"], b["max_soe_kwh"]
ETA_C, ETA_D = b["efficiency_charge"], b["efficiency_discharge"]
WEAR = b["cycle_cost_per_kwh"]
RATE_T = b["max_charge_power_kw"] * dt              # charge throughput cap kWh
DIS_STEP = b["max_discharge_power_kw"] / 100 * dt   # 1% discharge throughput kWh
K_MIN = 2                                           # classification floor: >0.1 kW
AC_CAP = b["inverter_max_ac_power_kw"] * (1 - b["inverter_ac_power_margin"]) * dt
THR = 0.01                                          # self-throttle kWh
M = 30.0

assert (buy > sell).all() and (sell > 0).all()
assert (solar <= AC_CAP).all()

surplus = np.maximum(0.0, solar - cons)
c_idle = np.minimum(surplus, RATE_T) * ETA_C        # forced IDLE passive charge
ac_headroom = np.maximum(0.0, AC_CAP - np.minimum(solar, AC_CAP))

# ---- variable registry -----------------------------------------------------
names = []
def var(name, n=1):
    i = len(names)
    names.extend(f"{name}[{j}]" for j in range(n))
    return np.arange(i, i + n)

E = var("E", T + 1)          # SOE at period start
stS = var("stS", T)          # stored via STORE (kWh in battery)
s2b = var("s2b", T)          # solar throughput to battery under STORE
stI = var("stI", T)          # stored via IDLE
k = var("k", T)              # discharge percent (integer)
imp = var("imp", T)          # AC import (excl. grid->battery)
exp = var("exp", T)          # AC export (raw)
cred = var("cred", T)        # credited export
S = var("S", T); I_ = var("I", T); B = var("B", T); D = var("D", T)
rho = var("rho", T); sig = var("sig", T); iot = var("iot", T); z = var("z", T)
N = len(names)

integrality = np.zeros(N)
integrality[k] = 0
for g in (S, I_, B, D, rho, sig, iot, z):
    integrality[g] = 1

lb = np.zeros(N); ub = np.full(N, np.inf)
lb[E] = EMIN; ub[E] = EMAX
lb[E[0]] = ub[E[0]] = E0
ub[stS] = RATE_T * ETA_C; ub[s2b] = np.maximum(surplus, 0)
ub[stI] = np.maximum(c_idle, 0)
ub[k] = 100
ub[exp] = 6.0; ub[imp] = 50; ub[cred] = 6.0
for g in (S, I_, B, D, rho, sig, iot, z):
    ub[g] = 1

rows, cols, vals, rlb, rub, rtag = [], [], [], [], [], []
SKIP = set(os.environ.get("SKIP_GROUPS", "").split(",")) - {""}
def con(coeffs, lo, hi, tag="core"):
    if tag in SKIP:
        return
    r = len(rlb)
    for c_i, v in coeffs:
        rows.append(r); cols.append(c_i); vals.append(v)
    rlb.append(lo); rub.append(hi); rtag.append(tag)

MC2 = EMAX - EMIN
for t in range(T):
    # one mode per period
    con([(S[t], 1), (I_[t], 1), (B[t], 1), (D[t], 1)], 1, 1)

    # SOE recursion: E[t+1] = E[t] + stS + stI - k*DIS_STEP/ETA_D
    con([(E[t + 1], 1), (E[t], -1), (stS[t], -1), (stI[t], -1),
         (k[t], DIS_STEP / ETA_D)], 0, 0)

    # ---- STORE: stS = min(RATE_T*ETA_C, EMAX - E[t]) when S=1, else 0
    con([(stS[t], 1), (S[t], -RATE_T * ETA_C)], -np.inf, 0)
    con([(stS[t], 1), (E[t], 1)], -np.inf, EMAX)
    MR = RATE_T * ETA_C
    con([(stS[t], 1), (rho[t], MR), (S[t], -MR)], 0.0, np.inf, "store_force")
    MC = EMAX - EMIN
    con([(stS[t], 1), (E[t], 1), (rho[t], -MC), (S[t], -MC)], EMAX - 2 * MC, np.inf, "store_force")
    # s2b = min(surplus, stS/ETA_C) when S=1, else 0
    con([(s2b[t], 1), (S[t], -max(surplus[t], 1e-9))], -np.inf, 0)
    con([(s2b[t], 1), (stS[t], -1 / ETA_C)], -np.inf, 0)
    MS2 = max(surplus[t], 1e-9)
    con([(s2b[t], 1), (sig[t], MS2), (S[t], -MS2)], surplus[t] - MS2, np.inf, "s2b_force")
    MS3 = RATE_T / 1.0
    con([(s2b[t], 1), (stS[t], -1 / ETA_C), (sig[t], -MS3), (S[t], -MS3)], -2 * MS3, np.inf, "s2b_force")

    # ---- IDLE: stI = min(c_idle, EMAX - E[t]) when I=1, else 0
    con([(stI[t], 1), (I_[t], -max(c_idle[t], 1e-9))], -np.inf, 0)
    con([(stI[t], 1), (E[t], 1)], -np.inf, EMAX)
    MI1 = max(c_idle[t], 1e-9)
    con([(stI[t], 1), (iot[t], MI1), (I_[t], -MI1)], c_idle[t] - MI1, np.inf, "idle_force")
    con([(stI[t], 1), (E[t], 1), (iot[t], -MC2), (I_[t], -MC2)], EMAX - 2 * MC2, np.inf, "idle_force")

    # ---- DISCHARGE: k in [K_MIN..100] when D=1 else 0; energy + AC caps
    con([(k[t], 1), (D[t], -100)], -np.inf, 0)
    con([(k[t], 1), (D[t], -K_MIN)], 0, np.inf)
    con([(k[t], DIS_STEP / ETA_D), (E[t], -1)], -np.inf, -EMIN)  # removed <= E-EMIN
    con([(k[t], DIS_STEP)], -np.inf, ac_headroom[t] if ac_headroom[t] < RATE_T * 4 else np.inf)

    # ---- AC balance: exp - imp = (solar - s2b - stI/ETA_C) + k*DIS_STEP - cons
    con([(exp[t], 1), (imp[t], -1), (s2b[t], 1), (stI[t], 1 / ETA_C),
         (k[t], -DIS_STEP)], solar[t] - cons[t], solar[t] - cons[t])

    # ---- export credit: full except self-throttled in D mode
    con([(cred[t], 1), (exp[t], -1)], -np.inf, 0)
    ME = 6.0
    con([(cred[t], 1), (z[t], -ME), (D[t], ME)], -np.inf, ME, "throttle")
    con([(exp[t], 1), (z[t], -THR), (D[t], -ME)], -ME, np.inf, "throttle")

# objective: imp*buy + g2b*buy - cred*sell + WEAR*(stS + stI)
# g2b = stS/ETA_C - s2b
c_obj = np.zeros(N)
c_obj[imp] = buy
c_obj[stS] = buy / ETA_C + WEAR
c_obj[s2b] = -buy
c_obj[cred] = -sell
c_obj[stI] += WEAR

A = sparse.csc_matrix((vals, (rows, cols)), shape=(len(rlb), N))
t0 = time.perf_counter()
res = milp(c=c_obj, constraints=LinearConstraint(A, rlb, rub),
           integrality=integrality, bounds=(lb, ub) if False else
           __import__("scipy.optimize", fromlist=["Bounds"]).Bounds(lb, ub),
           options={"time_limit": 120, "mip_rel_gap": 1e-4})
el = time.perf_counter() - t0
print(f"status: {res.status} ({res.message.strip() if res.message else ''})")
print(f"solve time: {el:.2f}s")
if res.x is not None:
    print(f"objective (cost): {res.fun:.7f}   (PWL exact: -5.9983584)")
    x = res.x
    modes = []
    for t in range(33, 39):
        m = ("STORE" if x[S[t]] > 0.5 else "IDLE" if x[I_[t]] > 0.5
             else "BYPASS" if x[B[t]] > 0.5 else f"DIS(k={x[k[t]]:.0f})")
        modes.append(f"t{t}={m} E={x[E[t]]:.3f}")
    print("window: " + " | ".join(modes))
