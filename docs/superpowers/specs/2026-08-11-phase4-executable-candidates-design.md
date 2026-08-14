# Phase 4: Executable-command candidates (P3) — design

**Status: all four decisions settled — D1, D2, D4 approved 2026-08-11; D3
decided 2026-08-14.** Phase 4's plan entry requires a design doc before code
and says `rules.md`'s new-class approval applies — the modules named in D1 and
D2 below carry that approval.

**4a is startable and 4b is unblocked on design.** Its non-code preconditions
— the #352 reproduction fixture and the 22/16 reconciliation — landed
2026-08-13 (§2), and D3's predicate is chosen and measured (§5). Both now wait
only on the beta shipping (§7). 4d has been removed from Phase 4 entirely and
is now Phase 5 in the parent plan.

Parent: `docs/superpowers/plans/2026-08-09-optimizer-target-architecture.md`
→ Phase 4. Normative: `docs/agents/optimizer-architecture.md` (P1–P7).

---

## 1. What Phase 4 changes

Today a DP candidate is an abstract power figure in kW. The planner picks one,
and a separate mapping layer later turns it into an inverter command — a mode
plus a percentage on that platform's lattice. Nothing guarantees the command
can express what the plan assumed, and the two places that decide have drifted
apart repeatedly (#282, #497, #511, #537).

P3's answer: **a candidate *is* an executable command** — mode, rate on the
real platform lattice, and its reactive semantics — scored by simulating that
command against the forecast. If the hardware cannot express an action, it is
not in the action space, so it cannot be planned.

Strategic intent stops being a classification computed from planned flows and
becomes the chosen command itself.

---

## 2. Evidence, re-verified on `main` 2dcd540f

The plan asks for two greps to be re-run before reopening the "is Phase 4
subsumed by #511/#517?" question. Both were run 2026-08-11.

**The plan still charges at nominal power — but in 6 places, not the 7 the
plan records.** Phase 3's restructuring moved them:

```
core/bess/dp_battery_algorithm.py:355, 475, 508, 546, 644
core/bess/pwl_window_dp.py:543
```

**The load-bearing half is unchanged.** `charging_power_rate` has **zero**
occurrences in `dp_battery_algorithm.py`, `pwl_window_dp.py` and
`action_selector.py`, while `battery_system_manager.py:3442` writes exactly
that value to the inverter. The planner assumes a charge throughput the
executor is configured not to deliver. That is a structural R≠P divergence on
the charge path, untouched by #511 and #517 (both discharge-side). **Phase 4
stands.**

### The #352 evidence reproduces — the earlier 0 was a tautology (resolved 2026-08-13)

The 2026-08-11 revision of this section recorded "0 periods" and called it a
blocker. **That measurement was vacuous.** Both halves are now reconciled by
running every criterion over all 36 fixtures, on `main` post-#545.

**The 22/16 figure is real and reproduces bit-exactly.** Its criterion is a
BATTERY_EXPORT period whose *planned battery discharge* is below the period's
*home consumption*: **22 periods, 16 of them with planned export in the
0.1–0.5 kWh band.** Both numbers match 2026-08-10 exactly, so nothing has
regressed or been silently fixed since.

**The 0 came from reading "below the house deficit" literally, and that count
is 0 by construction.** `EnergyData._calculate_detailed_flows` sets
`battery_to_home = min(battery_discharged, home − solar)`, so
`battery_to_grid > 0` *requires* `battery_discharged > deficit`. A scan for
BATTERY_EXPORT periods discharging below the deficit measures the flow
derivation's own identity, not the corpus. Measured: 0, exactly as the algebra
demands. **A zero of that shape is never evidence about a bug.**

Measured together over the 232 BATTERY_EXPORT periods in the corpus (37
fixtures, i.e. including the new reproduction fixture below; the 22/16 row is
identical on the 36 that predate it):

| criterion | count | in 0.1–0.5 kWh band |
|---|---|---|
| planned discharge < home consumption (**the 22/16 figure**) | 22 | 16 |
| planned export < house deficit (≡ home-dominant) | 60 | 49 |
| forfeited headroom > planned export | 103 | 87 |
| **#354's two readings both failing: home-dominant AND headroom > export** | **50** | **48** |
| planned discharge < house deficit (the vacuous scan) | **0** | 0 |

Note which of these is the exposure metric. Planned *import* in a
BATTERY_EXPORT period is identically zero on 15-minute point forecasts — the
corpus cannot show the harm, per "What the corpus is" in the parent plan. What
it can show is the **commitment**: 103 periods commit the inverter to
`grid_first` while forfeiting more load-following headroom than the export
they defend, and 50 fail both of #354's readings at once. That is the
quantity D3 discriminates on (§5) — though note it discriminates by *share*,
not by size: the counts above are the exposure, not the rule.

**Reproduction fixture: landed.** `regression_2026_08_12_202906` (from the
maintainer's 2026-08-12 Growatt MIN bundle, the four-period hardware
reproduction on the issue). Its period 99 carries the shape: 0.825 kWh
discharged against 0.700 kWh home, **0.125 kWh planned export defended at the
cost of 2.925 kWh of forfeited headroom** — a 22% rate command, the same gear
as the live period 78. `expected_results` is pinned PRE-fix on purpose; 4b
moves it and states the delta.

### #352 is two bugs; only one is Phase 4's

Split recorded on the issue 2026-08-11. **Shape A** (LOAD_SUPPORT throttled
below house load) is gatable and was addressed by #520/#524 — pending hardware
verification. **Shape B** (low-rate BATTERY_EXPORT on `grid_first`) cannot be
gated at all: `grid_first` does not load-follow, so raising its ceiling means
"export at full rate", which is #324. Shape B is Phase 4's.

---

## 3. The constraint the plan did not anticipate

The plan says to evaluate candidates by "reusing
`simulation/inverter_simulator.derive_control_command`/`simulate` logic in the
selector rather than a third implementation of inverter behavior." That is
right in spirit — a third implementation is exactly what P1 forbids — but it
cannot be done literally as an import.

```
core/bess/simulation/inverter_simulator.py
    imports  core.bess.battery_system_manager  (intra_period_discharge_gate)
    imports  core.bess.inverter_controller     (InverterController)
```

So `action_selector` importing `inverter_simulator` would make the **optimizer
core depend on the top-level orchestrator**. That inverts the layering: the DP
would import the thing that runs the DP.

The graph is already strained. `dp_battery_algorithm:1201` performs a
*function-local* import of `action_selector`, with a comment stating it is
deferred "because action_selector imports this module" — an existing cycle
already being worked around. Adding a second, wider one on top is how that
workaround becomes permanent.

Per `rules.md`'s workaround check, the fix is not another deferred import. It
is to extract the execution model into a **leaf module** that imports nothing
above it, and have both the selector and the simulator depend on that. Doing so
requires moving `intra_period_discharge_gate` out of `battery_system_manager`.

**This is Decision D1 below and it needs approval — it creates a module, moves
a public function, and touches the simulator's import surface.**

---

## 4. Proposed split (the plan's default, confirmed)

| PR | Scope | Depends on | Status |
|---|---|---|---|
| **4a** | `PlatformCapabilities` + the `execution_model` leaf: per-platform lattice, modes, minimum gear, load-following semantics; gate relocated. No candidate changes. | D1, D2 | **startable** |
| **4b** | Discharge candidates become executable commands, with D3's admissibility rule as the export filter. Closes #352 Shape B. Folds #511/#517 tests in as regression cover. | 4a, the beta (D3 decided, fixture landed) | blocked on 4a + beta |
| **4c** | Charge candidates become executable commands — the 6 `rate_throughput` sites collapse to the configured rate. This is where the measured R≠P divergence closes. | 4a, the beta | blocked on 4a |

4b and 4c are independent of each other and can run in parallel after 4a.
**4d is no longer part of Phase 4** — it is Phase 5 in the parent plan (D4).

---

## 5. Decisions

**D1 — Where does the execution model live? ✅ APPROVED 2026-08-11: option (a).**
A **new leaf module `core/bess/execution_model.py`** holds command derivation,
the platform lattice mapping, and the intra-period discharge gate. Both
`action_selector` and `simulation/inverter_simulator` depend on it; it imports
nothing above itself. This **relocates `intra_period_discharge_gate` out of
`battery_system_manager`** — that relocation is the substance of the decision,
not a side effect, because it is what lets the selector score a real command
without the optimizer core importing the orchestrator and without a third
inverter model (P1).

Rejected: (b) putting the logic in `inverter_controller` — the DP importing a
controller still inverts the layering, just less visibly; (c) letting the
selector call a narrow dependency-free subset — that is the third
implementation P1 forbids, arriving by the back door.

**D2 — Does the capability model belong in `BatterySettings`? ✅ APPROVED
2026-08-11: no, a separate `PlatformCapabilities`.** `BatterySettings` is 17
fields of physical-battery facts sourced from user config; a percent lattice,
mode vocabulary, minimum gear and load-following semantics are platform facts
with a different lifetime and source. `discharge_rate_is_load_following`
already living on the controller is evidence the split is real rather than
tidy-minded. Folding them in would also overload an object passed through
almost every function in the optimizer.

**D3 — What is "dominance OR forfeited headroom", concretely? ✅ DECIDED
2026-08-14** (owner's criterion, chosen from six measured alternatives).

**The rule.** A `grid_first` export command is admissible iff the period is
*mostly about exporting* — or the battery is already flat out, where there is
nothing left to protect:

```
admit  iff  battery_to_grid > battery_to_home        # the period is an export
       or   headroom <= one rate step                # already at full gear
                                                     # headroom = max_discharge*dt - discharge
```

**What it distinguishes, in one sentence:** is the export the point of the
period, or a by-product of covering the house? Two periods that are
indistinguishable by rate are separated cleanly by share:

| | discharge | to grid | to house | export share | verdict |
|---|---|---|---|---|---|
| arbitrage remainder (owner's case, h0) | 5.0 kWh @ 50% | 4.5 | 0.5 | **90%** | admit |
| #352 leakage (repro p99) | 0.825 kWh @ 22% | 0.125 | 0.700 | **15%** | reject |

**No invented constants.** "Mostly" is the 50/50 split — a boundary, not a
tuned threshold. "Flat out" is the top of the platform's own percent lattice.
Contrast the rejected alternatives below, each of which needed a number
somebody had to choose.

**The full-rate exemption is load-bearing, not a caveat.** Bare dominance
costs **+15.24 SEK** on the corpus; adding the exemption drops that to
**+3.67 SEK**. Measured cause: 8 of the 60 periods bare dominance rejects are
at full rate and carry 31.5 of the 50.3 SEK at stake. At full rate there is no
load-following capacity left, so demoting forfeits revenue and buys nothing.
This is #354's live-E2E lesson (a near-full-rate spike export has nothing to
protect), re-derived independently here.

### The alternatives, measured as real candidate filters

Every rule below was run as a filter inside `select_action`, with the DP
**re-optimising** — so "corpus cost" is what the optimizer actually achieves
under the restriction, not revenue counted on a plan the restriction would
have changed. "Exposure" is `buy_price × forfeited headroom` summed over the
surviving `grid_first` periods: a worst-case comparison scale, not a predicted
saving.

| rule | owner's h0 | p99 removed | corpus cost | exposure left |
|---|---|---|---|---|
| baseline (today) | — | no | 1796.11 | 437.5 |
| **dominance, unless flat out (CHOSEN)** | **kept, +0.00** | **yes** | **+3.67** | **242.9** |
| #354 two-sided (dominance OR headroom) | kept, +0.00 | yes | +2.66 | 252.9 |
| dominance, bare | kept, +0.00 | yes | +15.24 | 243.4 |
| harm/benefit at a 2 kW excursion | kept, +0.00 | yes | +4.36 | 171.6 |
| dominance AND harm/benefit | kept, +0.00 | yes | +19.31 | — |
| **top gear only — REFUTED** | **LOST, +6.75** | yes | +2.47 | — |

+3.67 SEK is **0.14% of the corpus's 2600.8 SEK of savings**.

### Why "top gear only" was refuted, and why that mattered

The first proposal was parameter-free and wrong: admit `grid_first` only at
the largest feasible discharge. The owner refuted it with a constructed case
before any code was written, and the case is now permanent (§6).

With a fixed energy budget and a per-period power cap, the optimum puts every
exporting period at a cap **except exactly one**, which absorbs the remainder —
and that one lands in the *cheapest* exporting hour. Forbidding it does not
make the remainder disappear. Measured on the case: the rule moved 4.5 kWh
from the 2.00 SEK/kWh hour to a **0.50 SEK/kWh** hour, losing 6.75 SEK of
94.25 (7%), and produced a *new* 45% partial-rate export while doing so. It
did not even achieve its own goal.

Recorded because the aggregate hid it: the same rule measures −0.095% across
the corpus, which contains few energy-rich, cap-limited export days. **A corpus
average is not a substitute for a constructed adversarial case.**

### What this deliberately does not fix

131 partial-rate `grid_first` periods survive, because they are genuinely
export-dominant — the owner's h0 among them. They still carry spike exposure.
The rule does not eliminate exposure; it eliminates exposure **the plan is not
being paid for**. `grid_first` is for true arbitrage, and true arbitrage
accepts the commitment.

**Structural, not stochastic** (P7): no distribution over load, no forecast
variance, no reference excursion. The comparison is between two flows the plan
already computes.

**Applies only where `discharge_rate_is_load_following`** (#324). VPP-style
platforms have no load-following behaviour to demote to and are untouched.


**D4 — What happens to `strategic_intent` consumers? ✅ APPROVED 2026-08-11:
removed from Phase 4, becomes Phase 5.** Measured blast radius: 25 non-test
Python modules reference `strategic_intent` — every inverter controller,
`schedule_store`, `daily_view_builder`, the three debug exporters,
`backend/api.py`, `backend/ai_chat.py`, `api_dataclasses` — plus 10 frontend
files, and since #544 it is pinned per period in the goldens. That is a
vocabulary migration across the application, not candidate-space work, and
bundling it would make 4b's and 4c's measured deltas unreadable.

---

## 6. Acceptance criteria

Fixed by the parent plan; the design chooses the how. Each must be verified by
a **mutation**, not a green suite — reverted behaviour, named failing test,
count reported, per the PR template.

- **#352**: a low-rate export plan either carries a spike-tolerant command or
  is not planned; the reproduction shows no avoidable spike import. Covers the
  0.1–0.5 kWh home-dominant band #511 does not reach. Concretely:
  `regression_2026_08_12_202906` p99 (0.125 kWh export against 0.700 kWh to the
  house) must **not** be planned as a partial-rate `grid_first` command.
- **The arbitrage-remainder case must survive — a pin, not a nice-to-have.**
  Any materiality rule is wrong if it breaks this, and one already did:

  > 25 kWh available, 10 kW export cap, hourly periods priced 2.00 / 4.00 /
  > 5.00 SEK/kWh. The optimum is **5, 10, 10** — every exporting period at the
  > cap except one, which takes the remainder in the *cheapest* hour. That
  > 50%-rate period is legitimate arbitrage and must be admitted, at no cost to
  > the plan (94.25 SEK of planned export revenue, unchanged).

  A rule that admits p99 or refuses this h0 is refuted. Both are single-solve
  checks; write them as tests when 4b lands, in that order, and state the
  measured revenue rather than asserting "unchanged".
- **#320**: no Growatt MIN mode flip caused by plan/lattice rounding on the
  reproduction bundle. (Regression cover only — #320 is closed.)
- **#466 crossover**: the 06:00–06:59 residual-cover case keeps a test here,
  in the candidate space rather than the tie policy.
- **#511-class**: a planned discharge the inverter cannot execute is
  *unrepresentable* — the test constructs the old failing plans and shows the
  candidate space cannot express them.
- **R==P corpus**: `KNOWN_PLAN_EXECUTION_GAP_SEK` entries move toward 0 and
  none regress.

**Exit gate:** intent is an input; corpus R==P gaps are at their floor;
#320/#352 reproductions pass.

### Expected golden churn

4b and 4c change the candidate space, so plans move and the action-selector
goldens must be regenerated — including the `intents` and
`intra_period_discharge_allowed` fields added in #544. This is the first phase
where that is expected. Every regeneration states its measured delta in the PR
body; a phase that cannot regenerate them has not measured its delta.

---

## 7. Sequencing

**After the beta, not before.** Phases 1–3 were parity-preserving: the goldens
were captured at Phase 1 and every later change left all 36 fixtures'
actions and SoE bit-identical. 4b/4c deliberately break that. The beta's job is
proving 25 closed reporter fixes on real hardware; a candidate-space change
that moves most plans would make any report from those reporters ambiguous
between "the audited refactor regressed something" and "the new candidate space
chose differently".

Work that can proceed now, all non-behavioural: 4a (whose two decisions are
approved). The #352 reproduction fixture and the 22/16 reconciliation are
**done** (2026-08-13, §2), and D3 is decided and measured (§5, 2026-08-14).
The beta is the only thing 4b and 4c now wait on.

Every number in §2 and §5 is re-derivable:
`PYTHONPATH=. .venv/bin/python scripts/measure_export_commitment.py`.
