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
| 3 | #459-class; collapses the six flow derivations into one record. **No longer closes #497** — #511 already did | 2 | re-scoped 2026-08-10 |
| 4 | #352 residual, #354 (parked — right problem, wrong layer), #466 crossover regression cover, #511-class recurrence, #320 regression cover | 2 | gated on #520/#524 |
| prerequisite | #526 (live latent defect; blocks #520 → #524 → Phase 4's R==P claim) | 2 | next |
| parallel | #487 (input quality — premise check first, independent) | 1 input | next |
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
> What remains is real but different: the **six flow derivations are still
> six**, and collapsing them into one per-candidate record is a
> consolidation refactor, not a behavior change. Plan and gate it as such.
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
- [ ] **Acceptance — golden bit-parity across every fixture in
      `core/bess/tests/unit/data/`**, reusing Phase 1's
      `golden_capture.py` machinery and its regeneration discipline. Any
      non-zero delta means the consolidation changed behavior: state the
      measured value in the PR body and justify it against the 0.05
      SEK/fixture budget, or fix it. `assert_flow_coherence` must stay
      green throughout (floor, not goal — it is already at 0/2168).
- [ ] Full + slow + E2E per the detailed plan; draft PR; `/code-review`.

**Exit gate:** bit-parity holds; no reward-only or flows-only code path
survives (`P4` compliance grep in the PR body); the six flow derivations
are one.

## Phase 4: Executable-command candidates (P3)

**The one genuinely medium-sized project. Scope to acceptance level —
first step is its own design doc + detailed plan (this is a
`brainstorming` → `writing-plans` sequence, and rules.md's new-class
approval applies).**

### Is Phase 4 subsumed by #511/#517? No — measured 2026-08-10

One session argued Phase 4 had been overtaken by the #511/#517 fixes. It
had not, and the counter-evidence is static and re-checkable rather than
inferential — re-run these two greps before reopening the question:

- **The plan charges at nominal power in seven hardcoded places.**
  `rate_throughput = battery_settings.max_charge_power_kw * dt` appears at
  `dp_battery_algorithm.py:306,339,377,475,589,728` and
  `pwl_window_dp.py:537`.
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

**Phase 4's live driver is #352, not #320.** #320 is closed (see the issue
map). Measured for #352: 22 sub-load `grid_first` periods live, **16 of
them in the 0.1–0.5 kWh band #511 does not reach**, 5 clearly
spike-exposed.

### Gating

Phase 4's central claim is that R==P becomes structural. Two open issues
decide what R==P even means at the boundary, so **settle them first** —
`#526` → `#520` → `#524` (`#524` is already labelled `[BLOCKED]` on
`#520`, and `#520`'s discharge gate opens unconditionally where
`shadow_price == 0.0` is ambiguous between "worth nothing" and "never
computed", which is #526). Building Phase 4 on an unsettled gate means
encoding the ambiguity into the candidate space.

### Split into four shippable PRs

The design doc's first job is to confirm this split, but the default is:

- **4a — capability model.** Per-platform lattice/mode/minimum-gear into
  `BatterySettings`/platform config; no candidate changes yet.
- **4b — discharge commands.** Candidates become executable discharge
  commands; folds in #511/#517's tests as regression cover.
- **4c — charge commands.** The seven hardcoded `rate_throughput` sites
  above collapse to the configured rate; this is where the measured R≠P
  divergence closes.
- **4d — intent as input.** `classify_strategic_intent` on planned flows
  is deleted or reduced to observed-data use.

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

- [ ] **#487 — premise check FIRST, then decide (next up).** Consumption
      statistics must account for inverter self-consumption while the
      battery sleeps. **Its own body calls the mechanism unverified**, so
      the first step is verification, not implementation, and it is the
      cheapest high-expected-value move on the board: *does measured
      overnight load actually drop when the inverter sleeps?* Measure that
      against real bundles before writing any fix. If the premise fails,
      the fix is wrong regardless of how well it is built — this is the
      same discipline that turned Phase 0's fold-scoping item from a
      −5.51 SEK/day "win" into PR #511. Only if the premise holds does
      this route through `implement-issue`. Independent of every phase.
- [ ] **#526 — live latent defect, and the gate on Phase 4 (next up).**
      `shadow_price == 0.0` is ambiguous between "worth nothing" and
      "never computed", and the discharge gate opens unconditionally
      there. Fix before #520, which is before #524 (already `[BLOCKED]`
      on it), which is before Phase 4 can claim R==P is structural.
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
#487 premise check            — verification, not implementation;
   │                            cheapest high-EV move. Parallel-safe.
   ▼
#526                          — live latent defect; gates #520 → #524
   ▼
Phase 3 (one flow record)     — RE-SCOPED: consolidation refactor,
   │                            acceptance = golden bit-parity
   ▼
#520 → #524                   — settle before Phase 4 encodes the
   │                            ambiguity into the candidate space
   ▼
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
