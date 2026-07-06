# Design: Remove ad hoc DP guardrails in favor of pure backward induction

**Date**: 2026-07-06
**Status**: Approved
**Related**: #234 (dead cost-basis threading), #236 (DP hot-loop perf), #240
(flow model miscredits load-following overshoot as export)

## Problem

The DP optimizer (`core/bess/dp_battery_algorithm.py`) layers three ad hoc
guardrails on top of its backward induction:

1. A per-action `cost_basis` profitability floor in `_compute_reward`'s
   discharge branch (`effective_cost_basis`, plus a `sell_price > buy_price` /
   `excess_solar` anti-cycling special case) that vetoes a discharge outright
   (`return float("-inf")`) if its value doesn't clear a blended historical
   average cost.
2. A whole-day `min_action_profit_threshold` rejection gate in
   `optimize_battery_schedule`: if the DP's own schedule doesn't beat a
   solar-only baseline by enough, discard it and fall back to an all-IDLE
   schedule.
3. A `C` cost-basis-threading grid inside `_run_dynamic_programming` meant to
   carry the true path-dependent cost basis backward through the recursion —
   #234 found this is dead code (a loop-order bug means it's never read back),
   so the floor above is fed a frozen `initial_cost_basis` for the entire
   backward pass regardless.

`docs/agents/bess-knowledge.md` ("The Governing Economic Law") already
documents the *intended* design: a stored kWh's opportunity cost is its
forward-looking `shadow_price` (the DP's own value-to-go slope), not the sunk
`cost_basis` — and even notes the code's floor doesn't match that documented
law. That mismatch was never reconciled.

## Why none of these guardrails are needed

In a correctly specified finite-horizon MDP — one-step reward capturing real
cash flows (grid import cost, export revenue, charging wear cost) and `IDLE`
always a feasible action — backward induction is optimal by construction
(Bellman's principle of optimality). At every `(t, i)`, `IDLE`'s value
(`0 reward + V[t+1, i]`) is evaluated alongside every other action, so the
recursion can never recommend something worse than doing nothing: if
discharging isn't worthwhile, the `max` simply picks `IDLE` instead. A
separate profitability veto on top of that `max` is therefore either
redundant (the value function would have reached the same conclusion) or
actively harmful (it can block a genuinely optimal action based on a stale or
theoretically wrong quantity — which is exactly what #234 documents: a frozen
`cost_basis` blocking legitimate multi-cycle arbitrage).

### Empirical validation (this session)

Built a prototype DP with all three guardrails removed and the one-step
reward otherwise unchanged (real cash flows: grid import/export at that
period's price, charging wear cost via `cycle_cost_per_kwh`, discharge
priced at actual cash flow with no veto). Ran it against all 26 pinned
fixtures in `core/bess/tests/unit/data/`:

- **25/26 fixtures: matched or beat the current production algorithm**
  (improvements from a few cents to ~$58 — realistic magnitudes, not runaway
  arbitrage).
- **1/26 fixture regressed** by 0.27 SEK (~0.1% of total daily cost) against
  both current and an all-IDLE baseline.

An earlier draft of this experiment showed *much* larger "improvements"
(hundreds of SEK, 5-7 effective cycles/day) — traced to a bug in the
prototype's charge-branch accounting (it under-priced the true binary-rate
grid cost of charging while still correctly charging wear cost, manufacturing
free arbitrage). Once fixed to use the actual STORE-physics-consistent cost
accounting (matching `_compute_reward`'s existing charge/idle branches
exactly), cycling frequency came back in line with the current algorithm.
**This confirms the linear `cycle_cost_per_kwh` wear model, correctly priced,
already fully disciplines cycling frequency — no separate frequency-aware
wear-cost redesign is needed.**

### The one remaining regression, root-caused

Verified the prototype's all-IDLE replay cost matches
`dpa._create_idle_schedule`'s cost exactly (282.7890 both ways) for the
regressed fixture — so it isn't a reward-function mismatch between the two
paths. Tracing the chosen actions: a discharge lands the continuous SoE at
8.068 kWh, off the `SOE_STEP_KWH = 0.1` grid; the next period's policy lookup
snaps to the nearest grid point (8.1) instead of the true continuous value —
a ~0.03 kWh drift, compounding into the observed 0.27 SEK gap. This is a
pre-existing property of how `optimize_battery_schedule`'s Step 2 already
reconstructs a continuous path from the discretized policy — not something
this redesign introduces.

Also verified #240's fix does **not** explain this regression: the four
discharges in the regressed schedule are all smaller than that period's
`home_consumption`, so there's no overshoot for #240's flow-misattribution to
apply to. Applying the #240 fix to this fixture produces byte-identical
actions and cost.

**Tried to close the gap fully**: replaced the Step-2 replay's "snap SoE to
nearest grid index, trust that cell's stored policy" with a one-step
recompute at the true continuous SoE, using the already-known `V[t+1, :]`
(linearly interpolated) as the continuation value — same reward+max(V) logic
as the backward pass, just applied at the true state instead of a snapped
one. This reduced the regression (0.27 → 0.16 SEK, ~40%) but did not
eliminate it, and introduced no regressions elsewhere across the other 25
fixtures. A full elimination would need finer SoE/power discretization or a
continuous-action reformulation — out of scope here.

**Conclusion**: include the interpolated-V replay recompute (small, clearly
justified, no new risk) *and* keep a trivial numerical safety net — compare
the DP's own output cost against all-IDLE, take whichever is cheaper. The
safety net now guards a smaller residual (~0.16 SEK, ~0.06% of daily cost)
than the original whole-day threshold gate did, but it isn't provably zero
without it, so it stays. This is a different, much narrower justification
than the current whole-day threshold gate: pure numerical insurance against
discretization noise, not an economic trust mechanism.

## Design

### Removed

- `_compute_reward`'s discharge-branch profitability floor: `effective_cost_basis`,
  the `sell_price > buy_price` / `excess_solar` anti-cycling special case, and
  the `-inf` veto. Discharge reward becomes a direct cash-flow computation
  with no veto — `IDLE` competing in the same `max` is the only arbiter.
- The whole-day `min_action_profit_threshold` rejection gate in
  `optimize_battery_schedule` and `THRESHOLD_HORIZON_FLOOR`. The algorithm
  stops reading/using `min_action_profit_threshold` entirely as part of this
  PR. The `BatterySettings` field and the add-on's `config.yaml` schema entry
  are **left in place but unused** for now — removing them is a separate,
  user-facing config-schema change (existing installs have this value set)
  with its own migration path, tracked as a **separate follow-up issue**, not
  bundled here.
- The dead `C` cost-basis-threading grid in `_run_dynamic_programming` (moot
  once nothing reads it as a floor input).

### Added

- A trivial post-hoc comparison in `optimize_battery_schedule`: compute the
  DP's schedule cost and the all-IDLE schedule cost, return whichever is
  cheaper. O(1) comparison, not a configurable threshold.
- Step 2's continuous-path reconstruction changes from "snap SoE to nearest
  grid index, use that cell's stored policy" to a one-step recompute at the
  true continuous SoE using interpolated `V[t+1, :]` as the continuation
  value. Reduces (but does not eliminate — verified empirically) the
  discretization residual the safety net above guards against.
- The #240 fix in the discharge branch's flow accounting: if the naively
  computed `grid_exported` for a discharge is `<= 0.1 kWh` (reusing the same
  threshold `decision_intelligence.classify_strategic_intent` already uses to
  call something `BATTERY_EXPORT` vs `LOAD_SUPPORT`), treat it as
  self-throttled load-following — zero export credit, since load-first
  hardware never actually exports it.

### Kept unchanged

- `cost_basis` FIFO tracking and reporting (debug bundle, UI) — still
  computed via the existing forward-replay logic; simply no longer used as a
  gate anywhere.
- `shadow_price` reporting — unchanged.
- The intra-period `solar_export_discharge_rate` runtime gate in
  `battery_system_manager.py` — a different mechanism (hardware-level,
  sub-15-minute gating using `shadow_price`, applied after the DP has already
  produced its schedule). Out of scope.

## Test impact

- `test_action_threshold.py` (6 tests) — tests `min_action_profit_threshold`
  directly. **Deleted**, since the config option is removed.
- `test_cost_basis_calculation.py` (6 tests) — tests FIFO `cost_basis` math
  itself, which is kept. Expected **unchanged**; verify during
  implementation.
- `test_optimization_algorithm.py` (multi-window cost-basis scenarios,
  ~lines 335-406) — likely needs updated expected actions/costs, since
  removing the floor changes chosen schedules in some cases. Verify each
  changed expectation by hand rather than blindly re-pinning to new output.
- `test_solar_export_discharge_gate.py` (3 tests) — tests the unaffected
  runtime gate. Expected **unchanged**; verify.
- All 26 pinned fixtures in `core/bess/tests/unit/data/`
  (`test_scenarios.py`) — expected costs/actions will differ (mostly flat,
  some modestly better per this session's findings). Regenerate expectations;
  hand-verify every fixture showing a nonzero cost delta rather than accepting
  new output as ground truth by default.
- New tests to add:
  - A regression test asserting the DP-alone schedule is never worse than an
    all-IDLE schedule, across the full fixture set (the property this
    redesign's safety net rests on).
  - A #240-specific test: a discharge that overshoots `home_consumption` by
    less than 0.1 kWh must show zero `grid_exported` credit for the excess.
- `core/bess/tests/integration/test_plan_faithfulness.py` (the `R == P`
  invariant: executing the optimizer's plan through the inverter simulator
  must reproduce the planned economics, per `docs/agents/simulator.md`) —
  these hand-crafted scenarios were deliberately designed to avoid the
  SoE-grid boundary ambiguity ("no fractional solar-storage", per the file's
  own docstrings), so they're expected to keep passing unchanged. But the
  #240 fix changes what the *planned* economics assume for small-overshoot
  discharge — verify during implementation whether `core/bess/simulation/`
  already models load-first self-throttling physically (the debug-bundle
  evidence in #240 suggests real hardware does); if so, this fix should
  *improve* `R == P` alignment for such periods, not break it. Add a new
  plan-faithfulness scenario that deliberately hits the small-overshoot
  boundary to lock this in — it's exactly the case existing scenarios were
  designed to avoid, so nothing currently covers it.
- `bess_manager/config.yaml` and `BatterySettings.min_action_profit_threshold`
  — left in place, unused, per the scope note above; removal is a separate
  follow-up issue with its own config-migration path (existing installs may
  have this value set).

## Rollout

This changes expected output for nearly every pinned fixture, so it ships as
a redesign PR, not a patch — reviewed against the full regression suite
first, then released to the beta channel before stable (existing convention
for changes that are easy to self-validate against fixtures but hard to
validate against real hardware/pricing behavior ahead of time).

## Follow-up issues (not in this PR)

- Remove `min_action_profit_threshold` from `bess_manager/config.yaml`'s HA
  add-on schema and `BatterySettings`, once this PR has shipped and the field
  is confirmed unused. Needs its own migration note for existing installs.
