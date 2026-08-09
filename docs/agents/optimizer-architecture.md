# Optimizer Target Architecture — Normative

**Status: normative.** Every change to `core/bess/dp_battery_algorithm.py`,
`core/bess/pwl_window_dp.py`, `core/bess/tie_detection.py`,
`core/bess/models.py` (flow derivation), `core/bess/strategic_intent.py`,
or `core/bess/simulation/` must either uphold the principles below or amend
this document in the same PR, with the reason. "It was the fastest fix for
the symptom" is not an amendment reason — that is the failure mode this
document exists to end.

## Why this document exists

Between 2026-06 and 2026-08 the optimizer accumulated **ten** hand-written
correction layers between the raw Bellman argmax and the emitted action
(#240, #269, #313, #282, #429, #450, #459, #466, #467, #510). Each was
individually correct, reviewed, and regression-pinned — and each manufactured
the conditions for the next. An independent architecture assessment
(2026-08-08) found the recurring-issue treadmill is structural, driven by
three defect classes, not by implementation sloppiness. The principles below
close those classes; the migration order is in
`docs/superpowers/plans/2026-08-09-optimizer-target-architecture.md`.

The three defect classes, with their issue lineage:

| Class | Mechanism | Issues it produced |
|---|---|---|
| **1. Plan/policy mismatch** | DP optimizes point-forecast energy *quantities*; the inverter executes reactive *policies* (load-tracking modes absorb forecast error, IDLE locks it out). The asymmetry is invisible to an expected-value argmax. | #466, #418, #393, #485, part of #352 |
| **2. Plan/actuation mismatch** | DP plans flows → intent is classified from flows → command derived from intent. Every seam in that chain (percent lattice, grid_first rate semantics, the #350 noise fold running on planned flows) leaks money between plan and execution. | #320, #352, #497/#511, #354, the PLAN_EXECUTION_GAP pins |
| **3. Solver numerics** | Grid-snapped V + argmax-on-float-noise over a plateau-riddled objective; reward shaping (#240, #269) manufactures new plateaus; each pathological pick ships a bespoke tie-break. | #450, #459, #466, #510, #512, #513 |

The user-facing formulation of Class 1, owed to ridax67 (#466), is the
design principle for intent semantics:

> **IDLE must express that the optimizer WANTS to hold energy (a decisive
> margin), never that it merely EXPECTS balance (a coin flip).**

## Principles

### P1. One selector

There is exactly **one** implementation of candidate **enumeration** and
**tie policy**, parameterized by a continuation-value evaluator
`eval_V(next_soe) -> float`. The grid forward replay, the PWL backward
induction, and the PWL forward replay call it directly. The grid backward
induction's numpy-vectorized hot loop may keep its own evaluator for
speed, provided it (a) consumes the same enumeration functions and
(b) is pinned bit-parity against the selector by a standing test — a
vectorized evaluator that drifts from the selector is the #236 bug
reproduced.

Forbidden: adding a candidate type, guard, cap, or preference to one call
site and mirroring it by hand into the others. The concrete targets are
the two hand-cloned enumerate/select functions —
`_best_action_at_continuous_state` (~213 lines) vs
`_pwl_best_action_at_continuous_state` (~221 lines), whose parity is
maintained only by "mirror" comments (`pwl_window_dp.py:164,442,458,912`).
The shared helpers (`_discharge_candidates`, `_charge_candidate`,
`_prefer_*`, `_tie_margin`) are already imported by PWL rather than
cloned; the clone problem is precisely the enumerate/select pair. (The
`_compute_reward`/`_compute_reward_grid` "branch for branch" pair at
`dp_battery_algorithm.py:447` is the physics core — protected below, not
a P1 target.)

### P2. Ties resolve through one lexicographic preference table

All near-tie resolution (within the single epsilon definition, P5) happens
in **one ordered preference table**, applied once, inside the P1 selector.
The baseline order, subsuming the #466 and #510 tie-breaks:

1. Never prefer a candidate that imports more grid energy than the argmax
   winner.
2. Never override a decisive winner (margin > epsilon).
3. Within epsilon: **load-tracking discharge (up to net load) >
   store-surplus > idle/hold.**

Consequences, by construction:

- IDLE is only ever emitted on a decisive margin — it always means a
  deliberate hold (arbitrage), never a balance coin flip. This covers the
  evening near-ties *and* the sunrise/sunset crossover cases from #466.
- A new tie symptom is fixed by **adding or reordering a table row** — with
  its rationale and economic bound in the row's docstring — never by adding
  a new `_prefer_*` function or a new call site.
- Epsilon-compounding is impossible: the table is applied once against the
  argmax value, not chained.

Reward shaping that flattens the objective (price floors, export-credit
zeroing) MUST land together with the table row that resolves the
indifference region it creates (generalizes the #269/#510 invariant in
`bess-knowledge.md`).

### P3. Candidates are executable commands

Every candidate the selector considers corresponds to a command the target
inverter can actually execute — mode (load_first / grid_first /
battery_first / grid-charge), rate on the hardware's actual lattice, and
the mode's **reactive semantics** (a load-first discharge cap tracks real
load; it is not a fixed energy quantity). Candidate value is computed by
simulating that command's response to the forecast.

Consequences:

- R == P (realized equals planned) becomes a structural property, not a
  test-suite achievement. The plan cannot propose what the hardware cannot
  execute (#320, #352, #497/#511, #354).
- Strategic intent becomes an **input** (the chosen command) rather than a
  label re-derived downstream from flows. `classify_strategic_intent` on
  planned flows is a legacy seam to be removed, not extended.

### P4. One flow record per candidate; noise models live at ingestion only

Each candidate's physical flows are computed **once**, and both the reward
and the reported `EnergyData` derive from that same record. Reward-side
edits that do not propagate to flows (the #497/#459 divergence class) are
forbidden.

Sensor-noise heuristics (e.g. the #350 small-export fold) apply **only** in
the sensor-ingestion path (`sensor_collector.py`). Planned and simulated
flows are exact by definition and must never pass through a noise model.

### P5. One epsilon, one owner

The tie/noise threshold is defined in exactly one place
(`tie_detection.epsilon_for_period`) and consumed everywhere ties are
compared — the preference table, tie-window detection, hysteresis (#485).
No caller re-derives or hand-picks a SEK margin.

### P6. Exactness claims are certified or bounded

A solver output spliced over another solver's output (the #450 PWL path)
must either carry a certification the machinery actually earns, or an
explicit error bound. #513 (PWL mis-ranks a plan by 0.584 SEK while
"exact") is the standing counterexample.

**Current state (aspirational until the Phase 2 rider lands):**
`splice_schedule` today splices unconditionally — the only guard is the
certification raise (`PWLWindowUnderRefinedError`), and #513 proves
certification does not imply correct ranking. "Treated as heuristic"
becomes a code property via the splice cost-gate (migration plan, Phase 2
rider): a re-solved window is accepted only if its replayed cost is no
worse than the grid segment it replaces. Until that gate exists, any NEW
reliance on PWL exactness is forbidden; the existing splice path is
grandfathered, gate pending.

### P7. Point forecasts stay; risk handling is structural, not stochastic

The DP remains deterministic over point forecasts. Forecast-error
robustness is obtained structurally — the P2 preference for load-tracking
modes, and honest inputs (#487) — not by adding per-period uncertainty
models, variance heuristics, or scenario trees. That machinery may only be
introduced if tie-resolved-to-tracking demonstrably still misses in the
field, with the field evidence in the amending PR.

## What this document does NOT change

- The physics core (`_compute_reward`, `_state_transition`, `_ac_flows`)
  and its vectorized mirrors: correct, bit-parity-tested, refactor *around*
  it. (P1/P4 change who calls it and how results are bookkept, not the
  math.)
- The fixture/regression harness, debug-bundle-to-fixture pipeline, and
  R==P plan-faithfulness corpus: the acceptance mechanism for every
  migration phase.
- Explicit-failure discipline (`rules.md`): raises stay raises.
- The inline issue-citation documentation style.

## Compliance check (for reviewers and CI-stage review prompts)

A PR touching the files in the header fails review if it:

1. Adds a `_prefer_*`-style function or a second tie-resolution site (P2).
2. Edits candidate logic in one of the grid/PWL paths without going through
   the shared selector — or, before Phase 1 lands, without mirroring AND
   stating the mirror in the PR body (P1).
3. Introduces reward-only or flows-only accounting for the same physical
   action (P4).
4. Applies a sensor-noise heuristic to planned or simulated flows (P4).
5. Hand-picks a SEK tie margin instead of consuming `epsilon_for_period`
   (P5).
6. Adds reward shaping that flattens the objective without the matching
   preference-table row (P2).
7. Adds per-period uncertainty modeling without field evidence (P7).
