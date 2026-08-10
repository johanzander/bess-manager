# Phase 3 — One Flow Record (P4): Detailed Plan

> **Parent:** `2026-08-09-optimizer-target-architecture.md`, Phase 3
> (re-scoped 2026-08-10). Read that phase and `docs/agents/optimizer-architecture.md`
> (P4 is normative) before starting. Base every branch on `origin/main`.

**Phase 3 is a consolidation refactor, not a behaviour fix.** Its original
acceptance — drive flow-coherence violations to zero — is already satisfied
(0 incoherent periods across the corpus). The payoff here is P4 compliance
and removing duplicated physics, plus **one genuinely live economic defect**
found while mapping (Task 4). Do not oversell it and do not let it grow.

---

## Task 0 (MANDATORY FIRST): re-measure on current `origin/main`

The survey this plan is built on was run against a **stale checkout**
(`bc5cafa6`, the merged `pr521` branch the main working tree was parked on)
— roughly ten commits behind, missing **Phase 2 (#525)** and **the #526 fix
(#530)**, and covering **32 fixtures where main has 36**.

Its *structural* findings were re-verified by hand against `origin/main` and
hold (see Appendix A). **Every number it reported must be re-derived before
you rely on it.** Tie-related figures are the least trustworthy: Phase 2
replaced tie resolution outright, so any pre-#525 tie measurement describes
code that no longer exists.

Re-measure and record in the PR body:

- [ ] Fixture count and total planned periods (expect 36 fixtures).
- [ ] Deviation between `_compute_reward` and `_build_period_data` for
      `grid_imported` and wear cost, across all fixtures. *Stale claim: 0.0
      and ≤6.7e-16 respectively.* If they still agree exactly, the
      consolidation is hygiene, not a bugfix — say so plainly.
- [ ] Count of bit-exact ties and near-ties (gap < 1e-12) between
      **behaviourally different** candidates in `select_action`. *Stale
      claim: 46 knife-edge decisions out of 2194 calls, pre-Phase-2.* This
      number sizes the bit-parity risk; get it right before refactoring
      arithmetic.
- [ ] How many fixtures trigger the idle guardrail. *Stale claim: 0 of 32.*
      Task 3 depends on this being 0.
- [ ] How often the `EnergyData` heuristics (`models.py` fold and the two
      non-invention clamps) fire on **planned and simulated** data. *Stale
      claim: 0.* Task 5 is only safe while this is 0.

If any re-measurement contradicts the stale figure materially, **stop and
re-scope** rather than proceeding on this plan's assumptions.

### Task 0 results — measured 2026-08-10 on `a81ac613`

| Measurement | Stale claim | Re-measured | Verdict |
|---|---|---|---|
| Fixtures / planned periods | 32 fixtures | **36 / 2168** | as expected |
| `_compute_reward` vs `_build_period_data`, `grid_imported` | 0.0 | **0.0** (0 of 2461 rows differ) | confirmed |
| Same, wear cost | ≤6.7e-16 | **≤6.661e-16** (42 of 2461 rows) | confirmed |
| Knife-edge selections | 46 / 2194 | **56 / 2194** (29 bit-exact + 27 <1e-12) | see below |
| Fixtures firing the idle guardrail | 0 of 32 | **0 of 36** | confirmed |
| `EnergyData` heuristic firings on planned data | 0 | **0** | confirmed |

No re-measurement contradicted the plan materially, so the scope stands.
Two notes on the details:

- **`grid_imported` agrees exactly, so the consolidation is hygiene, not a
  bugfix** — stated plainly as this task requires. The only deviation
  between the two sites is the wear term's two algebraically-identical
  formulations, at float-noise magnitude.
- **The knife-edge count is higher than the stale figure, not lower**, and
  the stale definition was not reproducible anyway (Phase 2 replaced tie
  resolution). Measured here against the question that actually matters for
  bit-parity: how often is the strict-`>` argmax decided by a gap under
  1e-12 against a candidate the goldens would record *differently* (in
  `power` or `next_soe`). 56 is a risk figure, and it argues *harder* for
  the plan's "do not re-associate the reward arithmetic" instruction. For
  contrast, ties by the codebase's own ambiguity criterion
  (`TIE_DEDUP_SOE_KWH`, 1.0 kWh) number only 4.

---

## Acceptance gate (whole phase)

**Golden bit-parity**: byte-identical `actions` and `soe_trajectory` for
every fixture in `core/bess/tests/unit/data/`, via the Phase 1 machinery
(`core/bess/tests/unit/golden_capture.py`). Reuse it; do not invent a second
comparison harness.

Two documented exceptions, each of which must be stated with its measured
value in the PR body rather than silently absorbed:

1. **Task 3** changes `cost_basis` on the idle-guardrail path (stale
   measurement: 0.05 SEK/kWh max divergence). Safe for `actions` /
   `soe_trajectory`; only observable if the guardrail fires.
2. **Task 4** changes live cost-basis input. It is a *fix*, so a corpus
   delta is expected — measure it, don't hide it.

`assert_flow_coherence` (`core/bess/tests/helpers.py`) must stay green
throughout. It is the floor, not the goal.

---

## Task 1 — introduce `PeriodFlows`, produced once

**Files:** `core/bess/dp_battery_algorithm.py`, `core/bess/action_selector.py`

One record carrying **flows only** — no prices, no costs:

```
solar_to_battery, grid_to_battery, battery_charged, battery_discharged,
grid_imported, grid_exported, clipped_solar, energy_stored
```

**Costs must NOT go on this record.** The reward is computed at the #269
floored `reward_sell_price` while reporting uses the real `sell_price`; a
single costed record would collapse that distinction and regress #269. The
record carries flows; each consumer prices them.

- [ ] Extract the charge-split / AC-flow math into one helper that
      `_compute_reward` and `_build_period_data` both call, returning
      `PeriodFlows`.
- [ ] Store it on `Candidate` (`action_selector.py`).
- [ ] `_build_period_data` consumes the record instead of recomputing.
- [ ] Bit-parity gate green.

**Do not re-associate the reward arithmetic.** Keep the current term order
and the in-place `grid_imported += grid_to_battery`. A "compute once, then
multiply out" rewrite moves ULPs, and Task 0's knife-edge count is exactly
the population that flips when it does. Enumeration order in
`select_action` is also load-bearing (strict `>`, first-wins) — do not
reorder `consider()` calls.

**Export both wear formulations or accept a cost-digit delta.**
`_compute_reward` uses `(s2b+g2b)*eff*cycle`; `_build_period_data` uses
`max(0, next_soe-soe)*cycle`. Algebraically identical, different float
paths. `actions`/`soe_trajectory` are unaffected (wear enters the objective
only via `_compute_reward`), so the stated acceptance survives either way —
but any byte-identical assertion on `battery_cycle_cost` / `hourly_cost` /
`battery_solar_cost` will not.

## Task 2 — `_replay_accounting_pass` consumes stored records

**Files:** `core/bess/dp_battery_algorithm.py`, `core/bess/schedule_splicer.py`

- [ ] Widen `splice_schedule`'s payload to carry the record alongside
      `(action, next_soe)`.
- [ ] Replay consumes stored records instead of re-deriving.
- [ ] Bit-parity gate green.

Keeping the recompute here means P4 is only half-satisfied — widening the
splicer is the honest option. If it proves disproportionate, say so in the
PR and leave Task 2 out rather than faking it.

## Task 3 — collapse `_create_idle_schedule` onto the same record

**File:** `core/bess/dp_battery_algorithm.py`

A fourth independent copy of the IDLE physics, which already disagrees with
`_compute_reward` on cost basis (it charges the full
`battery_charged * sell_price` as solar opportunity cost; `_compute_reward`
discounts the share that would have been AC-clipped anyway).

- [ ] Collapse onto the shared record + `_build_period_data`.
- [ ] State the `cost_basis` correction as an **intentional, measured fix**,
      not a parity claim.
- [ ] Confirm (Task 0) the guardrail fires on 0 fixtures, so nothing
      observable moves.

## Task 4 — fix the live cost-basis defect (highest value in the phase)

**File:** `core/bess/battery_system_manager.py`

`_calculate_initial_cost_basis` derives its own charge-source split:

```
solar_to_battery = min(battery_charged, solar_production)          # BSM
solar_to_battery = min(solar_production - solar_to_home, battery_charged)  # EnergyData
```

The BSM form ignores the house load, so solar already consumed at home is
counted again as having charged the battery. Worked case: `solar=3.0,
home=2.0, battery_charged=2.0, grid_imported=1.0` → EnergyData `s2b=1.0,
g2b=1.0`; BSM `s2b=2.0, g2b=0.0`. **1 kWh of grid charging is booked as free
solar**, and the result feeds `optimize_battery_schedule(initial_cost_basis=…)`.

- [ ] Re-derive the disagreement on current main and confirm it still holds.
- [ ] Make both this and the energy-balance log table read
      `event.energy.solar_to_battery` / `.grid_to_battery` instead of
      re-deriving.
- [ ] Measure the corpus delta. **A cost change here is expected and
      correct** — pin it, state it, don't suppress it.

This is the one live economic defect in the inventory. If the phase has to
be cut short, do this task.

## Task 5 — make exact-vs-ingested explicit at the model layer

**File:** `core/bess/models.py`

`EnergyData._calculate_detailed_flows` contains three ingest heuristics —
the #350 sub-resolution export fold and two "don't invent a flow to
reconcile independent counters" clamps. They currently run on **planned and
simulated** flows too, which is a literal P4 violation ("planned and
simulated flows must never pass through a noise model").

- [x] **ATTEMPTED AND BACKED OUT 2026-08-10 — the premise failed.** Its own
      gating condition was "a zero-behaviour-change compliance move", and it
      is not one.

      Two of the three are not noise heuristics at all: the `grid_to_home`
      and `battery_to_grid` clamps are **physical bounds** (a flow cannot
      exceed its source). Gating them let an exact record attribute more
      export to the battery than the battery discharged — inventing energy,
      the opposite of the non-invention rule. They stay unconditional.

      The third, the #350 fold, genuinely is a noise model, but bypassing it
      **is** a behaviour change and it reaches hardware. Whenever
      `ac_cap < home_consumption < solar_production`, `_discharge_is_unexecutable`
      (#497) stands down — it computes its deficit as `home - solar`, from
      RAW solar, blind to AC clipping — while the AC stage still leaves the
      battery covering a deficit it can overshoot by less than
      `GRID_FLOW_RESOLUTION_KWH`. Ungating the fold there flips planned intent
      LOAD_SUPPORT → BATTERY_EXPORT, which `inverter_controller` maps to
      `grid_first`: the export feedback loop `battery_system_manager`
      documents. Constructed and confirmed, not hypothesised.

      Task 0's "0 firings on 2168 planned periods" was weak cover: only 4 of
      36 fixtures have an AC cap at all, and a 2170-run sweep over caps
      2–10 kW found 0 hits **but never entered the `ac_cap < home` regime**,
      which is the only regime where the band is reachable.

      **The P4 violation therefore still stands on `main`**, documented by
      `test_planned_flows_still_pass_through_the_ingest_fold`. Closing it
      needs an AC-aware candidate filter — a candidate-space change, i.e.
      Phase 4 — not a model-layer flag. That test should flip when the gate
      finally lands, not be deleted.
- [x] Ingest semantics untouched, as required.

## Task 6 — correct the parent plan's own claims

**File:** `docs/superpowers/plans/2026-08-09-optimizer-target-architecture.md`

- [ ] "Six flow derivations" is wrong. Replace with the re-measured figure
      from Task 0 (the survey counted seven genuine planning/reporting
      derivations and ~20 sites overall, of which only ~6 are true
      duplicates).
- [ ] Its `EnergyData` construction-site list is stale: `debug_data_exporter.py`
      and `influxdb_helper.py` construct none; it misses
      `prediction_snapshot.py`, `daily_view_builder.py`, and both
      `battery_system_manager` splits.
- [ ] Its claim that noise heuristics live only in `sensor_collector.py` is
      false — they are also in `models.py` and `energy_flow_calculator.py`.

---

## Explicitly OUT of scope

- **The numpy mirrors** (`_compute_reward_grid`, `_state_transition_grid`,
  `_ac_flows_grid`) and the backward passes. P1(a) permits the backward pass
  its own evaluator; they are pinned by `test_vectorized_backward_parity.py`,
  and their candidate-space divergence is deliberate and measured.
- **`EnergyData`'s ingest semantics.** Required by measured data.
- **`EconomicData.from_energy_data`.** Must stay a separate price-taking step
  (see #269 above).
- **The simulator's charge-rate defect** — `mode_to_power` computes a
  rate-scaled charge power that `_state_transition` then discards, so
  `charge_rate_pct` 25/50/100 all produce identical flows. That is a **Phase
  4 (P3)** defect. Phase 3 only ensures `PeriodFlows` *can* express a
  command-derived flow set. Note it for #320/#352; do not fix it here.
- **Tie policy.** Phase 2 has landed; `_prefer_*` now live in
  `tie_policy.py`. There is no Phase 2 sequencing conflict — the stale
  survey claimed otherwise.

## Per-task workflow

Each task is its own commit; Tasks 1+2 may share a PR, Tasks 3/4/5/6 should
be separable so a problem in one doesn't block the rest. For every PR:
`./scripts/quality-check.sh`, fast suite, slow suite, bit-parity gate,
`/code-review` with CONFIRMED findings treated as blockers, and the
documentation check (`docs/agents/bess-knowledge.md`, `docs/SOFTWARE_DESIGN.md`,
`docs/agents/simulator.md`) — Task 4 in particular changes a documented
mechanism.

---

## Appendix A — what was verified by hand on `origin/main` (2026-08-10)

| Claim | Verdict |
|---|---|
| `_prefer_*` live in `tie_policy.py`; Phase 2 landed | **TRUE** — survey said the opposite |
| Charge-split math duplicated across scalar + numpy paths | **TRUE** — copies still present |
| Fixture corpus size | **36**, survey said 32 |
| `tie_policy.py` exists | **TRUE** |
| All quantitative measurements | **UNVERIFIED** — computed on the stale tree; redo per Task 0 |
