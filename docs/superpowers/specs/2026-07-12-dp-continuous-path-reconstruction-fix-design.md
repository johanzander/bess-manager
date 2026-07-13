# Design: Fix DP continuous-path reconstruction error on extended horizons

**Date**: 2026-07-12
**Status**: Option A ruled out; Option B implemented and shipped (branch
`fix/275-option-b-discretization`, reduces but does not eliminate #275);
Option C remains open, tracked as #276
**Related**: #275 (reported symptom, root-caused), #126 (original user report),
#251 (prior, unrelated terminal-value fix), #236 (DP hot-loop perf — blocks
one of the options below), 2026-07-06-dp-bellman-guardrail-removal-design.md
(introduced the mechanism this doc addresses, as a partial fix)

## Problem

Once tomorrow's real day-ahead prices enter the optimization horizon (192
periods instead of 96, terminal value forced to `0.0` per
`_calculate_terminal_value`), the DP can hold battery charge back from a
known, higher near-term sell price and export it later at a known, lower
sell price — a direct, quantifiable revenue loss with no uncertainty to
justify it (Belpex/ENTSO-e day-ahead prices are published values once both
days are in the horizon, not forecasts).

Root-caused in #275: `_run_dynamic_programming`'s backward induction
(`dp_battery_algorithm.py:602-718`) is exact and correct — forward-simulating
its own grid-consistent policy reproduces its computed value function
exactly. The bug is in `optimize_battery_schedule`'s Step 2, which
reconstructs the actual period-by-period schedule via
`_best_action_at_continuous_state` / `_interpolate_value`
(`dp_battery_algorithm.py:721-821`, lines `1046-1064` for the call site).
Step 2 chooses each period's action using **linearly interpolated**
`V[t+1, :]` at the true continuous SoE, rather than the nearest-grid value
Step 1 used to build `V`. `V` has genuine kinks (slope discontinuities from
`SOE_STEP_KWH`/`POWER_STEP_KW` discretization plus the
`BATTERY_EXPORT_THRESHOLD_KWH` self-throttling cutoff at line 344), so
interpolation misjudges local marginal value near them. Because Step 2 lands
on a fresh non-grid SoE every period, this error compounds period-over-period
across the horizon.

Measured on the #275 reproduction (2-day, 168-period horizon after startup
offset): production Step 2 captured only **69%** of the value the exact
backward-induction value function said was achievable (0.853 vs. 1.229 SEK).

## Why this wasn't caught before

This exact mechanism (grid-snap-vs-continuous mismatch in Step 2) was already
identified and partially addressed in
`2026-07-06-dp-bellman-guardrail-removal-design.md`. That work tried both
extremes:

- **Snap to nearest grid index, use that cell's stored policy** (the
  original Step 2 behavior): regressed the pinned single-day (96-period)
  fixture set by 0.27 SEK on the one fixture that showed any discretization
  residual.
- **Interpolated recompute** (current production behavior, what this doc is
  about): reduced that same regression to 0.16 SEK — *better* on single-day
  fixtures — but explicitly documented as not eliminating it, with "finer
  SoE/power discretization or a continuous-action reformulation" flagged as
  out of scope for that PR.

That acceptance was reasonable at the time: it was validated only against
single-day fixtures, where the residual tops out around 0.16 SEK (~0.06% of
daily cost) — negligible. **The 2-day real-price horizon in #275 exposes a
much larger version of the same root cause (~30% of achievable value on that
horizon)**, because (a) more periods means more compounding of the same
per-period interpolation error, and (b) Frank's contract's sharp buy≫sell
asymmetry produces sharper `LOAD_SUPPORT`/`BATTERY_EXPORT` kinks in `V` than
the single-day fixtures likely exercised.

**Important tension to resolve before choosing a fix**: #275's own
reproduction shows the *opposite* ranking from the 2026-07-06 finding — on
that 2-day scenario, grid-consistent reconstruction reproduces the DP's exact
optimal value, while interpolation captures only 69% of it. So neither
"snap to grid" nor "interpolate" is a clean global win — each does better on
a different regime (single-day vs. multi-day, mild vs. sharp price
asymmetry). This doc's validation plan (below) must cover both regimes
before recommending a direction.

## Options considered

### Option A: Revert Step 2 to grid-snap action selection

Use the same nearest-grid lookup (`round()`) Step 1 used to build `V`, for
the *action selection* only — interpolation could still be used to report
the continuous SoE trajectory for display (debug bundle, UI), just not to
drive the decision.

- **Pro**: Exact match to backward induction's own optimum on the #275
  scenario (verified). No new state-space cost — same discretization,
  same performance profile as today.
- **Con**: This is the behavior 2026-07-06 already tried and reverted away
  from, because it regressed the pinned single-day fixture set more than
  interpolation does. Reintroducing it risks reintroducing that regression.
  Must re-validate against all 26 pinned fixtures, not just #275's scenario.

### Option B: Finer discretization (smaller `SOE_STEP_KWH`/`POWER_STEP_KW`)

Shrink the grid steps so the kinks interpolation misrepresents become
smaller, reducing interpolation error directly without changing Step 2's
logic.

- **Pro**: Doesn't require picking a side in the Option A tension — shrinks
  the error for both single-day and multi-day cases, in the same direction
  2026-07-06 flagged as the "real" fix.
- **Con**: Directly worsens the state-space size the DP already struggles
  with. #236 (open) measures the *current* discretization (0.1 kWh /
  0.2 kW: ~240 SOE levels × ~150 power levels) at ~11.5s for a 96-period
  horizon and ~22.8s for 192 periods, unvectorized. Halving both steps
  roughly quadruples the per-period inner-loop cost (2× states × 2× actions)
  — pushing 192-period horizons toward ~90s+, unacceptable for a 15-minute
  re-optimization cadence. **This option is effectively blocked on #236's
  vectorization landing first**, or needs to ship alongside it.

### Option C: Continuous-action reformulation

Replace the discretized action search with a continuous optimization
(e.g. closed-form per-period optimum given `V[t+1,:]`, or a coarser grid
with local refinement near the chosen action). Eliminates the discretization
kink problem at its root rather than shrinking or routing around it.

- **Pro**: Most principled long-term fix; no grid-vs-interpolate tension at
  all once the action space itself isn't discretized.
- **Con**: Largest scope — a genuine algorithm redesign, not a targeted
  patch. 2026-07-06 flagged this as "out of scope" for the same reason.
  Needs its own investigation into whether the reward function
  (`_compute_reward`) is smooth enough for closed-form or local-search
  optimization per period, and how it interacts with the discrete
  `BATTERY_EXPORT_THRESHOLD_KWH` self-throttling cutoff (itself a
  discontinuity, independent of the SOE/power grid).

## Recommendation (superseded — see Validation results below)

~~Start with Option A~~ — ruled out. See results below. Next: pursue
**Option B**, coordinated with #236 (vectorize first, or ship together).
**Option C** stays a tracked follow-up (#276) regardless.

## Validation results: Option A (2026-07-12)

Implemented Option A exactly as scoped — replaced `_interpolate_value`'s
linear interpolation with a `_snapped_value` nearest-grid lookup
(`round()`, matching Step 1's own internal read of `V`) as the continuation
value in `_best_action_at_continuous_state`, action selection only; the
continuous SoE trajectory reporting (`current_soe` propagation in
`optimize_battery_schedule`'s Step 2 loop) was untouched and remains exact
either way, so this does not affect `R == P` plan-faithfulness.

**Ran the full pinned single-day fixture suite** (`test_scenarios.py`, 29
tests / 27 fixture files) in a clean worktree off `origin/main`
(`fix/275-dp-interpolation-error`), before and after the change:

- **Baseline (current production, interpolated)**: 29/29 pass.
- **Option A (grid-snap)**: **17/29 fail.** Every one of the 14 fixtures with
  a directly comparable pinned cost value regressed — **14/14 worse, 0
  better, 0 unchanged.** Regression magnitudes ranged from 0.04 SEK to
  **1.47 SEK** (mean 0.48 SEK), materially larger than 2026-07-06's reported
  single-fixture 0.27 SEK worst case.

This is a decisive, unanimous result: Option A is **not** a viable global
fix. It resolves #275's multi-day scenario (confirmed exactly optimal there)
at the cost of a uniform, unambiguous regression across the single-day
fixture set — worse in every single measured case, not a mixed bag. This
both confirms and sharpens the tension flagged above: grid-snap and
interpolation are not two comparably-good options with different edge cases
each wins on the current codebase — grid-snap is now measurably worse on the
common case (single-day horizons, the vast majority of real usage) than it
was in 2026-07-06's smaller/older fixture set.

**Conclusion**: do not pursue Option A further. The code change was reverted
(not merged) after this validation. Proceed to Option B (finer
discretization, coordinated with #236) as the next candidate, since it's the
only remaining option that doesn't require picking a side in this tradeoff.

## Validation results: Option B (2026-07-12)

#236 (DP hot-loop vectorization) landed first, giving ~114-117x headroom
(96p: 12.5s → 0.11s; 192p: 25.4s → 0.22s) — see that PR. Option B work
branched from the vectorized code.

**Discretization levels tried, in order:**

1. `SOE_STEP_KWH=0.0125, POWER_STEP_KW=0.025` (both quartered): net
   improvement on pinned fixtures, but `POWER_STEP_KW=0.025` produced
   sub-1%-of-max-power planned actions that real hardware rate registers
   (integer percent, `core/bess/simulation/inverter_simulator.py::_map_rates`)
   round to 0% — silently never executed. Produced a serious `R != P`
   violation on `synthetic_seasonal_summer`: planned cost looked *better*
   (-14.80 vs -14.71 baseline) but realized cost was **+6.11 vs -14.67**,
   a ~21 SEK real-world harm the planned number completely hid. **Ruled
   out** — `POWER_STEP_KW` has a hard floor at real hardware's rate
   resolution that `SOE_STEP_KWH` doesn't share (SOE precision is internal
   bookkeeping, power precision becomes a hardware register command).
2. `SOE_STEP_KWH=0.0125, POWER_STEP_KW=0.1`: fixed the R≠P violation, but
   `POWER_STEP_KW=0.1` turned out to exactly equal a hardcoded
   `_POWER_THRESHOLD_KW = 0.1` classification threshold in
   `decision_intelligence.py::classify_strategic_intent` — the smallest
   nonzero grid action failed that threshold's strict `>` comparison and
   fell through to a passive-charging fallback, misclassifying real
   grid-charging as `SOLAR_STORAGE` almost everywhere. Traced to a **21 SEK
   R≠P gap** on `synthetic_seasonal_summer` (plan: -14.80, hardware never
   actually charges since the mislabeled intent maps to a no-op command;
   realized: +6.11) and `GRID_CHARGING` vanishing from ~19/22 fixtures'
   behavioral distributions. **Root-caused, not a fundamental Option B
   risk** — see the postmortem in `core/bess/dp_constants.py`.
3. `SOE_STEP_KWH=0.0125, POWER_STEP_KW=0.15`: dodged that specific
   collision, but `test_plan_faithfulness.py`'s dedicated hand-crafted
   `grid_charge_arbitrage` scenario still showed a 2.99 SEK R≠P gap —
   `decision_intelligence.py` has *multiple* hardcoded `0.1` "significant
   flow" thresholds beyond just `_POWER_THRESHOLD_KW`, so picking a power
   step by trial-and-error avoidance doesn't scale.
4. `SOE_STEP_KWH=0.025, POWER_STEP_KW=0.2` (power step reverted to the
   proven original value; only SOE refined): zero R≠P violations across
   the *entire* suite including `test_plan_faithfulness.py`. Clean.
5. Refined `_POWER_THRESHOLD_KW` and the other decision_intelligence.py
   `0.1` thresholds to derive from `POWER_STEP_KW` via a new
   `core/bess/dp_constants.py` (single source of truth for the DP's grid
   resolution), closing the whole collision class for any future tuning —
   not just today's specific value.
6. Found `SOE_STEP_KWH=0.025` still slightly finer than
   `POWER_STEP_KW * dt` (0.2 * 0.25 = 0.05 for quarterly-resolution
   periods), causing `shadow_price` (the DP value-function gradient,
   reported per period and used by the real-time solar-export discharge
   gate) to become jagged — alternating between 0 and 2x its true value
   at consecutive periods, since not every SOE grid point is independently
   reachable via a single action. **Final value: `SOE_STEP_KWH=0.05`**,
   exactly matching the quarterly reachable-state increment. Confirmed
   clean (`shadow_price` smooth, matches steady-state sell price).

**Final shipped configuration**: `SOE_STEP_KWH=0.05`, `POWER_STEP_KW=0.2`
(unchanged from original), in `core/bess/dp_constants.py`.

**Full-suite validation** (branch `fix/275-option-b-discretization`,
committed on top of `perf/236-vectorize-dp-backward-induction`):
`.venv/bin/pytest` (no marker filter): **1454 passed, 16 skipped, 0
failed.** 15 pinned fixtures re-pinned, all checked by direction before
re-pinning (net -3.7 SEK aggregate on the measured set, one small
regression of +0.10 SEK, rest improvements) — not blindly accepted, per
the standing 2026-07-06 convention. Two behavioral tests
(`test_solar_export_discharge_gate.py`) and one sanity-check
(`test_terminal_value.py`) adjusted after confirming their premise no
longer held at any grid resolution or that finer discretization
legitimately found a better/different (not wrong) outcome — see the
shipped commit message for the full reasoning on each.

**#275 reproduction result**: on the issue's "Worse" scenario, tonight's
peak SOE drains from 15.0 kWh to 10.95 kWh (held: 3.90 kWh above the
7.05 kWh floor) — down from the original bug's 12.4 kWh (held: 5.32 kWh),
a ~27% reduction. **Reduces but does not eliminate #275** — the residual
matches the design doc's original prediction (Option B alone can't fully
close the gap; Option C is still needed for that). Confirmed via direct
DP-function tracing (not just cost totals) that the qualitative defect
(selling at a dominated worse price instead of a better one) is
meaningfully mitigated: much of the previously-dominated `BATTERY_EXPORT`
at a worse price is now replaced by legitimate `LOAD_SUPPORT`
self-consumption, though a residual export-at-worse-price pattern remains
in some periods.

**Benchmark**: 96p 0.04s, 168p 0.07s (vs. #236's already-vectorized
0.11s/0.22s baseline at the original discretization) — finer SOE grid
costs roughly 2-3x, still far inside the 15-minute re-optimization budget.

## Open questions

- Does `_interpolate_value`'s linear interpolation choice matter, or would
  e.g. monotone cubic interpolation reduce the kink-crossing error enough to
  avoid touching Option A/B at all? Not yet investigated — cheap to test
  empirically alongside the options above.
- Is the `BATTERY_EXPORT_THRESHOLD_KWH` self-throttling cutoff (a hard
  `<=` branch, `dp_battery_algorithm.py:344`) itself a source of kinks
  independent of the SOE/power grid, and would Option C need to smooth that
  too?

## Out of scope for this doc

- Implementing any of the options above — this is a design/validation doc
  only, per project convention (2026-07-06 doc followed the same pattern:
  propose, validate empirically, then ship as its own PR).
- The `min_action_profit_threshold` follow-up already tracked from
  2026-07-06 (unrelated field, separate migration path).
