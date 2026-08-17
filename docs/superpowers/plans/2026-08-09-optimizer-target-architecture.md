# Optimizer Target Architecture — Migration Plan

> **For agentic workers:** This is a PROGRAM plan: an ordered sequence of
> phases, each of which is a separate PR (or short PR series) executed in
> its own session/worktree. Phases 1–2 are specified to implementation
> level here. Phases 3–4 are specified to acceptance level; their first
> step is to write their own detailed plan (superpowers:writing-plans, or
> `implement-issue` where a phase maps 1:1 to an issue). Do NOT execute
> later phases from this document alone. Steps use checkbox (`- [ ]`)
> syntax for tracking.
>
> **How disagreements are settled (added 2026-08-10, after three sessions
> reached three different orderings from this same text).** Claims here are
> settled by *measurement against fixtures, live bundles, or the code as it
> stands on `origin/main`* — never by re-reading the plan text. A session
> that disagrees with an ordering must bring a newer measurement, and must
> record it in this document, inline, with its date and how it was
> obtained. Every reordering below carries its evidence for exactly that
> reason: the 2026-08-10 three-way disagreement happened because the
> winning measurements lived only in session transcripts while the doc kept
> asserting stale premises. A conclusion recorded without its measurement
> is how this recurs.
>
> **Tick the boxes.** Phases 1 and 2 both shipped with every box in this
> document still unchecked, which made the doc useless as a status source
> and was an independent cause of the same confusion. A merged phase ticks
> its boxes in the merging PR.

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

**"The corpus", used throughout this document and the code comments**, means
the scenario fixtures in `core/bess/tests/unit/data/` — 37 as of 2026-08-13,
across five `historical_*` (real price days), ten `realworld_*` and nine
`regression_*` (built from real user debug bundles), and thirteen `synthetic_*`
(constructed edge cases). Every pin iterates that same set: `test_scenarios.py`
auto-discovers it, and the action-selector goldens, the VPP baseline and the
R==P check all run over it — which is why adding a fixture deliberately trips
two meta-tests.

Worth stating because it bounds what "measured on the corpus" can ever mean.
These are Swedish and Belgian systems at 15-minute **point** forecasts, so a
sub-period effect (load exceeding the period average within the slot) is
arithmetically zero here by construction, and no fixture represents a
configuration nobody has sent a bundle for. #393's overnight residual measures
0 here while remaining live on real hardware: a zero can mean the instrument
cannot see it, not that it does not happen.

**But check that a zero is not an identity first (2026-08-13).** #352's
Shape B was recorded as "measures 0 on the corpus" on the same reasoning, and
that was wrong for a different reason: the scan asked whether a
`BATTERY_EXPORT` period discharges below the house deficit, which the flow
derivation makes impossible by construction. It measured algebra, not the
corpus. The real criterion reproduces 22 periods, exactly as first recorded —
see the Phase 4 section. Before concluding "the instrument cannot see it",
confirm the criterion *could* have returned non-zero.

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

| Phase | Retires / unblocks | Class | Status |
|---|---|---|---|
| 0 | in-flight WIP: #510, #511 (#497), #506, #507 (#502), #508 (#501), #515, #516 (#512), #517 (#466 crossover) | 2, 3 | **DONE** |
| 1 | the mirrored-selector bug class (#236-shape, `DISCHARGE_LATTICE_PCT_EPS`-shape) | 3 | **MERGED — PR #521** |
| 2 | #466 evening near-ties, #393; makes #485 trivial; subsumes #466/#510 tie-break code (crossover moved to Phase 4 — #517) | 1, 3 | **MERGED — PR #525** (P6 rider *not* included — moved to deferred, see below) |
| 3 | #459-class; collapses the duplicated planning-side flow derivations into one record ("six" was unmeasured — census in the Phase 3 section). **No longer closes #497** — #511 already did | 2 | **MERGED — PR #534** (re-scoped 2026-08-10). Closeable: all five follow-ups below are non-blocking, and #536 is explicitly "does not block a release" |
| 4 | #352 **Shape B only** (see Phase 4 section — Shape A was #520/#524), #354 (parked — right problem, wrong layer), #466 crossover regression cover, #511-class recurrence, #320 regression cover | 2 | **#520/#524 gate CLEARED. D1/D2/D4 approved 2026-08-11**; **4a is now the prerequisite for the #352 fix** (the fix needs the load-following capability, which never reaches the DP). **Beta gate cleared 2026-08-14** — beta ran clean and is being released to main; 4b/4c wait only on 4a |
| 5 | intent-as-input (was Phase 4d — split out 2026-08-11; 25 backend modules + 10 frontend files + the goldens) | 2, 3 | after 4b/4c |
| prerequisite | #526 (live latent defect; blocked #520 → #524 → Phase 4's R==P claim) | 2 | **MERGED — PR #530** |
| parallel | #487 (input quality — premise check first, independent) | 1 input | **PARKED** — premise not confirmed, no fix built |
| found en route | #528 (derived `lifetime_load_consumption` omits the battery terms, so it reports actual load **plus net battery charge**; the `max(derived, 0.0)` clamp hides the largest errors). Does *not* reach the `ha_statistics` forecast — that path resolves the entity directly and raises when absent | 1 input | filed 2026-08-10, unscheduled |
| deferred | #513 (fix when touched; until then P6 treats PWL as heuristic), #512 (SOE-step sweep, gated on its own premise test), **P6 splice cost-gate** (measured non-firing — see Phase 2) | 3 | last |

**#320 is CLOSED (2026-08-09)** and is no longer a live driver for any
phase. It appears above only as regression cover. Measured on its own
reproduction fixture before closing: 23/129 `BATTERY_EXPORT` periods with
**zero** sub-threshold exports, against 62/129 with 31 sub-threshold when
the issue was filed — #511 and #517 between them removed the mechanism.
Any session citing #320 as a reason to reorder is working from stale text.

---

## Phase 0: Drain the WIP queue (entry criteria, not new work)

No new architecture work starts while overlapping WIP is open — parallel
sessions rediscovering each other's findings is how this program got
confusing.

- [x] Merge PR #510 (merged 2026-08-08, `742d5906`; two optional test nits
      may follow up).
- [x] Flow-coherence invariant — landed as PR #506 on 2026-08-08, before
      this plan was written. **Correction (2026-08-10): there is no
      `test_flow_coherence.py` on `origin/main`.** The invariant lives as
      `assert_flow_coherence` in `core/bess/tests/helpers.py:288` and is
      called from the canonical scenario harness
      (`test_scenarios.py:254`), `test_dp_breakpoint_search.py:663`, and
      `helpers.py:260` — i.e. it runs over the whole fixture corpus rather
      than from a file of its own. That is the better arrangement, but the
      wrong filename in this doc sent at least one session looking for a
      pin that does not exist. See Phase 3 for what this does to its
      acceptance criteria.

      **No coverage was lost — provenance, so nobody re-opens this.**
      `9da0f539` (PR #506) added `test_flow_coherence.py`; `33f62129`
      (PR #511) deleted it *and* migrated its content, in the same commit,
      into `helpers.py` (+36 lines) and `test_scenarios.py` (+14). That
      commit's own message states the reason: "All 182 incoherent periods
      are gone, and **the two invariants that were pinned as debt are
      ordinary assertions now**." So the standalone pin was retired
      because it had been promoted, not dropped — and today's
      `assert_flow_coherence` is a strict superset of it (6 invariants:
      four source/destination balances, the home-consumption balance, and
      non-negativity across all 7 named flows). Stale copies of the
      deleted file survive in unmerged worktrees and branches
      (`origin/test/period-flow-invariants` among others); finding one
      there is not evidence that coverage went missing.
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
- [x] Post the #466 status comment — posted 2026-08-09 (plain language, no
      shadow-price/lattice jargon, as required). #466 stays open for the
      Phase 2 evening near-ties answer. Original requirement: ridax67's
      principle ("IDLE = WANTS,
      not EXPECTS") is now P2 of the target architecture, and the
      sunrise/sunset crossover shipped in #517 — written in plain
      language (no shadow price / backward induction / lattice jargon;
      the reporter has said explicitly that vocabulary is not useful to
      him).

## Phase 1: One selector (P1) — ✅ MERGED (PR #521, `19305476`)

**One PR. Pure mechanical extraction — zero behavior change, enforced by
bit-parity.** Shipped as specified; the as-built interface corrections are
recorded in the Interfaces block below.

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

- [x] Write `test_action_selector_parity.py`: for every fixture in
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
- [x] Run it against unrefactored code to prove the golden capture is
      self-consistent (trivially passes).
- [x] Extract `Candidate`/`select_action`; port the grid replay call site;
      parity test must pass.
- [x] Port the grid backward-induction hot loop's selection to the same
      enumeration (keep the vectorized fast path if bit-parity holds;
      if the vectorized path can't route through `select_action` without
      slowdown, it must at least share the same candidate-enumeration
      functions and a parity test pins vectorized-vs-selector agreement —
      this is the #236 lesson).
- [x] Port both PWL call sites; delete the mirrored candidate/tie code in
      `pwl_window_dp.py`; parity test must pass.
- [x] Confirm the four former call sites contain no candidate logic —
      `grep -n "_prefer_\|_discharge_candidates\|_charge_candidate"` hits
      only `action_selector.py` (plus imports).
- [x] Full suite + slow suite + quality-check; commit; draft PR;
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

- [x] Port the existing unit tests for both `_prefer_*` functions onto
      `apply_tie_policy` (same cases, same expected indices) — run RED
      against an empty table, GREEN against the ported rows.
- [ ] **P6 splice cost-gate rider — NOT shipped in #525; moved to the
      deferred track (2026-08-10).** Measured before deferring: splicing
      toggled on/off across all 36 fixtures moves **every** delta ≤ 0, so
      the gate would not fire on anything in the corpus today. It is
      insurance against a shape #513 describes, not recovered money, and it
      costs a `_replay_accounting_pass` per tie window. Do it last, or take
      its uncosted alternative (disable splicing and fix #513). Original
      specification, unchanged, for whoever picks it up: accept a re-solved
      tie window only if
      its replayed cost (via `_replay_accounting_pass` over the spliced
      segment) is ≤ the grid segment it replaces; a worse window is
      discarded with a WARNING log naming the window and both costs (an
      explicit, visible decision — not a silent fallback: the grid plan is
      the incumbent, the splice is the challenger). RED test: a synthetic
      window reproducing the #513 mis-ranking shape must NOT be spliced.
      This makes `optimizer-architecture.md` P6 true in code.
- [x] Add the two new acceptance tests above (RED first: today's code
      picks IDLE at the crossover with epsilon 0).
- [x] Implement; measure the corpus deltas
      (`test_plan_faithfulness.py` pins + per-fixture planned cost); any
      pin that moves is stated with its measured value in the PR body and
      must stay within the 0.05 SEK budget per fixture.
- [x] Full + slow suite; mock-HA replay of the ridax67 bundle
      (`mock-run.sh 2026-08-07-232503`) to observe the crossover command;
      quality-check; draft PR; `/code-review`.
- [x] Answer #466 with the shipped rule, quoting ridax67's WANTS/EXPECTS
      principle as the implemented semantics.

**Exit gate:** all tie resolution flows through `tie_policy.py`; repo-wide
`grep` for `_prefer_` returns nothing; corpus pins within budget.

## Phase 3: One flow record (P4) — RE-SCOPED 2026-08-10

> **This phase changed character. Read this before planning it.** As
> written, Phase 3 was a *behavior fix* whose acceptance was driving
> flow-coherence violations to zero. **That acceptance is already
> satisfied on `origin/main` and cannot discriminate anything.** Measured
> independently 2026-08-10: **0 incoherent periods across 2168**. The
> original 182/1875 pin is dead, and the invariant that replaced it —
> `assert_flow_coherence`, `helpers.py:288` — is a strict superset of the
> retired pin (6 invariants: the four source/destination balances, the
> home-consumption balance, and non-negativity across all 7 named flows,
> against the old pin's 2). It runs over the whole scenario corpus via
> `test_scenarios.py:254`.
>
> What remains is real but different: the planning-side flow derivations
> are still duplicated, and collapsing them into one per-candidate record is
> a consolidation refactor, not a behavior change. Plan and gate it as such.
>
> **"Six" was never measured — corrected 2026-08-10 by census.** The
> planning/reporting charge-split derivations at the time Phase 3 started
> were **eight**: `_compute_reward`, `_build_period_data`,
> `_create_idle_schedule`, `_state_transition`, the two numpy mirrors
> (`_compute_reward_grid`, `_state_transition_grid`, both explicitly out of
> scope under P1(a)), `pwl_window_dp`'s store/idle gain, and
> `EnergyData._calculate_detailed_flows` (a legitimately different
> derivation — it works from aggregate totals, not from a chosen action).
> Two more lived in `battery_system_manager` (`_calculate_initial_cost_basis`
> and the energy-balance log table), for **ten** sites overall. Phase 3
> removes five of them: the first three collapse into `_period_flows`, and
> both BSM sites now read the split `EnergyData` already derived.
> `_state_transition`, the two numpy mirrors and the PWL gain remain
> deliberately.
> `assert_flow_coherence` stays in place as the standing regression net —
> it is no longer the goal, it is the floor.
>
> **Phase 3 no longer closes #497.** #497 was closed by PR #511 on
> 2026-08-09. A session that plans Phase 3 around closing it will be
> re-fixing shipped work.

**Scope to acceptance level — first step is its own detailed plan.**
Phase 0's fold-scoping premise check already moved the substance to #511;
what is left of the #350 fold here is non-urgent data hygiene, explicitly
demoted in Phase 0. Do not re-litigate it.

**Acceptance is now golden bit-parity, exactly as in Phase 1** — the
strongest oracle available and, unlike coherence or corpus-cost pins,
independent of every open behavioral question (#520/#524/#526). A
consolidation that changes no bit has demonstrably not changed behavior;
one that does has a delta to state and defend against the 0.05
SEK/fixture budget.

- [x] **DONE** — detailed plan written and merged as PR #533
      (`2026-08-10-phase3-one-flow-record.md`). Covered:
      per-candidate flow record computed once in
      `action_selector.select_action` (extending `_compute_reward`'s
      existing flow math, not duplicating it); reward derived from that
      record; `_replay_accounting_pass` consuming the stored records
      instead of recomputing; each `EnergyData` construction site gets an
      explicit exact-vs-ingested decision.

      **Both halves of this item were wrong — corrected 2026-08-10 by
      grep.** The sensor-noise heuristics did *not* live only in
      `sensor_collector.py`: three are in `models.py`
      (`EnergyData._calculate_detailed_flows` — the #350 fold and two
      non-invention clamps, which run on planned data too, a literal P4
      violation), and `energy_flow_calculator.py` carries its own
      gap-filling fallbacks for `system_production`/`self_consumption`.

      **That P4 violation is still open.** Phase 3 tried to gate them and
      backed out: the two clamps are physical bounds rather than noise
      models, and gating the #350 fold flips planned intent to
      BATTERY_EXPORT (hence `grid_first`) in the reachable regime
      `ac_cap < home < solar`, where #497's pre-clipping deficit leaves the
      candidate admitted. Fixing it means an AC-aware candidate filter —
      Phase 4's business, not the model layer's. See the Phase 3 detailed
      plan's Task 5 and
      `test_planned_flows_still_pass_through_the_ingest_fold`.
      `sensor_collector.py` itself constructs `EnergyData` but applies no
      heuristic of its own.

      The construction-site list was also stale. `influxdb_helper` and
      `debug_data_exporter` construct **none**, and
      `simulation/inverter_simulator` constructs none directly (it goes
      through `_build_period_data`). The five real production sites are
      `sensor_collector.py`, `dp_battery_algorithm.py`
      (`_build_period_data`), `daily_view_builder.py`, `models.py`
      (`apply_export_curtailment_to_period_data`) and
      `prediction_snapshot.py`.
- [x] **MET — bit-parity held on all 36 fixtures at every task**, byte
      identical on `actions`, `soe_trajectory` and `battery_solar_cost`. A
      full-field diff (every energy/economic/decision field, all 2168
      periods) found **0 differences** against pre-refactor `main`; the only
      behavioural delta anywhere is Task 3's intended cost-basis correction,
      one fixture, 0.049977 SEK/kWh. Original acceptance text:
- [x] **Acceptance — golden bit-parity across every fixture in
      `core/bess/tests/unit/data/`**, reusing Phase 1's
      `golden_capture.py` machinery and its regeneration discipline. Any
      non-zero delta means the consolidation changed behavior: state the
      measured value in the PR body and justify it against the 0.05
      SEK/fixture budget, or fix it. `assert_flow_coherence` must stay
      green throughout (floor, not goal — it is already at 0/2168).
- [x] **DONE** — 1690 fast + 458 slow green, mock-HA E2E run, draft PR,
      `/code-review` at high effort (22 agents) plus two maintainer review
      rounds. Every CONFIRMED finding fixed before merge; the review rounds
      found four real defects this phase introduced, all of which are
      recorded with their measurements in PR #534.

**Exit gate — MET, with one part of P4 explicitly not closed.** Bit-parity
holds. No reward-only or flows-only code path survives. The duplicated
planning-side flow derivations are one (`_period_flows`), with
`_state_transition`, the two numpy mirrors and the PWL gain remaining
deliberately — see the census note above.

**P4's noise-model half did NOT land.** Task 5 (gate the ingest heuristics
so exact data bypasses them) was attempted and withdrawn: two of the three
are physical bounds rather than noise models, and gating the third (#350's
fold) flips planned intent to BATTERY_EXPORT — hence `grid_first` — in the
reachable regime `ac_cap < home < solar`, where #497's pre-clipping deficit
leaves the candidate admitted. Closing it needs an AC-aware candidate
filter, i.e. Phase 4. Pinned by
`test_planned_flows_still_pass_through_the_ingest_fold`, which should
**flip** when the gate lands rather than be deleted.

**Phase 3 is closed.** Its follow-ups are triaged below; none blocks a
release.

## Phase 4: Executable-command candidates (P3)

**The one genuinely medium-sized project. Scope to acceptance level —
first step is its own design doc + detailed plan (this is a
`brainstorming` → `writing-plans` sequence, and rules.md's new-class
approval applies).**

### Is Phase 4 subsumed by #511/#517? No — measured 2026-08-10

One session argued Phase 4 had been overtaken by the #511/#517 fixes. It
had not, and the counter-evidence is static and re-checkable rather than
inferential — re-run these two greps before reopening the question:

- **The plan charges at nominal power in six hardcoded places.**
  `rate_throughput = battery_settings.max_charge_power_kw * dt` appears at
  `dp_battery_algorithm.py:355,475,508,546,644` and `pwl_window_dp.py:543`.
  (Re-measured 2026-08-11 on `2dcd540f`. This said *seven*, at now-stale line
  numbers, until Phase 3 restructured the file. The count is incidental; the
  next bullet is the load-bearing one.)
- **None of them reads the configured charge rate.** `charging_power_rate`
  has **zero** occurrences in `dp_battery_algorithm.py`,
  `pwl_window_dp.py`, and `action_selector.py` — while
  `battery_system_manager.py:3372` writes exactly that value to the
  inverter (`set_charging_power_rate`), and `bsm:3525` displays the
  resulting power as `(charging_power_rate / 100) * max_charge_power_kw`.

So on the charge side the planner assumes a throughput the executor is
configured not to deliver. That is a structural R≠P divergence on the
*charge* path, untouched by #511 and #517 (both of which addressed
discharge executability), and it is precisely what "candidates are
executable commands" fixes. Phase 4 stands.

> ⚠️ **Correction (2026-08-16, 4c's premise check): the second bullet's
> conclusion is false.** `battery_system_manager` writes
> `get_period_settings(period)["charge_rate"]`, not `charging_power_rate` —
> the intent-derived rate, which is a flat 100% for `SOLAR_STORAGE`/`IDLE`
> and scaled from the plan's own action for `GRID_CHARGING`.
> `charging_power_rate` (default 40%) is only the power monitor's *initial*
> target, `power_monitoring_enabled` defaults to False, and the target is
> overwritten every period anyway. **The executor is not throttled below what
> the planner assumes**, so the SEK this paragraph implies for 4c are not
> there.
>
> The *first* bullet stands: the plan does charge at nominal power in six
> places, and `_period_flows` derives charge throughput from
> `max_charge_power_kw` regardless of what was commanded. Because the DP and
> the inverter simulator share that record, the simulator reproduces the plan
> by construction and **cannot disagree with it about charge** — which is why
> the corpus R==P harness shows a 0.00000 gap while the written command is
> genuinely short. Closing that blindness is what "4c-full" would mean.
>
> Measured defect after the correction: 4 of 493 charging periods plan a
> charge the written command cannot deliver (worst −0.0288 kWh), caused by
> nearest-rounding the `GRID_CHARGING` rate. Fixed narrowly — see "4c as
> built" below.

**Phase 4's live driver is #352, not #320.** #320 is closed (see the issue
map). Recorded for #352 on 2026-08-10: 22 sub-load `grid_first` periods live,
16 of them in the 0.1–0.5 kWh band #511 does not reach, 5 clearly
spike-exposed.

✅ **Reconciled 2026-08-13 — the figure reproduces bit-exactly; the "0" was
vacuous.** The 22/16 criterion is a BATTERY_EXPORT period whose planned
*discharge* is below the period's *home consumption*: 22 periods, 16 with
export in the 0.1–0.5 kWh band, unchanged from 2026-08-10. The 2026-08-11
scan read "below the house deficit" literally, and that count is 0 *by
construction* — `EnergyData._calculate_detailed_flows` sets
`battery_to_home = min(discharged, home − solar)`, so any export at all
requires discharge above the deficit. It measured an identity, not the corpus.
Full criterion table, and the reproduction fixture
(`regression_2026_08_12_202906`, from the maintainer's 2026-08-12 Growatt MIN
bundle), in the design doc §2.

**#352 is two bugs; only one is Phase 4's** (split recorded on the issue,
2026-08-11). *Shape A* — LOAD_SUPPORT throttled below house load — is gatable
and was addressed by #520/#524, pending hardware verification. *Shape B* —
low-rate BATTERY_EXPORT on `grid_first` — cannot be gated at all, because
`grid_first` does not load-follow and raising its ceiling means "export at full
rate" (#324). Shape B is Phase 4's.

### Gating — ✅ CLEARED 2026-08-11

Phase 4's central claim is that R==P becomes structural, and two open issues
decided what R==P meant at the boundary: `#526` → `#520` → `#524`. **All three
are merged** (PRs #530 and #524), so the gate is settled and its ambiguity is
no longer at risk of being encoded into the candidate space. #541 additionally
supplied the VPP regression baseline that #540 gated Phase 4 on.

Two things gate it now, neither a code dependency:

1. **The design doc exists; its decisions are open.**
   `docs/superpowers/specs/2026-08-11-phase4-executable-candidates-design.md`
   — **D1, D2 and D4 approved 2026-08-11; D3 decided 2026-08-14** (see the split
   below). D1 resolved a blocker the split did not anticipate: **the selector
   cannot simply import
   `inverter_simulator`.** That module imports `intra_period_discharge_gate`
   from `battery_system_manager` and `InverterController`, so reusing it in the
   selector would make the optimizer core depend on the top-level orchestrator.
   `dp_battery_algorithm:1201` already defers an `action_selector` import
   because `action_selector` imports it back, so one cycle is already being
   worked around; adding a second is what `rules.md`'s workaround check
   forbids. The remedy is a leaf execution module both sides depend on, which
   means relocating the gate — hence approval.
2. **Sequencing behind the beta — CLEARED 2026-08-14 (owner).** The beta ran
   without reported issues and is being released to `main`, so this gate is
   spent; 4b/4c wait only on 4a. Original reasoning, kept as the test to
   re-apply if it recurs: Phases 1–3 were parity-preserving: the
   goldens were captured at Phase 1 and every later change left all 36
   fixtures' actions and SoE bit-identical. 4b/4c deliberately break that. The
   beta exists to prove 25 closed reporter fixes on real hardware, and a
   candidate-space change that moves most plans would make any report from
   those reporters ambiguous between a regression and an intended new choice.

### Split into three shippable PRs (was four — see D4)

Confirmed by the design doc and approved 2026-08-11. **4d has been removed
from Phase 4** and becomes its own phase; see below.

- **4a — capability model. BUILT** (`core/bess/execution_model.py`;
  as-built notes in the design doc §4c). Per-platform lattice / mode
  vocabulary / minimum gear / load-following semantics in a **new
  `PlatformCapabilities`** rather than folded into `BatterySettings` (D2),
  built by BSM from the live controller and threaded to the candidate space
  in place of `discharge_resolution_kw`. `intra_period_discharge_gate`
  relocated out of `battery_system_manager` (D1), so the simulator no longer
  imports the orchestrator. Semantics are the tri-state the design asked for
  (`ceiling` / `target` / `absent`). Goldens and the 36-fixture corpus are
  bit-identical; the one intended behaviour change is **#580** — the
  off-lattice residual-cover candidate is now offered only where a
  LOAD_SUPPORT discharge is actually delivered as `min(plan, actual load)`
  (native SolaX / SPH / Solis / Huawei lose it; Growatt keeps it in both
  control modes, because #413 makes VPP LOAD_SUPPORT natively
  load-following even though its rate register is a forced power — that
  distinction is a separate declared capability, see design doc §4c). No
  candidate-space changes beyond that gate.

  **Two gate fixes are queued behind 4a and should move with it** — both sit in
  the value-estimator code D1 relocates, so landing either first means measuring
  its delta twice:

  - **#579 (open, `blocked`)** — `_record_marginal_value` snapped with `round()`
    while `_interpolate_value` floors, so a SoE in the lower half of a cell was
    priced off the cell below. Fixed and green; 142 of 2168 golden gate booleans
    flip (141 opening). It introduces `_value_slope_below` as a **third** peer
    dV/dSoE estimator — the behaviour change the "as-built" note above defers —
    and a **new public `has_value_cell_below`** on `dp_battery_algorithm.py`
    that the gate tests call so they stop mirroring the DP's index rule.
    **4a should absorb both into `execution_model.py` rather than inherit them
    at their current home.**
  - **#571 (open, `blocked`, not yet fixed)** — a *different* defect at the same
    seam: `np.round` snapping makes `V` locally non-concave and the gate reads
    the corrupted cell. #579 does **not** fix it — at the reported state
    `idx = 324.0` is exactly on a grid point, so `round()` and `ceil()-1` select
    the same cell. Candidate fix is to read the slope off the upper concave
    envelope; scored against a 0.005 kWh reference it roughly halves the error
    on the 217 concavity-violating states without regressing the 1642 clean
    ones. Reproduce from **period 58** of the bundle (horizon 134,
    `initial_soe` 9.9), not period 59.

  Neither *depends* on 4a technically — this is sequencing, and 4a's
  behaviour-neutrality requirement is the reason.

  **Status after 4a landed: still queued, and 4a did not absorb them.**
  #579 is unmerged, so there was no code to move; and both fixes live in
  `dp_battery_algorithm._record_marginal_value`, which D1 does not relocate
  — 4a moved the gate itself (the two-line ceiling function), not the value
  estimator that decides its input. Absorbing #579 would additionally have
  flipped 142 golden gate booleans inside the phase required to be
  behaviour-neutral. Land them next, each measuring its own delta.
- **4b — discharge commands.** Candidates become executable discharge
  commands; folds in #511/#517's tests as regression cover. Closes #352
  **Shape B** with the exact-cover candidate, gated on 4a's load-following
  capability. Gated on 4a and the beta.
- **4c — charge commands. NARROW VERSION BUILT 2026-08-16; the full one is
  deliberately not.** The original scope ("collapse the six `rate_throughput`
  sites to the configured rate") rests on a premise that does not hold — there
  is no configured rate being written; see the correction above. What was
  measured instead: 4 of 493 charging periods plan a charge the written
  command cannot deliver, because the `GRID_CHARGING` rate is scaled from the
  plan and rounded to *nearest*, landing below it.

  **Built:** the charge command rounds **up** (`command_index(...,
  rate_is_ceiling=True)`), the same conversion 4b introduced, for the same
  reason — the battery's own remaining room binds above the command, so a
  rate above the plan still delivers exactly the plan, while nearest charges
  less. Fixes all 4. **Corpus cost: +0.00000 SEK, 0 of 38 fixtures moved** —
  it changes only what is written, not what is planned, so no golden or
  baseline re-pin.

  **The asymmetry with 4b is physical and worth keeping straight.** A
  discharge ceiling can be rounded up because actual house load binds below
  it. Nothing binds a *charge* command from above except the battery's own
  room — so where `import_cap_kwh` is what limited the plan (#429), rounding
  up would draw more than the house fuse allows. There the DP floors the plan
  onto the lattice instead (`execution_model.lattice_grid_charge`), which is
  safe because under-drawing never violates a fuse. That path is unexercised
  by the corpus (power monitoring is off in every fixture).

  **Rejected, with the measurement:** flooring *every* grid charge onto the
  lattice regardless of what bound it. Costs **+1.33 SEK** across the corpus
  and moves 11 fixtures, because charging less than the battery could compounds
  into lost arbitrage — the same shape as D3's +3.67 SEK. Flooring *all*
  charging (solar included) is worse still: 311 further periods and 3.70 kWh
  of storable solar discarded, for no fidelity gain, since SOLAR_STORAGE is
  commanded at a flat 100% and never rounds.

  **Left open, deliberately:** `_period_flows` still derives charge throughput
  from `max_charge_power_kw` rather than the commanded rate, so the inverter
  simulator cannot see a charge-rate divergence at all (it shares that record
  with the DP under P4). Also unfixed: one `SOLAR_EXPORT` period plans a
  0.0089 kWh charge against a deliberate 0% command (#313 blocks passive
  charging) — a sub-noise-floor plan/command inconsistency of a different
  kind. Both are worth their own measurement before anyone spends a phase on
  them; neither is worth SEK today.

4b and 4c are independent of each other and can run in parallel after 4a.

**Approved decisions (2026-08-11).** These name the modules, which per Global
constraints above *is* the `rules.md` new-class approval:

- **D1 — a new leaf module `core/bess/execution_model.py`** holds command
  derivation, the platform lattice mapping, and the intra-period discharge
  gate. Both `action_selector` and `simulation/inverter_simulator` depend on
  it; it imports nothing above itself. This **relocates
  `intra_period_discharge_gate` out of `battery_system_manager`**, which is
  the point — it is what lets the selector score a real command without the
  optimizer core importing the orchestrator, and without a third inverter
  model (P1). Rejected: putting it in `inverter_controller` (still inverts the
  layering) and letting the selector call a narrow subset (the third
  implementation, arriving by the back door).
- **D2 — a separate `PlatformCapabilities`**, not extra fields on
  `BatterySettings`. The latter is 17 fields of physical-battery facts with a
  different lifetime and source; `discharge_rate_is_load_following` already
  living on the controller is evidence the split is real.
- **D3 — decided 2026-08-14, SUPERSEDED the same day.** The share rule
  (`battery_to_grid > battery_to_home`, or already flat out) was decided on
  measured evidence and then demoted within hours by a `bess-analyst` second
  opinion sought before amending P7. **#352's root cause is a missing
  candidate, not a bad one:** at the field-evidenced period the action space
  offers 2.70 kW (under-covers the house, plans an import at buy 3.92) or
  3.30 kW (over-covers, exports at sell 2.63) — exact cover at 2.80 kW is off
  the percent lattice, the near-cover steps are removed by #497's band, and
  `_residual_cover_p` only fires *below* the smallest lattice step. The export
  is the least-bad option, not a choice; it is what makes the period a
  `BATTERY_EXPORT` and puts the inverter in the committing mode. Adding the
  exact-cover candidate measures **−3.12 SEK** (cheaper), takes committing
  exports from 52 to 19 and fixes the field case, against D3's **+3.67 SEK**
  which also leaves a phantom planned import. **No P7 amendment: with cover
  present the p99 margin collapses from 0.0388 SEK to 0.0067, inside its own
  epsilon — the decisiveness that motivated the amendment was an artifact of
  the missing candidate.** D3 survives only as optional cleanup for the 19,
  to be re-measured post-4a. Design doc §2 ("The root cause is a missing
  candidate") is normative here; §5 is history.

- [x] Design doc —
      `docs/superpowers/specs/2026-08-11-phase4-executable-candidates-design.md`.
      Candidate = executable command (mode + rate on the platform lattice +
      reactive semantics), evaluated by simulating that command against the
      forecast, via the shared `execution_model` leaf (D1) rather than a third
      implementation of inverter behaviour. Per-platform capability
      differences (percent lattice, VPP vs TOU, minimum gear) enter through
      `PlatformCapabilities` (D2), not hardcoded — #320's complaint.
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
      tests in as regression tests. Its author was told on 2026-08-11 that
      the materiality test survives as candidate scoring and the PR will not
      be rebased, so the trail from that work to the fix stays visible.
- [ ] Build the #352 reproduction fixture from a real bundle
      (`scripts/mock_ha/scenarios/from_debug_log.py`) and reconcile the 22/16
      figure. **Both gate 4b**; requested from the reporter 2026-08-11.

**Exit gate:** the corpus R==P gaps are at their floor; #320/#352
reproductions pass. *(Intent-as-input moved to Phase 5 — see below.)*

## Phase 5: Intent as input (was Phase 4d)

**Split out of Phase 4 on 2026-08-11.** `classify_strategic_intent` on planned
flows is deleted or reduced to observed-data use, and the chosen command
becomes the intent.

Removed from Phase 4 because it is not candidate-space work — it is a
vocabulary migration across the whole application, and bundling it would make
4b's and 4c's measured deltas unreadable. Blast radius, measured 2026-08-11:
**25 non-test Python modules** reference `strategic_intent` (every inverter
controller, `schedule_store`, `daily_view_builder`, the three debug exporters,
`backend/api.py`, `backend/ai_chat.py`, `api_dataclasses`) plus **10 frontend
files**, and since #544 it is pinned per period in the action-selector
goldens.

Depends on 4b and 4c: the command has to exist and be the thing chosen before
it can replace the classification.

**Phase 5's user-visible driver is #330** (identified 2026-08-11), which
otherwise reads as a display bug with no owner. A *recorded* period's
`strategic_intent` is the **planned** intent, not the observed one — the same
caveat #536 records for cost attribution ("only as good as plan-vs-execution
fidelity"). So whenever actual diverges from forecast, the label describes what
was intended rather than what happened: #330's "schedule says selling to grid,
energy flow does not", and the matching evidence from @Frank-Leysen on #126
("Solar Exporting" while grid-balanced and charging; IDLE while charging
3.3–3.5 kW after a solar-forecast undershoot). Reducing planned-flow
classification to observed-data use is what fixes that class; a labelling patch
in the UI would only move the disagreement.

## Parallel / deferred tracks

### Phase 3 follow-ups (recorded 2026-08-10, PR #534)

Five things Phase 3 found or left behind. Recorded here because until now
they existed only in code comments and commit messages, which nobody greps.

- [ ] **#536 — regime-aware charge-source split. MEASURED, NOT SCHEDULED —
      does not block a release.** Costs **+3.85 SEK** overstated across all
      30 bundles (26 periods, worst single +0.524 SEK) against the
      **+55.15 SEK** Phase 3 correctly attributes — ~7%, and in the safe
      direction, since an overstated basis makes the DP *less* eager to
      discharge. Not fixed because the only viable detection keys off
      `decision.strategic_intent`, which on a recorded period is the
      *planned* intent: the flows genuinely cannot distinguish
      "solar→home + grid→battery" from "solar→battery + grid→home" when all
      three are non-zero. That would couple historical cost accounting to
      plan-vs-execution fidelity to recover ~0.13 SEK/day. Revisit on
      evidence from a user who grid-charges heavily with concurrent PV.
      `EnergyData` allocates solar to the home first. That is right for
      `load_first` surplus charging and wrong during deliberate
      `GRID_CHARGING` (`battery_first`), where PV is DC-coupled straight to
      the battery and the house runs off the grid — so solar that really did
      charge the battery is booked to the home and the charge is booked
      entirely to the grid. Reproduced: `solar=2.0, home=2.0, charged=3.0,
      imported=3.0` → `s2b=0.0, g2b=3.0`, basis 1.40 where the truth is 0.73.
      Measured across the 30 bundles in `docs/`: **264 load_first charging
      periods / 191.1 kWh where Phase 3's fix adds 55.15 SEK of correctly
      attributed cost, against 26 GRID_CHARGING periods / 30.3 kWh where it
      overstates by 3.85 SEK** — a factor of 14, and the overstatement
      forfeits margin rather than losing money. Deliberately not fixed in
      Phase 3: keying the split off `decision.strategic_intent` decides which
      of two physically different topologies the accounting assumes, which is
      a modelling decision on a money path and wants its own evidence.
      **Caveat on that measurement:** recorded `strategic_intent` is the
      *planned* intent, so the split is only as good as plan-vs-execution
      fidelity. Site: `battery_system_manager._calculate_initial_cost_basis`.
- [ ] **P4's noise-model half is still open** — see the Phase 3 section. The
      one-flow-record half landed; gating the ingest heuristics did not.
      Needs an AC-aware candidate filter (`_discharge_is_unexecutable`
      computes its deficit pre-clipping), i.e. Phase 4 territory. Pinned by
      `test_planned_flows_still_pass_through_the_ingest_fold`, which should
      **flip** when the gate lands rather than be deleted.
- [ ] **`_state_transition`'s `ac_cap_kwh` is ambiguous.** `None` means both
      "no AC cap configured" and "caller forgot", so it cannot be asserted
      away (tried; four tests caught the attempt). A caller passing
      `import_cap_kwh` without it would compute `next_soe` under a different
      inverter limit than `_period_flows` derives for the same action.
      Nothing is presently wrong — `select_action` is the only caller passing
      an import cap and it passes the derived value. Remedy: derive the cap
      inside the function, as `_period_flows`/`_price_flows` now do. Deferred
      because this is the bit-parity-pinned physics core this plan says to
      refactor *around*; bit-parity would gate the change.
- [ ] **`_build_period_data` takes a `currency` argument it never reads.**
      Trivial, but removing it pulls `inverter_simulator.simulate`'s public
      signature into the diff, which is why Phase 3 left it and threaded the
      dead argument into `_create_idle_schedule` instead.
- [ ] **The simulator never applies `import_cap_kwh`.** Pre-existing, not a
      Phase 3 regression. A flows-only fix would be half a fix: its
      `_state_transition` call omits the cap too, so `next_soe` and the flows
      would disagree. Both call sites move together or neither does.

### Older tracks

- [x] **#487 — premise check DONE 2026-08-10; PARKED, not implemented.**
      The predicted signature is absent from the only bundle with enough
      history (`2026-08-04-203125`, 168 hourly entries = 7×24h). Overnight
      totals 00:00–05:59, night by night: 11.50 / 9.00 / 11.10 / 12.40 /
      9.60 / 10.80 / 10.70 kWh — non-monotonic noise around ~10.7, not the
      ratchet a self-reinforcing loop predicts (lowest night is the
      second, highest the fourth). The magnitude does not fit either: the
      issue puts inverter self-consumption at ~50% of night load "at low
      overnight power levels", but that house averages 1.8 kW overnight,
      so standby draw is 1–3%. **Not a refutation** — the reporting
      system's own bundle carries only 14 hourly entries and logs `No
      statistics data returned ... in the past 7 days`, so the premise is
      untested on the low-consumption house where it was observed and
      cannot be tested from anything available. Needs a bundle with ≥7
      days of `lifetime_load_consumption` statistics *and* battery state
      over the same window. Measurement posted on the issue. **This is the
      premise check paying for itself: no fix was built.**
- [x] **#526 — DONE, merged as PR #530 (2026-08-10).** The gate decision
      moved into the DP (`_record_marginal_value`), recorded as
      `DecisionData.intra_period_discharge_allowed`; `shadow_price` is
      reporting-only and no consumer derives a decision from it. Measured:
      353/2168 periods (16.3%) no longer authorize, of which only **115**
      are on gate-consulting intents (SOLAR_EXPORT 105, SOLAR_STORAGE 10);
      **cost bit-identical on 36/36 fixtures** (`dR = +0.000000`) because
      those periods sit at the reserve floor with nothing to discharge.
      Observed end-to-end on mock-HA: at floor SoE the written
      `discharging_power_rate` goes **100 → 0**, schedule payload
      byte-identical, and at 60% SOC both branches still write 100.
      Beyond the reported bug it also closed `_create_idle_schedule` (the
      numerical safety net has no value function at all, yet
      `classify_strategic_intent` can label its periods SOLAR_EXPORT) —
      found in code review, not in the issue. **#520 is now unblocked.**
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

**Revised 2026-08-10.** Phases 0–2 are done; the remainder was reordered
on the measurements recorded above, not on a re-reading of this plan.

```
Phase 0 (drain WIP)           — ✅ DONE
   ▼
Phase 1 (one selector)        — ✅ MERGED #521, bit-parity held
   ▼
Phase 2 (preference table)    — ✅ MERGED #525 (P6 rider deferred)
   ▼
#487 premise check            — ✅ DONE 2026-08-10. Premise NOT confirmed
   │                            on available data; PARKED, no fix built.
   ▼
#526                          — ✅ MERGED PR #530. 36/36 fixtures
   │                            cost-identical; register 100→0 at floor.
   │                            #520 unblocked.
   ▼
Phase 3 (one flow record)     — ✅ MERGED #534. Bit-parity held on all 36
   │                            fixtures through every task. Live fix: BSM
   │                            booked 48.9 kWh of grid charging as free
   │                            solar across 15 of 30 REAL bundles, 66%
   │                            basis understatement on the pinned day.
   │                            Task 5 (noise-model gate) withdrawn — see
   │                            Phase 3 follow-ups.
   ▼
#520 → #524                   — TOU half MERGED (#524). VPP half (#537)
   │                            WITHDRAWN 2026-08-11, design defect: it
   │                            mapped gate-closed to a battery_first hold,
   │                            which delivers NOTHING, where TOU's
   │                            gate-closed still delivers the plan and only
   │                            declines to raise the ceiling. All 172
   │                            gate-closed LOAD_SUPPORT periods carry a
   │                            planned discharge — 118.11 kWh abandoned.
   │                            Root cause: VPP carries BATTERY_EXPORT's
   │                            planned magnitude faithfully but collapses
   │                            LOAD_SUPPORT's 101 rates to 1 command, so
   │                            "deliver the plan, no more" is inexpressible
   │                            there. Redesign needs the load-tracking
   │                            power adjustment (ridax67, #520) — which is
   │                            also #352's fix, i.e. Phase 4b work.
   ▼
#539 VPP simulation + v10.0.2 — NEW GATE, before Phase 4. No VPP simulation
   │  baseline                   exists, so "no regression from beta" is
   │                            unenforceable for Growatt VPP. Pin the
   │                            released tag, then compare per phase.
   │                            Folds in #538. Phase 4 changes VPP command
   ▼                            generation, so the baseline must precede it.
Phase 4 (command candidates)  — 4a capability → 4b discharge cmds →
   │                            4c charge cmds → 4d intent-as-input.
   │                            Driver is #352 (+#354's band); #320 is
   ▼                            closed and only regression cover.
P6 splice cost-gate           — LAST. Measured: every delta ≤ 0 across
                                36 fixtures, so it would never fire
                                today. Insurance, not recovered money —
                                or take the alternative: disable
                                splicing and fix #513.

#513 fix when touched; #512 sweep-gated; both may run between phases.
```

**Why this differs from the original order.** Phase 3 moved earlier than
its dependencies would suggest because its re-scoped acceptance
(bit-parity) is independent of every open behavioral question, so it can
land while #520/#524 are still being settled. #487 and #526 jumped the
queue because one is a cheap premise check and the other is a live defect
blocking the Phase 4 gate. P6 fell to last on measurement alone.
