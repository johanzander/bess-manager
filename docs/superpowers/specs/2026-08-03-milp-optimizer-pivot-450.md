# Design: MILP optimizer pivot (#450)

**Date**: 2026-08-03
**Status**: Direction decided (owner-approved); feasibility spike PASSED; full
implementation is the next phase. The exact-PWL DP on this branch is a
validated reference implementation, not the shipping fix.
**Related**: #450 (root cause), #448/#269 (field reports), #275 (same
discretization family), 2026-07-12-dp-continuous-path-reconstruction-fix-design.md
(Option C is this doc).

## Why the pivot

#450's root cause is SOE-grid snap noise in the DP backward pass. Two prior
fix attempts (backward-pass interpolation; finer grid) failed for structural
reasons: a uniform-grid V table read by ANY scheme must choose between
rounding noise (snap) and one-signed chord bias (interpolation), because the
true V's kinks live on a data-dependent lattice no uniform grid contains.

This branch first implemented the mathematically direct fix: an ε-certified
piecewise-linear V over continuous SOE (exact backward induction). It works —
window flips correctly, replay reproduces V₀ to ~1e-10, the Governing
Economic Law holds tighter than production — but costs **3.2 s at 78 periods
/ 37 s at 192** (vs 0.04 s for the grid DP), which the owner rejected. The
remaining cost is intrinsic: the exact discrete-action V carries thousands of
genuine micro-kinks (winner-switches between adjacent integer-percent
discharge levels; near-cliffs at feasibility onsets propagating through
action shifts). Tolerance knobs move runtime <30% (measured ε 1e-6→1e-3).

Decision: replace the DP with the industry-standard MILP formulation
(deterministic day-ahead arbitrage is linear apart from mode semantics).
The PWL implementation stays in branch history as the exactness referee.

## Feasibility spike (2026-08-03) — PASSED

Model (scipy.optimize.milp / HiGHS), full #450-fixture semantics: hardware
modes as one-hot binaries per period — STORE (forced full-rate charge,
solar-first + grid top-up), IDLE (forced passive solar charge), BYPASS
(hold + export, #313), DISCHARGE (percent rate) — with forced-min physics
via big-M pairs (room-vs-rate, surplus-vs-capacity), SOE recursion with
efficiencies, wear cost, AC-headroom discharge cap, #240 self-throttle
credit binary. ~8 binaries + 1 rate var per period.

| Variant | 78 periods | 192 periods | Optimum vs PWL (−5.9983584) |
|---|---|---|---|
| Integer percent rates (hardware-true) | 5–6 s | (not run) | −5.9984602 (1e-4 better) |
| Continuous rates | **0.19 s** | **0.98 s** | −6.0309207 (integer restriction costs ~3 öre/day) |

Both variants pick the correct #450 window (BYPASS then three charges,
SOE 2.0→3.222→4.444→5.666). Branch-and-bound over the integer rate lattice
is the entire cost — near-tied windows (the very phenomenon behind #450)
force deep optimality proofs.

## Key design decisions for the build phase

1. **Two-stage rates**: solve with continuous rates (fast), then
   re-integerize to the percent lattice — either fix the mode binaries and
   re-solve the small integer-rate problem, or round-and-repair with an
   R==P check. Do NOT ship continuous rates raw (#282: hardware rounds
   percent registers; plans must be executable bit-for-bit).
2. **Shadow prices from LP duals** (binaries fixed, one linprog solve) —
   validate against the Governing Economic Law test and the 0.05 kWh
   finite-difference definition the gates were tuned on (the exact V is
   micro-staircase; see dp_constants.py SOE_STEP_KWH note).
3. **Negative sell prices** break the "import/export split needs no binary"
   simplification used in the spike — the general model needs a per-period
   binary for forced-export semantics (hardware exports surplus even at
   negative prices). Spike asserted buy>sell>0 and must not be reused as-is.
4. **Semantics to re-derive as constraints, each with its pinned test**:
   #233 below-floor tolerance, #240 self-throttle, #313 bypass, #353
   future_value reporting, forced IDLE passive charge, AC cap + clipping
   (clip loss needs care under negative prices), per-period charge caps
   (temperature derating), terminal value.
5. **Solver dependency**: add-on base is Alpine (musl). Prefer `highspy`
   (~10 MB, musllinux wheels, exposes duals + tuning) over full scipy
   (~40 MB). Verify aarch64 musllinux wheel availability before committing.
6. **Reconcile the 1e-4 optimum delta** between the spike MILP and the PWL
   reference on the fixture before trusting either as the acceptance value
   (likely a small feasibility-rule mismatch, e.g. charge-candidate
   classification floor).
7. **Acceptance harness carries over unchanged**: the #450 regression test
   (`test_issue_450_soe_grid_interpolation.py`) and re-pinned fixture are
   implementation-agnostic; the full pinned fixture suite re-validates by
   direction, per convention.

The spike script is preserved alongside this doc
(`2026-08-03-milp-spike-450.py`).
