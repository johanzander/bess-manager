# Optimizer Target Architecture — Migration Plan

> **For agentic workers:** This is a PROGRAM plan: an ordered sequence of
> phases, each of which is a separate PR (or short PR series) executed in
> its own session/worktree. Phases 1–2 are specified to implementation
> level here. Phases 3–4 are specified to acceptance level; their first
> step is to write their own detailed plan (superpowers:writing-plans, or
> `implement-issue` where a phase maps 1:1 to an issue). Do NOT execute
> later phases from this document alone. Steps use checkbox (`- [ ]`)
> syntax for tracking.

**Goal:** Migrate the optimizer to the normative architecture in
`docs/agents/optimizer-architecture.md` (P1–P7), retiring the
ten-correction-layer treadmill: one selector, one preference table, one
flow record, executable-command candidates.

**Architecture:** See `docs/agents/optimizer-architecture.md`. Every phase
must leave the full suite green, the plan-faithfulness corpus pinned, and
ship independently — no phase depends on a later one.

**Tech stack:** Python 3.11, numpy, pytest (`-m "not slow"` fast lane),
canonical scenario harness (`core/bess/tests/unit/test_scenarios.py` +
`data/*.json`), plan-faithfulness corpus
(`core/bess/tests/integration/test_plan_faithfulness.py`), mock-HA E2E
(`verify` skill / `mock-run.sh`).

## Global constraints

- `docs/agents/rules.md` applies in full (no new classes without approval —
  the modules named below count as the approval; explicit failure; no
  fallbacks).
- Every phase: `./scripts/quality-check.sh` green, fast suite green, slow
  suite green (≈1–2 min), plan-faithfulness pins re-verified (re-pinned only
  with the measured value stated in the PR body).
- Bit-parity gates below mean: byte-identical `actions` and
  `soe_trajectory` for every fixture in `core/bess/tests/unit/data/`,
  asserted by a throwaway comparison script committed to the PR branch and
  removed before merge (or kept under `scripts/` if generally useful).
- Branch per phase from `origin/main`; draft PR; `/code-review` before
  ready; CONFIRMED findings are blockers.
- No phase closes a reporter's issue from a beta/intermediate PR — final
  prod release PRs close issues (repo policy).

## Issue map (what each phase retires)

| Phase | Retires / unblocks | Class |
|---|---|---|
| 0 | in-flight WIP: #510, #511 (#497), #506, #507 (#502), #508 (#501), #515, #516 (#512), #517 (#466 crossover) | 2, 3 |
| 1 | the mirrored-selector bug class (#236-shape, `DISCHARGE_LATTICE_PCT_EPS`-shape) | 3 |
| 2 | #466 evening near-ties, #393; makes #485 trivial; subsumes #466/#510 tie-break code (crossover moved to Phase 4 — #517) | 1, 3 |
| 3 | #497 fully, #459-class; formalizes the fold-scoping split | 2 |
| 4 | #320, #352 residual, #354 (parked — right problem, wrong layer), #466 crossover regression cover, #511-class recurrence | 2 |
| parallel | #487 (input quality — independent, any time) | 1 input |
| deferred | #513 (fix when touched; until then P6 treats PWL as heuristic), #512 (SOE-step sweep, gated on its own premise test) | 3 |

---

## Phase 0: Drain the WIP queue (entry criteria, not new work)

No new architecture work starts while overlapping WIP is open — parallel
sessions rediscovering each other's findings is how this program got
confusing.

- [x] Merge PR #510 (merged 2026-08-08, `742d5906`; two optional test nits
      may follow up).
- [x] Flow-coherence pin test (`test_flow_coherence.py`) — already on
      main; it landed as PR #506 on 2026-08-08, before this plan was
      written. Phase 3's acceptance anchor is in place.
- [x] Land `scripts/bench_pwl_everywhere.py` (PR #515, merged
      2026-08-09) — the #512 sweep gate.
- [x] PR #511 (#497 executable-discharge fix) merged 2026-08-09; #497
      closed. Its tests become Phase 4 acceptance tests.
- [x] PRs #507 / #508 (curtailment reporting/UI) merged 2026-08-09.
- [x] Fold-scoping: **premise check FAILED and the design changed as a
      result.** The mock-HA measurement found 130 periods planning small
      (<0.15 kWh) exports, 117 of which derived a `grid_first` command at
      ≤60% rate — squarely inside #352's live failure mode. The −5.51
      SEK/day was simulator accounting: real under perfect 15-minute
      average loads, but live it would have converted spike-robust
      `load_first` periods into forced-rate `grid_first` ones. The #350
      fold had been accidentally shielding users from #352 for that whole
      class. Redesigned as candidate-set materiality at the DP level
      (P3) and shipped as **PR #511** instead; the fold move itself is
      demoted to non-urgent data hygiene for Phase 3.
- [x] Park PR #354 with a Phase 4 pointer. NOT closeable as "already
      fixed": #511 removed sub-material exports from the *plan*, but
      #354's own body flags the **0.1–0.5 kWh home-dominant band** that
      survives it — material exports the DP legitimately plans that still
      commit the inverter to `grid_first` and forfeit load-following
      headroom. #352 stays open for that residual. #354's mechanism is the
      wrong layer (demoting at command-write means the DP already credited
      revenue the mapping forgoes — the P>R optimism P3/P4 forbid), but
      its **two-sided materiality test** is real domain knowledge to carry
      into Phase 4: a near-full-rate export has almost no load-following
      headroom left to protect, so a home-dominance-only rule would
      permanently demote every export on a high-consumption house
      (learned from live E2E, would otherwise be rediscovered the hard
      way).
- [ ] Post the #466 status comment: ridax67's principle ("IDLE = WANTS,
      not EXPECTS") is now P2 of the target architecture, and the
      sunrise/sunset crossover shipped in #517 — written in plain
      language (no shadow price / backward induction / lattice jargon;
      the reporter has said explicitly that vocabulary is not useful to
      him).

## Phase 1: One selector (P1)

**One PR. Pure mechanical extraction — zero behavior change, enforced by
bit-parity.**

**Files:**
- Create: `core/bess/action_selector.py` — the single candidate
  enumeration + evaluation + selection implementation.
- Modify: `core/bess/dp_battery_algorithm.py` — `_run_dynamic_programming`
  (grid backward), `_best_action_at_continuous_state` (grid replay) become
  thin wrappers calling the selector with a grid-interpolating `eval_V`.
- Modify: `core/bess/pwl_window_dp.py` —
  `run_pwl_window_backward_induction`, `_pwl_best_action_at_continuous_state`
  call the same selector with a PWL-row `eval_V`.
- Test: `core/bess/tests/unit/test_action_selector_parity.py`.

**Interfaces (Produces — later phases rely on these exact names):**

```python
# core/bess/action_selector.py

@dataclass(frozen=True)
class Candidate:
    power: float            # kW, signed (+charge / -discharge / 0 idle)
    next_soe: float         # kWh
    reward: float           # this period's reward (currency)
    new_cost_basis: float
    grid_imported: float    # kWh, for the import-more guard and #429 cap
    value: float            # reward + eval_V(next_soe)

def select_action(
    soe: float,
    t: int,
    cost_basis: float,
    eval_V: Callable[[float], float],
    eval_value_slope: Callable[[float], float],
    period_inputs: PeriodInputs,
    battery_settings: BatterySettings,
) -> SelectionResult:                 # chosen Candidate + full candidate
                                      # list + argmax index + tie margin

@dataclass(frozen=True)
class PeriodInputs:                   # HORIZON-level bundle, indexed by t
    buy_price: list[float]
    sell_price: list[float]           # reward-facing (floored) prices
    home_consumption: list[float]
    solar_production: list[float]
    dt: float                         # hours
    max_charge_power_per_period: list[float] | None   # 233 derating
    import_cap_kwh: float | None      # 429 fuse cap
    discharge_resolution_kw: float | None
    sell_price_floored: list[bool] | None             # 269 flag
```

**As-built (Phase 1, PR #521) — this block is the real signature, not a
sketch.** Three things the original sketch got wrong, corrected here so
Phase 2 does not re-derive them:

1. **`PeriodInputs` holds horizon-level lists indexed by `t`, not
   per-period scalars.** `_compute_reward` takes the price *lists* plus a
   period index, so scalar fields would mean rebuilding throwaway lists
   per candidate or changing the physics core's signature at ~15 call
   sites. Converting `_compute_reward` to the scalar convention its twin
   `_compute_reward_grid` already uses belongs to a phase allowed to touch
   that signature — it is not free.
2. **`select_action` also takes `cost_basis` and a separate
   `eval_value_slope`.** The grid and PWL paths compute dV/dSoE
   differently (`_local_value_slope` clamps a grid index;
   `_pwl_local_value_slope` takes a clamped central difference); unifying
   them would be a behavior change. `self_throttle_export_threshold_kwh`
   is gone from the sketch entirely — #497 removed that threshold.
3. **One deferred import is structural.** `action_selector` imports the
   physics from `dp_battery_algorithm`, so `dp_battery_algorithm`'s two
   consumers import back from it inside the function body — the same
   arrangement `optimize_battery_schedule` already has with
   `pwl_window_dp`. The alternative was moving the physics core out of
   `dp_battery_algorithm.py`, which the architecture doc protects.

- Candidate enumeration (idle, discharge lattice via
  `_discharge_candidates`, charge via `_charge_candidate`, SOLAR_EXPORT
  bypass #313, import-cap filter #429) moves here verbatim.
- The existing tie-breaks (`_prefer_load_covering_discharge`,
  `_prefer_curtailed_charge_absorb`) are **called from inside
  `select_action` in their current order** — Phase 1 does not change tie
  semantics, only the number of places they live.
- `_tie_margin` and the `epsilon_for_period` call move inside; the
  `SelectionResult` exposes `tie_margin` and `value_slope` so
  `optimize_battery_schedule` keeps feeding `detect_tie_windows` unchanged.

**Steps:**

- [ ] Write `test_action_selector_parity.py`: for every fixture in
      `core/bess/tests/unit/data/`, run `optimize_battery_schedule` on
      current `main` (captured golden outputs: actions + soe_trajectory +
      battery_solar_cost, stored as a generated JSON under
      `tests/unit/data/golden/` in the first commit) and assert the
      refactored path reproduces them bit-identically.
      **Golden lifecycle:** these goldens pin *refactor* parity, and every
      later behavior-changing phase (Phase 2 onward) regenerates them as
      part of its measured-delta step, stating the regeneration in the PR
      body. The parity test itself is never deleted or skipped — a phase
      that can't regenerate goldens hasn't measured its delta.
- [ ] Run it against unrefactored code to prove the golden capture is
      self-consistent (trivially passes).
- [ ] Extract `Candidate`/`select_action`; port the grid replay call site;
      parity test must pass.
- [ ] Port the grid backward-induction hot loop's selection to the same
      enumeration (keep the vectorized fast path if bit-parity holds;
      if the vectorized path can't route through `select_action` without
      slowdown, it must at least share the same candidate-enumeration
      functions and a parity test pins vectorized-vs-selector agreement —
      this is the #236 lesson).
- [ ] Port both PWL call sites; delete the mirrored candidate/tie code in
      `pwl_window_dp.py`; parity test must pass.
- [ ] Confirm the four former call sites contain no candidate logic —
      `grep -n "_prefer_\|_discharge_candidates\|_charge_candidate"` hits
      only `action_selector.py` (plus imports).
- [ ] Full suite + slow suite + quality-check; commit; draft PR;
      `/code-review`.

**Exit gate:** bit-parity across all fixtures; diff shows net deletion in
`pwl_window_dp.py`; no behavioral pin changed.

## Phase 2: The preference table (P2)

**One PR. First deliberate behavior change; small, measured, fixture-pinned.**

**Files:**
- Create: `core/bess/tie_policy.py` — the ordered preference table.
- Modify: `core/bess/action_selector.py` — replace the two `_prefer_*`
  calls with one `apply_tie_policy(...)` call.
- Delete: `_prefer_load_covering_discharge`,
  `_prefer_curtailed_charge_absorb` (their docstring rationale moves into
  the corresponding table rows).
- Test: `core/bess/tests/unit/test_tie_policy.py`; existing
  `test_curtailment_charge_early_tiebreak.py` and the #466 spec tests keep
  passing unmodified (they pin behavior, not implementation).

**Interfaces:**

```python
# core/bess/tie_policy.py

@dataclass(frozen=True)
class TieContext:
    epsilon: float                 # from tie_detection.epsilon_for_period
    home_consumption: float
    solar_production: float
    dt: float
    rate_step: float               # discharge lattice step, kW
    sell_price_floored: bool       # 269 flag for this period

def apply_tie_policy(
    candidates: list[Candidate],
    argmax_index: int,
    ctx: TieContext,
) -> int:                          # chosen index
```

Baseline table (each row = one guard/preference, applied in order, all
measured against `candidates[argmax_index].value` — never chained):

1. **Guard:** candidates importing more grid than the argmax winner are
   ineligible (+1e-9 tolerance). (Subsumes the identical guard inside
   `_prefer_curtailed_charge_absorb` — dp:1504. Recorded foreclosure: in
   negative-buy-price windows a within-epsilon grid top-up is arguably the
   safer pick against a solar shortfall, and this row permanently bans it.
   That codifies today's behavior; a future amendment relaxing it must
   cite this note and bring field evidence.)
2. **Guard (per-preference, not shared — see below):** row 3 returns the
   argmax winner unchanged when it is a **charge**
   (`power > POWER_TOLERANCE_KW`) or a discharge **already beyond the load
   cover** (`-power > max_cover_p`, row 3's own eligibility bound). An
   IDLE winner *or a partial-cover discharge winner* stays eligible, so
   row 3 can improve a partial cover to a larger within-epsilon one.
   Row 4 keeps its own, different guard: it bails on any **discharge**
   winner and may still improve a charge winner.

   Charge winners are never flipped to discharges — that part is
   unchanged and still intended: it would be an undeclared semantic change
   this plan does not make.

   **This row previously claimed "both `_prefer_*` functions bail on any
   non-idle winner", and that parity claim is now false in both
   directions.** #512 widened `_prefer_load_covering_discharge` to fire on
   partial-cover winners as well as IDLE: which candidate `argmax` returns
   among tied candidates is an enumeration-order accident, and at #512's
   finer grid it started landing on partial covers, silently skipping the
   swap and leaving residual import exposed — the hole a literal
   implementation of the old row 2 would re-open. In the other direction,
   `_prefer_curtailed_charge_absorb` bails on discharge winners, not on
   all non-idle ones, so it can already improve a charge winner today.
   The asymmetry between the two rules is therefore deliberate and must
   survive the merge into `apply_tie_policy`; a single shared non-idle
   guard cannot express it.
3. **Prefer** the largest load-tracking discharge ≤ net load (+half a
   rate step, capped at `BATTERY_EXPORT_THRESHOLD_KWH/dt`) within epsilon
   — the #466 rule, now firing on **all** within-epsilon ties, including
   `epsilon == 0` flat-value periods and the sunrise/sunset crossover
   (net load ≤ 0 falls through to row 4).
4. **Prefer** the highest-`next_soe` candidate within epsilon when
   `sell_price_floored` (the #510 rule).
5. Otherwise the argmax winner stands.

**The two deliberate semantic changes vs today, and their acceptance:**

- Row 3 drops the `epsilon <= 0.0` early-return (flagged in the #510
  review: today the tie-break is disabled exactly where the value function
  is flat, the most degenerate tie). At `epsilon == 0`, "within epsilon"
  catches only bit-exact ties — economically sound, since cycle cost is
  already inside `_compute_reward`, so on an exact tie tracking is weakly
  dominant under forecast error. **Before writing the RED test, replay the
  ridax67 2026-08-07-232503 bundle and measure the 06:00–06:59 period's
  actual margin.** If it is bit-exact-tied, the acceptance below applies
  as written. If the gap is tiny but nonzero, passing requires an epsilon
  *floor* — which trades real model value and may only be introduced with
  an explicit per-period forfeiture bound stated in the row docstring
  (and counted against the 0.05 SEK/fixture budget).

  **The sunrise/sunset crossover is NO LONGER this row's acceptance test
  — see #517.** This plan originally specified ridax67's 06:00–06:59
  period as the proof that dropping the early-return works. #517
  established that period was never a tie at all: the action set was
  *empty* (every lattice candidate overshot the 86 W residual and #497
  correctly excluded the unexecutable ones), so IDLE won by default, not
  by a coin flip. The fix was a new candidate — discharge exactly the
  forecast residual — i.e. P3 (candidates are executable commands)
  subsumed the case P2 was going to handle. An implementer who tests the
  crossover here will be testing something already fixed by another
  mechanism and may wrongly conclude the tie policy caused it.
  Crossover acceptance now lives in Phase 4 (candidate space).

  Row 3's remaining acceptance is therefore the *genuine* near-ties: the
  original #466 evening periods (19:00 / 22:15 in bundle
  2026-08-06-110152, decisive-margin holds must stay IDLE while coin
  flips resolve to tracking) plus #393's overnight residual. Measure a
  candidate period's actual margin before writing the RED test; the
  epsilon-floor rule above still applies.
- Rows apply uniformly in grid and PWL paths via Phase 1's single call
  site — the `#466-vs-#510 can't fight` argument becomes row ordering, not
  a guard-clause coincidence.

**Steps:**

- [ ] Port the existing unit tests for both `_prefer_*` functions onto
      `apply_tie_policy` (same cases, same expected indices) — run RED
      against an empty table, GREEN against the ported rows.
- [ ] **P6 splice cost-gate rider:** accept a re-solved tie window only if
      its replayed cost (via `_replay_accounting_pass` over the spliced
      segment) is ≤ the grid segment it replaces; a worse window is
      discarded with a WARNING log naming the window and both costs (an
      explicit, visible decision — not a silent fallback: the grid plan is
      the incumbent, the splice is the challenger). RED test: a synthetic
      window reproducing the #513 mis-ranking shape must NOT be spliced.
      This makes `optimizer-architecture.md` P6 true in code.
- [ ] Add the two new acceptance tests above (RED first: today's code
      picks IDLE at the crossover with epsilon 0).
- [ ] Implement; measure the corpus deltas
      (`test_plan_faithfulness.py` pins + per-fixture planned cost); any
      pin that moves is stated with its measured value in the PR body and
      must stay within the 0.05 SEK budget per fixture.
- [ ] Full + slow suite; mock-HA replay of the ridax67 bundle
      (`mock-run.sh 2026-08-07-232503`) to observe the crossover command;
      quality-check; draft PR; `/code-review`.
- [ ] Answer #466 with the shipped rule, quoting ridax67's WANTS/EXPECTS
      principle as the implemented semantics.

**Exit gate:** all tie resolution flows through `tie_policy.py`; repo-wide
`grep` for `_prefer_` returns nothing; corpus pins within budget.

## Phase 3: One flow record (P4)

**Scope to acceptance level — first step is its own detailed plan.**
Depends on Phase 0's fold-scoping outcome (it may already have moved the
#350 fold; this phase finishes the job from the reward side).

- [ ] Write the detailed plan (superpowers:writing-plans) covering:
      per-candidate flow record computed once in
      `action_selector.select_action` (extending `_compute_reward`'s
      existing flow math, not duplicating it); reward derived from that
      record; `_replay_accounting_pass` consuming the stored records
      instead of recomputing; sensor-noise heuristics verified to exist
      only in `sensor_collector.py` (grep every `EnergyData` construction
      site: `sensor_collector`, `influxdb_helper`, `debug_data_exporter`,
      `simulation/inverter_simulator`, backend API paths — each gets an
      explicit exact-vs-ingested decision in the plan).
- [ ] Acceptance (already written — landed on main via Phase 0's drain
      item): the #497 pin in `test_flow_coherence.py` — 182/1875
      incoherent periods — goes to
      **0**, and the plan-execution gap pins that the fold caused
      (+0.73/+0.56/+0.45 family) collapse, each re-pinned at its measured
      value.
- [ ] Full + slow + E2E per the detailed plan; draft PR; `/code-review`.

**Exit gate:** zero flow-coherence violations; no reward-only or
flows-only code path survives (`P4` compliance grep in the PR body).

## Phase 4: Executable-command candidates (P3)

**The one genuinely medium-sized project. Scope to acceptance level —
first step is its own design doc + detailed plan (this is a
`brainstorming` → `writing-plans` sequence, and rules.md's new-class
approval applies).**

- [ ] Design doc first: candidate = executable command (mode + rate on the
      platform lattice + reactive semantics), evaluated by simulating the
      command against the forecast — reusing
      `simulation/inverter_simulator.derive_control_command`/`simulate`
      logic in the selector rather than a third implementation of inverter
      behavior. Strategic intent becomes the chosen command
      (`classify_strategic_intent` on planned flows is deleted or reduced
      to observed-data use). Per-platform capability differences (percent
      lattice, VPP vs TOU, minimum gear) enter through
      `BatterySettings`/platform config, not hardcoded (#320's complaint).
- [ ] Acceptance criteria (fixed now, design chooses the how):
      - #320: no Growatt MIN mode flip caused by plan/lattice rounding on
        the reproduction bundle.
      - #352: a low-rate export plan either carries a command that
        tolerates load spikes or is not planned; the #352 reproduction
        shows no avoidable spike import. Covers the 0.1–0.5 kWh
        home-dominant band #511 does not reach, using #354's two-sided
        materiality test (dominance OR forfeited headroom) as candidate
        scoring rather than post-hoc demotion.
      - #466 crossover: ridax67's 06:00–06:59 residual-cover case (#517)
        keeps a regression test here, where it belongs — the candidate
        space, not the tie policy.
      - #511-class: a planned discharge the inverter cannot execute is
        unrepresentable — the test constructs the old failing plans and
        shows the candidate space cannot express them.
      - R==P corpus: `PLAN_EXECUTION_GAP_SEK` pins move toward 0 and none
        regress.
- [ ] Close #354 once Phase 4 covers its band; fold PRs #511 and #517's
      tests in as regression tests.

**Exit gate:** intent is an input; the corpus R==P gaps are at their
floor; #320/#352 reproductions pass.

## Parallel / deferred tracks

- [ ] **#487 (any time, independent):** consumption statistics must
      account for inverter self-consumption while the battery sleeps.
      Route through `implement-issue`. Improves every forecast-sensitive
      decision; requires none of the phases.
- [ ] **#485 hysteresis (after Phase 2):** "keep the applied schedule
      unless the new plan beats it by more than epsilon" — consumes
      `epsilon_for_period` (P5), implemented at the apply layer
      (`battery_system_manager`), a small PR once Phase 2 defines the
      epsilon surface.
- [ ] **Terminal value out of `battery_system_manager.py` (any time after
      Phase 0):** `_calculate_terminal_value` (~bsm:1902) is the single
      most economically sensitive scalar in the system, with a six-issue
      lineage (#126/#244/#246/#345/#422/#359 — the Frank horizon-drift
      family), and its sell-price day-scoping lives in a *different*
      method — the exact split that produced #422. Extract into
      `core/bess/terminal_value.py` with its scoping, mechanically, with a
      bit-parity test over the corpus. Small PR, independent of Phases 1–4.
- [ ] **#513 (before any new reliance on PWL exactness):** fix the PWL
      mis-ranking; until then P6 stands (PWL splices are heuristic).
- [ ] **#512 (gated on premise test):** SOE-step sweep through
      `scripts/bench_pwl_everywhere.py` (on main via Phase 0's drain item)
      + realized-cost harness first; only
      if the finer grid captures the gap AND survives realized cost does a
      constants PR follow (2026-08-09 sweep found the #350 fold interaction
      — Phase 0/3 must land first).

## Execution order summary

```
Phase 0 (drain WIP)
   ├── #487 (parallel, independent)
   ▼
Phase 1 (one selector)        — mechanical, bit-parity
   ▼
Phase 2 (preference table)    — closes #466 residual; then #485
   ▼
Phase 3 (one flow record)     — closes #497; absorbs fold-scoping
   ▼
Phase 4 (command candidates)  — closes #320/#352; subsumes #354's band
   
#513 fix when touched; #512 sweep-gated; both may run between phases.
```
