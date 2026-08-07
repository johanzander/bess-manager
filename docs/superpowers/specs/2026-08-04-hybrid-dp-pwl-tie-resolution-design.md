# Design: Hybrid grid-DP + windowed exact-PWL tie resolution (#450)

**Date**: 2026-08-04
**Status**: PROPOSED. Supersedes PR #461's full-MILP approach as the
intended fix for #450.
**Related**: #450 (root cause), 2026-08-03-milp-optimizer-pivot-450.md
(the rejected/superseded MILP pivot spec this design replaces), the
exact-PWL DP prototype already implemented in `dp_battery_algorithm.py`
during the #461 branch's checkpoint phase.

## Why this instead of full MILP

PR #461 fixed #450 by replacing the DP entirely with a MILP solved via
`scipy.optimize.milp`/HiGHS for the whole horizon, every solve. It works,
but at a real cost:

- **10-20x slower**: slow test suite went from ~12s (DP) to ~113-258s
  even after tuning `time_limit` down from 60s to 5s per solve.
- **Solve-time variance**: the same fixture/input measurably solved in
  1.6s one run and hit the full 60s timeout on a repeat run, since MIP
  solve time is driven by branch-and-bound search behavior, not a fixed
  computation.
- **A new correctness-risk class**: encoding physical logic (mode
  exclusivity, sentinel config values, credit branches) as big-M linear
  constraints is easy to get silently wrong in ways a solver will happily
  exploit for a better-looking objective. PR #461's hardening found and
  fixed four such bugs (import/export exclusivity, AC-cap sentinel
  handling, self-throttle export-credit, non-unique LP-dual shadow
  prices near capacity bounds) — none of which are bugs the grid DP is
  even capable of, but which are intrinsic to the MILP-encoding paradigm
  and could recur on any future change to the model.

All of this cost is paid on **every period of every solve**, even though
#450's actual failure mode — SOE grid-snap noise flipping a near-tied
decision — is rare: most periods have a clearly-dominant action and the
grid DP already gets them right.

This design keeps the grid DP as the primary solver for the whole
horizon (unchanged, same latency as today), and only invokes an exact
solve for the narrow set of periods where the DP's own decision margin
is small enough that grid-snap noise could plausibly have flipped it.
The exact solver used is the **exact-PWL DP** already prototyped on the
#461 branch (continuous-SOE piecewise-linear value function, proven
exact to ~1e-10 against the true optimum) rather than the MILP — it's
backward induction, the same paradigm as the grid DP, so it does not
carry the MILP's constraint-encoding risk class. It was rejected as the
*full-horizon* replacement for being too slow (3.2s/78 periods, 37s/192
periods vs the grid DP's 0.04s), but over a small window (a handful of
periods) that cost is expected to be negligible.

## Architecture

```
optimize_battery_schedule()
   │
   ├─▶ 1. Grid DP backward induction  (dp_battery_algorithm.py, unchanged)
   │      → full schedule + per-period (best_cost, runner_up_cost) margins
   │
   ├─▶ 2. Tie Detector                (new, small, pure function)
   │      margins → list of ambiguous periods → grouped into windows
   │
   ├─▶ 3. Window Resolver             (new, wraps exact-PWL DP)
   │      for each window: solve exactly with SOE(window_start), SOE(window_end)
   │      from the grid DP's own trajectory as fixed boundary conditions
   │
   └─▶ 4. Splicer                     (new, small)
          replace window periods' actions in the schedule,
          replay through existing _compute_reward/_build_period_data
```

The grid DP remains the primary solver for the entire horizon, exactly
as today. It surfaces one additional piece of information it already
computes as a side effect of picking the best action per period (the
margin to the runner-up). Everything downstream is new, small, and can
be modified or removed without touching DP internals — each unit has one
clear purpose and is independently testable.

**Common case (no ties detected)**: the schedule returned is byte-for-byte
what the grid DP alone would produce today — same latency, same code path,
zero behavior change. This is expected to be the large majority of solves.

## Components

**1. Margin recorder** (small addition inside the existing DP backward
induction). At each period/state, alongside picking the minimum-cost
action, also retain the second-lowest cost. Output: `tie_margins`, a
per-period array of `best_cost - runner_up_cost` along the DP's actual
chosen trajectory. No new concepts or state beyond a number the DP
already computes and currently discards.

**2. Tie Detector** — `detect_tie_windows(tie_margins, epsilon) -> list[Window]`.
Pure function, no DP or PWL dependency. Flags periods where
`margin < epsilon`; groups flagged periods that are adjacent or close
(within a small gap) into a single window; pads each window by a few
periods on each side so the exact solve has enough runway to genuinely
resolve the ambiguity rather than being boxed in at the edge. Overlapping
windows (after padding) are merged rather than resolved twice.

`epsilon` is derived from `SOE_STEP_KWH` and price granularity — the
actual mechanical source of #450's noise — rather than an arbitrary SEK
figure, so the threshold is principled and not hand-tuned. The exact
derivation is an implementation-time task (see Open Questions).

**3. Window Resolver** — wraps the existing exact-PWL DP prototype. For
each window, solves the sub-horizon's prices/solar/load with SOE at the
window's start and end pinned (equality constraints) to whatever the grid
DP already chose at those boundary periods, so the window reconnects
cleanly to the untouched schedule on both sides. Returns exact-optimal
actions for just those periods. Windows are independent of each other and
can resolve in parallel.

**4. Splicer**. Replaces the grid DP's actions for each window's periods
with the Window Resolver's actions; leaves all other periods untouched;
replays the full spliced action sequence through the existing
`_compute_reward`/`_build_period_data` machinery — the same reuse pattern
PR #461 established for MILP, so cost basis (FIFO), wear cost, AC-flow,
and self-throttle accounting stay in one validated place regardless of
which solver chose a given period's action.

## Error handling

Per this project's no-silent-fallbacks rule:

- If the Window Resolver's PWL solve is infeasible given the DP's pinned
  boundary SOEs (an added constraint not present in the original
  problem — shouldn't happen with adequate padding, but is a real edge
  case), raise loudly. Do not silently fall back to the grid DP's
  original (potentially wrong) choice for that window.
- Overlapping windows are merged before resolution, never resolved twice
  with potentially conflicting boundary pins.

## Testing

- **Margin recorder**: unit test with a synthetic price series containing
  a deliberately-engineered near-tie; confirm the recorded margin at that
  period is small and correctly reflects the real cost gap between the
  DP's chosen action and the runner-up.
- **Tie Detector**: pure-function tests — no ties → empty window list;
  isolated tie → single padded window; two ties close together → merged
  into one window; two ties far apart → two separate windows.
- **Window Resolver**: standalone tests with pinned boundary SOEs at known
  values, confirming reproduction of the true optimum inside the window
  (same exactness check already established for the PWL prototype at
  full-horizon scale).
- **Splicer + end-to-end**: reuse `test_scenarios.py` as the regression
  backbone. #450's own reproduction fixture
  (`regression_2026_08_02_043728.json`) becomes the canonical end-to-end
  regression test: the grid DP alone must still pick the wrong
  (grid-snap-induced) window at that period, the Tie Detector must flag
  it, and the spliced result must match the Bellman-optimal schedule —
  proving the fix works through the real pipeline, not just at the
  PWL-solver level in isolation.
- **No-regression check**: full fixture suite must show zero cost change
  on fixtures where no ties are detected — the fast path must be
  provably identical to today's DP output.
- **Performance**: confirm no-tie solves keep the DP's existing ~12s
  slow-suite time; measure the added latency on fixtures that do trip
  the tie detector, to characterize the actual (expected small) cost.

## Open questions (for implementation phase)

- Exact derivation formula for `epsilon` from `SOE_STEP_KWH` and price
  granularity.
- Window padding size (number of periods on each side of a flagged tie)
  — needs empirical tuning against real fixtures once implemented.
- Whether the exact-PWL DP prototype (built against full-horizon
  semantics) needs adaptation to accept pinned start/end SOE boundary
  conditions, or already supports this.
- Whether the PWL prototype currently covers all of the grid DP's flow
  modeling (self-throttle export credit, AC-cap clipping, per-period
  charge caps) needed inside an arbitrary mid-schedule window, or needs
  extension — these were exercised as full-horizon features on the DP
  side; confirm they compose correctly over an arbitrary sub-window.

## Explicitly out of scope

- Real-time / receding-horizon closed-loop re-optimization. This design
  is scoped to fixing #450 correctly with minimal blast radius; moving
  toward more frequent re-optimization is a separate, larger
  architectural direction to be designed later.
- The MILP core (`milp_battery_algorithm.py`) built on the #461 branch.
  This design does not reuse it; PR #461 should be closed or reworked in
  favor of this approach.
