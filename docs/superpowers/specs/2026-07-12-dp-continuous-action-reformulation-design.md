# Design: Continuous-action / exact piecewise-linear reformulation of the DP (#276)

**Date**: 2026-07-12
**Status**: Investigation only — no implementation, per project convention
**Related**: #276 (this issue), #275 (reported symptom, root cause — Options A/B,
merged to `main` as of this doc — Option B's `dp_constants.py` and
`SOE_STEP_KWH=0.05` are current production values), 2026-07-12-dp-continuous-path-reconstruction-fix-design.md
(Options A/B history), #236 (DP vectorization, merged to `main`)

## Problem being investigated

#275's root cause is that `optimize_battery_schedule`'s Step 2 reconstructs
the actual schedule at a true continuous SoE by linearly interpolating a
value function `V` that was computed on a fixed `SOE_STEP_KWH`/`POWER_STEP_KW`
grid (now `core/bess/dp_constants.py`, imported into `dp_battery_algorithm.py:67`).
`V` has kinks wherever the grid or a reward discontinuity (e.g.
`BATTERY_EXPORT_THRESHOLD_KWH`, `dp_battery_algorithm.py:503`) changes the
optimal action's character, and linear interpolation across a kink misjudges
local marginal value. Option A (grid-snap, ruled out) and Option B (finer
discretization, `SOE_STEP_KWH=0.05`, now shipped on `main`) each reduce this
but don't eliminate it — see the linked doc for the full validation history.

This issue (#276) asks whether the fixed grid can be removed as the source
of the mismatch entirely, via:

1. Solving for the optimal power analytically per period, instead of grid
   search.
2. Tracking `V` as an exact piecewise-linear function of SoE, not a sampled
   grid — the classical LP-sensitivity result that a linear-dynamics,
   piecewise-linear-reward value function is itself exactly piecewise-linear
   with a small number of true breakpoints.

## Empirical investigation

Built a standalone prototype (not part of this PR/branch) using the real
`_compute_reward` / `_state_transition` / `_interpolate_value` /
`_run_dynamic_programming` code against a real scenario fixture
(`historical_2024_08_16_high_spread_no_solar`, 24-period horizon, no solar).
For four representative `(t, soe)` cells (varying horizon position and SoE,
all at off-grid SoE values — i.e. not exact multiples of `SOE_STEP_KWH`,
matching what Step 2 actually encounters after a few periods of real state
transitions), densely sampled the single-period objective
(`reward(power) + V_interpolated(next_soe(power))`) at ~20,000 points across
the full feasible power range and located every slope-change breakpoint.

### Finding 1: the objective is genuinely piecewise-linear, not smooth

No cell showed curvature between breakpoints — every segment between two
adjacent breakpoints was exactly flat-slope, confirming the premise that the
per-period objective (reward + continuation value) is piecewise-linear in
the continuous power action. This is consistent with both proposed
approaches being structurally sound *in principle*.

### Finding 2: today's `V` has far more breakpoints than "genuine" kinks — and they're a grid artifact

Each test cell showed **36–126 breakpoints**, spaced at almost perfectly
regular ~0.05 kW intervals (matching current production `SOE_STEP_KWH=0.05`
divided by this scenario's `dt=1.0`). This is not evidence of a genuinely
complex reward landscape —
it's the direct fingerprint of `_interpolate_value`'s linear interpolation
between `SOE_STEP_KWH`-spaced grid points: every time `next_soe(power)`
crosses a grid line, the interpolation's local slope changes, whether or not
the underlying reward actually has a kink there. This directly confirms the
issue's premise ("artificial breakpoints introduced by uniform 0.1 kWh
sampling") with real numbers instead of by inspection.

The corollary: probing today's grid-based `V` cannot by itself tell us how
many *real* breakpoints the exact value function would have (Approach 2's
core claim). That requires actually implementing the backward recursion
that propagates exact breakpoints period-by-period — a genuine prototype,
not a measurement on existing code. Scoped as follow-up work below.

### Finding 3: the discretization error is real and compounds, even in a single period

Comparing the dense-scan (near-continuous) optimum against what today's
production grid search (`POWER_STEP_KW=0.2`, ~61 levels) finds at the same
cell, using the same interpolated `V`:

| t | soe (off-grid) | dense-scan optimum | grid-search optimum | single-period gap |
|---|---|---|---|---|
| 10 | 13.08 | power=-1.083 kW, value=-118.642 | power=-1.400 kW, value=-118.675 | 0.033 |
| 21 | 6.03 | power=-3.029 kW, value=-37.762 | power=-3.000 kW, value=-37.864 | 0.102 |
| 2 | 8.04 | power=0.0015 kW (≈IDLE) | power=0.200 kW | 0.000 |
| 12 | 11.06 | power=0.0015 kW (≈IDLE) | power=0.200 kW | 0.000 |

Two of four cells show no measurable gap (STORE-disposition cells — see
Finding 4), but the two discharge cells lose 0.03–0.10 SEK *in a single
period's decision* relative to the near-continuous optimum. #275's
reproduction showed this compounding to a ~30% value gap over a 168-period
horizon; these numbers are consistent with that compounding mechanism at the
per-period level.

### Finding 4: STORE actions need no continuous search at all

Reading `_state_transition`/`_compute_reward`'s charging branch
(`dp_battery_algorithm.py:192-206`, `453-468`): for any `power >
POWER_TOLERANCE_KW`, the actual energy stored depends only on
`max_charge_power_kw`, solar surplus, and available room — **not on the
chosen `power` value itself**. This is the "binary store semantics" the
`_discretize_state_action_space` comment (`#146`) already documents. Every
positive grid point in today's ~30-level charge search produces an
identical reward — confirmed by both STORE-disposition test cells picking
`power≈0` (the IDLE-vs-charge boundary) with a flat plateau on the charging
side. **The charge side of the action space search is already redundant
work** — a real, low-risk optimization opportunity independent of #276's
main question, worth flagging separately (not scoped into this doc).

### Finding 5: the self-throttle threshold is a jump, not a kink — but a negligible one

`BATTERY_EXPORT_THRESHOLD_KWH = 0.01` (`dp_battery_algorithm.py:92`, checked
at `dp_battery_algorithm.py:503`)
produces an actual step discontinuity in reward (export credit goes from 0
to non-zero discontinuously as `grid_exported` crosses it), not just a slope
change — visible in the dense scan as one segment with `slope=0` immediately
adjacent to a segment with a very large apparent slope over one sample
interval. Because the threshold (0.01 kWh) is far smaller than one
`POWER_STEP_KW` grid step's energy (0.2 kW × 1 h = 0.2 kWh), today's coarse
grid search already straddles this discontinuity without resolving it, and
its magnitude (threshold × sell_price) is economically negligible per
period. It should still be modeled explicitly as a fixed breakpoint in any
exact reformulation (Approach 2), since "exact" tracking that silently
smooths over a real discontinuity would reintroduce a smaller version of
the same bug.

## Assessment of the two proposed approaches

**Approach 1 (closed-form / breakpoint enumeration per period)**: supported
by Findings 1 and 4. Since the objective is piecewise-linear, its optimum
always lands on a breakpoint or a domain boundary — so the per-period
search can be replaced by evaluating a *candidate set* (physical boundaries,
the self-throttle threshold, and `V_next`'s own breakpoints) instead of a
~150-point grid. Combined with Finding 4 (skip the charge side of the search
entirely, it's a single binary decision), this could plausibly become
*cheaper* than today's search, not just more accurate — the opposite of
Option B's tradeoff (finer grid = more expensive).

**Approach 2 (exact piecewise-linear `V` propagation)**: the harder,
more principled fix — if `V`'s breakpoints are tracked exactly instead of
sampled, "interpolation across a kink" (#275's root cause) stops being
possible by construction, because there's no hidden kink between two known
breakpoints. Finding 2 shows this cannot be validated against today's
grid-based `V` — it requires prototyping the actual backward recursion:
representing each `V[t, :]` as a list of `(soe, value, slope)` breakpoints,
and deriving `V[t, :]`'s breakpoints from `V[t+1, :]`'s breakpoints plus the
period's own reward breakpoints (physical bounds, self-throttle threshold).
This is a bounded, well-defined next step, not open-ended research — but is
materially larger scope than Approach 1 and depends on Approach 1's
candidate-breakpoint logic as a building block regardless (evaluating the
objective at each candidate `next_soe` breakpoint is required either way).

## Recommendation

Pursue **Approach 1 first**, scoped as its own follow-up issue/PR:

1. Replace `_best_action_at_continuous_state`'s grid search with breakpoint
   enumeration over: physical charge/discharge power bounds, the
   `BATTERY_EXPORT_THRESHOLD_KWH` crossing (Finding 5), and `V_next`'s
   existing grid breakpoints (as an intermediate step, using today's
   grid-based `V` — this alone should already close most of the gap
   Finding 3 measured, without waiting on Approach 2).
2. Separately, in `_run_dynamic_programming`'s backward induction, skip the
   redundant charge-power grid search (Finding 4) — evaluate one STORE
   action instead of ~30, a free performance win regardless of which
   approach ships.
3. Re-run #275's reproduction scenario and the full pinned-fixture suite
   (same validation discipline as Options A/B) before deciding whether
   Approach 2's larger exact-`V`-propagation investment is still needed, or
   whether Approach 1 alone closes the gap enough that #276's harder
   half can stay deferred.

This keeps the same empirically-validate-before-committing discipline the
2026-07-06 and 2026-07-12 (Options A/B) docs established, and gives Approach
1 a chance to be a small, self-contained win before committing to Approach
2's larger scope.

## Out of scope for this doc

- Implementing either approach — this is a design/validation doc only, per
  project convention.
- Approach 2's backward-recursion prototype — flagged as the necessary next
  empirical step if Approach 1 doesn't fully close #275's residual gap, not
  attempted here.
- Finding 4 (redundant charge-side search) as a shipped optimization — noted
  as a spinoff opportunity, not scoped into #276's fix.
