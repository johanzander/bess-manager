# Optimizer Target Architecture — Normative

**Status: normative.** Every change to `core/bess/action_selector.py`,
`core/bess/tie_policy.py`, `core/bess/dp_battery_algorithm.py`,
`core/bess/pwl_window_dp.py`, `core/bess/execution_model.py`,
`core/bess/tie_detection.py`,
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
site and mirroring it by hand into the others.

**Status: satisfied for the forward replays as of Phase 1.** Candidate
enumeration and tie policy now live once, in
`core/bess/action_selector.py`; both forward replays call
`select_action`. The two hand-cloned enumerate/select functions this
principle was written against —
`_best_action_at_continuous_state` and
`_pwl_best_action_at_continuous_state`, whose parity used to be
maintained only by "mirror" comments — are gone. What P1 now guards is
re-divergence: adding a candidate type, guard, cap, or preference
anywhere other than `action_selector.py`.

Standing exemption: the two vectorized backward passes
(`_run_dynamic_programming`, `_pwl_candidate_values_at`) keep their own
numpy evaluators — routing them through `select_action` measured ~256x
slower AND would change behavior (the backward pass deliberately
estimates V over the coarse power lattice and deliberately does not apply
`_discharge_is_unexecutable`). They import the candidate-space
definitions rather than holding them, and
`core/bess/tests/unit/test_vectorized_backward_parity.py` pins the two
ways they can silently drift: scalar-vs-grid transition/reward bit-parity,
and that the backward pass values every off-lattice candidate type the
selector can choose. Removing that test re-opens the #236 bug class.

(The `_compute_reward`/`_compute_reward_grid` "branch for branch" pair is
the physics core — protected below, not a P1 target.)

### P2. Ties resolve through one lexicographic preference table

All near-tie resolution happens in **one ordered preference table**, applied
once, inside the P1 selector. Eligibility for it is set by the single
epsilon definition (P5) and nothing else; the one narrower, non-economic
band used *within* an eligible set is bounded in P5.
The baseline order, subsuming the #466 and #510 tie-breaks:

1. Never prefer a candidate that imports more grid energy than the argmax
   winner.
2. Never override a decisive winner (margin > epsilon).
3. Within epsilon: **load-tracking discharge (up to net load) >
   store-surplus > idle/hold.**
4. Within *float noise* (values indistinguishable to 1e-12), and only where
   no row above fired: **the most decisive action of the winner's own class**
   (largest magnitude), then lowest candidate index (#606).

Consequences, by construction:

- IDLE is only ever emitted on a decisive margin — it always means a
  deliberate hold (arbitrage), never a balance coin flip. This covers the
  evening near-ties *and* the sunrise/sunset crossover cases from #466.
- A new tie symptom is fixed by **adding or reordering a table row** — with
  its rationale and economic bound in the row's docstring — never by adding
  a new `_prefer_*` function or a new call site.
- Epsilon-compounding is impossible: the table is applied once against the
  argmax value, not chained.
- **The emitted plan never depends on the last bit of a float.** Before #606
  the table's final row was "the argmax winner stands", which is not a
  preference at all but a deferral to a `>` comparison, and a structural
  plateau (bit-identical consecutive periods inside one price block, all
  unconstrained) made two candidates tie to 0.93 ULP. The plan then differed
  by *interpreter*: measured on `regression_2026_08_13_145213`, period 18 was
  -1.1625 kW on py3.12.13 and -0.6875 kW on py3.13, at bit-identical cost.
  Item 4 above closes that (it is row 5 in `tie_policy.py`'s own numbering,
  which counts the two eligibility rows separately): an exactly-tied choice
  is resolved by a stated order over actions, never by the value's noise. A
  reward-shaping change
  that creates a *plateau* now needs this row the way one that creates an
  *indifference region* needs a within-epsilon row.

Reward shaping that flattens the objective (price floors, export-credit
zeroing) MUST land together with the table row that resolves the
indifference region it creates (generalizes the #269/#510 invariant in
`bess-knowledge.md`).

**Status: satisfied as of Phase 2.** The table lives in
`core/bess/tie_policy.py` and is applied once, from
`action_selector.select_action`. The two bespoke tie-break helpers this
principle was written against are gone; a repo-wide grep for `_prefer_`
over the source tree returns nothing, which is the standing exit gate.
(The migration plan under `docs/superpowers/plans/` still names them,
describing the code it retired.)

Three things the baseline order above states loosely, as built:

- Row 2 is **per-preference, not shared**. The load-cover row stands down
  on a charge winner and on a discharge already past the cover, but keeps
  a *partial*-cover winner eligible (#512). The curtailment row stands
  down on a discharge winner and may still improve a charge winner. A
  single shared non-idle guard cannot express that asymmetry and would
  re-open the hole #512 closed.
- "Within epsilon" is measured against the argmax winner for every row,
  and the band is **inclusive**, so the table is live at `epsilon == 0`
  where both retired helpers returned early. At epsilon 0 that admits only
  bit-exact ties. **No epsilon floor exists**, and one may only be
  introduced with a per-period forfeiture bound in the row docstring,
  counted against the 0.05 SEK/fixture budget: measured across the whole
  fixture corpus, the smallest gap the table declines to cross at
  epsilon 0 is 0.0080 SEK — a real ranking, not value noise.
- The sunrise/sunset crossover is **not** covered by this principle. #517
  established the action set there was empty, not tied, and fixed it with
  a candidate (P3). Crossover regression cover belongs in Phase 4.

### P3. Candidates are executable commands

Every candidate the selector considers corresponds to a command the target
inverter can actually execute — mode (load_first / grid_first /
battery_first / grid-charge), rate on the hardware's actual lattice, and
the mode's **reactive semantics** (a load-first discharge cap tracks real
load; it is not a fixed energy quantity). Candidate value is computed by
simulating that command's response to the forecast.

**As built, Phase 4a (partial).** The platform half exists:
`core/bess/execution_model.py` is a leaf module holding
`PlatformCapabilities` — the discharge lattice, the mode vocabulary, the
minimum commandable gear, and whether a discharge rate is a **ceiling**, a
**target**, or **absent** — plus `intra_period_discharge_gate`, relocated
out of `battery_system_manager` so the selector and
`simulation/inverter_simulator` share one execution model without the
optimizer importing the orchestrator. `BatterySystemManager` builds the
object from the live controller and passes it to
`optimize_battery_schedule`, which threads it to the candidate space in
place of the old `discharge_resolution_kw` kwarg. The first thing the
capability buys: the off-lattice residual-cover candidate is now offered
only where a planned LOAD_SUPPORT discharge is actually delivered as
`min(plan, actual load)` (#580).

**As built, Phase 4b (discharge half).** A discharge candidate is now scored
against what its command actually delivers, not against its nominal power.
`_residual_cover_p` offers exact load cover **wherever the lattice cannot
represent covering the deficit** — not only below the smallest gear, which
was the #466 sunrise case — because the same gap exists at any size: the
step below under-covers and imports at the buy price, every step above is
either unexecutable (#497) or exports at the sell price, and with buy > sell
that is a forced loss either way. The plan is the *delivery* under a ceiling
command; the command stays on the hardware lattice.

That only holds if the written ceiling covers the plan, so the
planned-power → written-percent conversion is now one function,
`execution_model.discharge_command_index`, rounding by what the number
**means**: up for a ceiling (`load_first` where the rate load-follows),
nearest for a target (`grid_first` anywhere, native SolaX). The controller,
the simulator's mirror and the planner's own executability gate all call it,
so they cannot round apart — the #282/#497 shape. Rounding up is the
*tightest admissible* ceiling, not a free one: it leaves up to one lattice
step of headroom the battery will use if actual load exceeds forecast,
including where the intra-period gate is deliberately closed. No rounding
both delivers the plan and never exceeds it, because the lattice is coarser
than the deficit.

**As built, Phase 4c (charge half, narrow).** The charge command now rounds
**up** through the same `command_index` the discharge side uses (renamed from
`discharge_command_index`, since both paths share it). The justification is
the mirror of the discharge one but rests on different physics: a discharge
ceiling is safe to round up because actual house load binds below it, while a
charge command is bounded from above only by the battery's own remaining
room — the inverter stops when full — so a rate above the plan still delivers
exactly the plan. Measured: 4 of 493 charging periods were short (worst
−0.0288 kWh); now none. Plan-neutral, +0.00000 SEK, no golden churn.

Where `import_cap_kwh` limited the plan (#429) that argument fails — nothing
physical binds above the command and rounding up would exceed the house fuse
— so there the DP floors the plan onto the lattice instead
(`execution_model.lattice_grid_charge`). Under-drawing never violates a fuse,
so the safe direction differs per binding constraint; do not unify them.

**Still open on the charge side.** `charging_power_rate` was never the
problem — it does not reach the inverter as a plan-limiting rate (see the
plan's correction of 2026-08-16). What remains is real but unmeasured in
money: `_period_flows` derives charge throughput from `max_charge_power_kw`
rather than from the commanded rate, and the DP and the inverter simulator
share that record under P4 — so the simulator reproduces the plan by
construction and **cannot disagree with it about charge**. Any charge-side
R==P result is therefore weaker evidence than the discharge-side equivalent.
Candidates are commands on the discharge side; on the charge side only the
written rate is.

**Two questions, not one — do not collapse them.** "Is the rate register a
ceiling" (`discharge_rate_is_load_following`, what the intra-period gate
needs, since it writes a rate) and "is a load-support discharge delivered
load-following" (`load_support_delivers_exact_cover`, what the cover
candidate needs) have different answers on solax-modbus Growatt in VPP
mode: the register is a forced power, but #413 makes LOAD_SUPPORT write no
rate at all and release the period to the inverter's own self-use. Each is
declared per controller and read through `PlatformCapabilities`; a caller
reading either fact off a controller directly is the drift this phase
removed.

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

The **economic** tie/noise threshold is defined in exactly one place
(`tie_detection.epsilon_for_period`) and consumed everywhere ties are
compared — the preference table, tie-window detection, hysteresis (#485).
No caller re-derives or hand-picks a SEK margin.

**The one narrow exception, and its boundary (#606).** Exactly one other
band exists: `tie_policy.VALUE_INDISTINGUISHABLE_SEK`. It is not a second
epsilon and must never be used as one — it decides nothing about
*eligibility*, which remains epsilon's sole property. It applies strictly
*inside* an already-decided eligible set, to pick a canonical action among
candidates whose values are indistinguishable as IEEE doubles. The
distinction is what it is a statement about: epsilon says "the DP's SOE
grid injects this much value noise, so these options are economically
unrankable" and is derived per period from the value slope;
`VALUE_INDISTINGUISHABLE_SEK` says "these two floats are the same number",
on a quantity whose own accumulated rounding is ~1 ULP (~1e-15 at corpus
magnitudes). Widening it toward epsilon would silently turn it into an
economic preference — measured at 0.006–0.010 SEK per fixture across the
corpus — so it is fixed at 1e-12 and any change to it needs the same
measured-delta treatment a new table row does.

This exception exists because a plateau can be *exact* rather than merely
narrow: bit-identical consecutive periods make the objective exactly
invariant to how a fixed total splits across them, so no economic margin,
however small, can rank them and the choice would otherwise fall to float
ordering. No further exception may be added without amending this section.

**The second exception, and its boundary (#602).**
`dp_constants.SHADOW_PRICE_NOISE_REL` bands the discharge gate's comparison
of a buy price against a shadow price. It is amended in rather than added
silently, per the paragraph above.

Unlike `VALUE_INDISTINGUISHABLE_SEK` this one *does* decide an eligibility
— which is why it needs stating here rather than hiding behind the existing
carve-out. What makes it admissible is that it decides eligibility against
**differencing noise**, not against an economic margin. `shadow_price` is a
finite difference of the value function, so it carries V's accumulated
rounding divided by the SoE step; the band is that bound with headroom
(1e-12 relative), eight orders of magnitude below the ~1e-4 SEK/kWh
smallest real price difference in any observed market. It cannot change a
decision that any market could express.

It is *relative* where the other two are absolute, because it bands a
quantity whose own noise scales with its magnitude — shadow prices run from
~0.1 to ~2.6 SEK/kWh across the corpus.

The gate's tie direction is stated, not left to the comparison: **at
indifference the gate opens.** That follows P2 row 3 (load-tracking
discharge is preferred within a tie) and P7 (a load-following cover absorbs
forecast error where an import does not), so it is the same preference the
rest of this document already asserts, applied at the one place that
compares a price against a slope.

Why it became necessary: the #602 concave terminal row gives V a constant
slope over the head segment equal to `median(buy_prices)`, and a median is
by construction an element of the array it is taken over. Every period
whose buy price attains the horizon median therefore ties against its own
shadow price to the last bits — deterministically, not occasionally.
Measured on `realworld_2026_04_22_202249` period 85: buy 2.60425 against
shadow 2.60425000000005. The pre-#602 formula escaped this only by
accident, because subtracting `cycle_cost` detuned the rate off the price
array.

A PR widening this band, making it absolute, reusing it outside the
shadow-price comparison, or adding a fourth band fails the compliance
check below.

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

**Window size is the caller's problem, not the solver's (#624).**
`detect_tie_windows` merges adjacent flagged periods with no cap, while the
solver's breakpoint set compounds per backward step — so the merged length
is an unbounded function of the price curve while the exactly-solvable
horizon is ~8 periods, and no budget raise extends it. Step 2b closes that
gap by bisecting a window that raises `PWLWindowUnderRefinedError` and
re-solving each half, terminating at horizon 1 (four breakpoints from the
pinned terminal row, three orders of magnitude under budget). This does not
relax P6 and is not the cost-gate: every spliced half carries the same
certification a whole window would have. It is the one exception that may be
caught, and only to re-size the work — catching it to keep the grid DP's
result, or to splice the uncertified table, remains forbidden.

**A budget that is not denominated in what it spends is not a budget (#697).**
The paragraph above used to say the exactly-solvable horizon is ~8 periods.
That was wrong about the binding constraint, and the error was expensive: the
real limit was transient memory in the objective evaluation, and it bit at
*five* periods — measured 1.1 GB RSS on the corpus's own bisected half —
inside the range the doc treated as safe. `_pwl_candidate_values_at` built a
dense `|X| × |actions|` matrix in one allocation, `|actions|` is ~102 for every
battery (the discharge lattice is `max_discharge_power_kw / 100`, so hardware
size does not enter), and the two budgets that existed both looked at the
wrong thing: `PWL_MAX_PREIMAGE_SEED_POINTS` counted seed *abscissae* (8 MB)
rather than the ~10 GB of evaluation they imply, and `PWL_MAX_BREAKPOINTS` was
checked *after* the evaluation it bounds and against the *pruned* row, an
order of magnitude smaller than what had just been allocated. So the kernel
OOM-killed the add-on instead, eleven times, and Supervisor's backoff turned a
deterministic solver bug into a 38-hour outage.

Two rules follow, and they are general, not incidental to this bug:

- **Bound the resource where it is actually spent, in its own units.** The
  objective is evaluated in fixed-size row blocks (`PWL_EVAL_BLOCK_CELLS`), so
  peak memory is independent of `|X|`. Blocking is exact — every reduction is
  over the action axis, so rows are independent and the blocked result is
  bitwise identical — which is why this bounds cost without touching P6.
- **A ceiling checked after the allocation it bounds is not a ceiling.**
  `PWL_MAX_EVAL_CELLS` is checked before the evaluation, in cells, and raising
  it feeds the bisection above like any other budget.

Note the failure mode this leaves closed: an optimizer that exceeds a budget
raises and gets re-sized, but an optimizer that is SIGKILLed cannot raise at
all, so **no in-process safety net can cover unbounded allocation**. The DP
shares the uvicorn process with the control loop, so bounding the allocation
is the only thing standing between a solver pathology and the battery going
unmanaged. Isolating the optimizer so that exhaustion surfaces as a catchable
`MemoryError` is tracked separately (#698).

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
   (P5). Two exceptions are permitted, both bounded in P5:
   `tie_policy.VALUE_INDISTINGUISHABLE_SEK`, which decides no eligibility
   and applies only within an eligible set already fixed by epsilon; and
   `dp_constants.SHADOW_PRICE_NOISE_REL`, which bands the discharge gate
   against value-function differencing noise and nothing else. A PR
   widening either, reusing them elsewhere, or adding a fourth band fails
   this check.
6. Adds reward shaping that flattens the objective without the matching
   preference-table row (P2). The #602 terminal row flattens V over its
   head segment; its matching statement is P5's stated gate direction
   (at indifference the gate opens), not a new table row, because the
   plateau it creates is compared against a *price* outside the selector
   rather than against another candidate inside it.
7. Adds per-period uncertainty modeling without field evidence (P7).
