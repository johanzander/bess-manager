# Phase 4: Executable-command candidates (P3) — design

**Status: D1, D2, D4 approved 2026-08-11. D3 decided 2026-08-14 and
superseded the same day** — #352's root cause turned out to be a *missing*
candidate, not a bad one (§2, "The root cause is a missing candidate"). D3
survives only as optional cleanup. Phase 4's plan entry requires a design doc
before code and says `rules.md`'s new-class approval applies — the modules
named in D1 and D2 carry that approval.

**4a is the prerequisite for everything else, including the #352 fix**, and
**the beta gate is cleared (2026-08-14, §7)** — so the sequence is 4a then 4b,
with nothing else to wait for. The #352 fix is not a separate patch: it is 4b's
discharge half, gated on the load-following capability that does not currently
reach the optimizer at all, which is 4a's job. The reproduction fixture and the
22/16 reconciliation landed 2026-08-13 (§2). 4d has been removed from Phase 4
entirely and is now Phase 5 in the parent plan.

**Reading order for anyone picking this up:** §2's root-cause subsection first,
then §5 for the history of how the wrong answer was reached and measured — the
D3 numbers are not valid on the post-4a action space.

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

### The root cause is a missing candidate, not a bad candidate (2026-08-14)

**This subsection supersedes D3 as the answer to #352.** It came out of a
`bess-analyst` second opinion sought before amending a normative principle, and
it inverts the diagnosis: the export is not a bad action the DP chooses, it is
the *least-bad* action available because the right one is absent.

At the field-evidenced period the action space offers **2.70 kW** or
**3.30 kW**, and nothing between:

- the house needs **2.80 kW** (0.700 kWh over the period, no solar);
- 2.80 is off the percent lattice (15 kW battery, 1% = 0.15 kW);
- 2.85 / 3.00 / 3.15 are removed by #497's unexecutable band;
- `_residual_cover_p` offers exact cover **only below the smallest lattice
  step**, so it does not fire here.

So the DP chooses between under-covering (2.70, planning a 0.025 kWh import at
buy 3.917) and over-covering (3.30, exporting 0.125 kWh at sell 2.634).
Over-covering is the cheaper error, and **that is what makes the period a
`BATTERY_EXPORT` and puts the inverter in the committing mode**. The export was
never the goal.

Exact cover is executable on load-following hardware: `load_first` is a
ceiling, so commanding the step above (19% = 2.85 kW) delivers
`min(2.85, 2.80) = 2.80` exactly. That is the same delivery-planning argument
`_residual_cover_p` already makes below the lattice, simply not applied above
it — a P3 gap, not a robustness problem.

**How to express that — owner's formulation, 2026-08-14, and it is the better
one.** The first draft added an off-lattice candidate at the deficit (2.80 kW)
and planned the *delivery*. Keep the candidates on the hardware lattice
instead — 2.85 kW **is** a real command, 19% — and make the candidate's
**flows** honour what that command does: under a ceiling it delivers
`min(2.85, deficit)` and exports nothing. Same delivered energy, same command
written, but two properties the off-lattice version does not have:

- **No conversion step, so no rounding failure.** An off-lattice planned power
  must be scaled back to an integer percent by `_scale_to_percent`, which
  rounds to *nearest* — and measured over the corpus, **39% of house deficits
  (539 of 1377) round DOWN**, where the commanded ceiling under-delivers the
  plan. The off-lattice version therefore needs a second fix (round ceilings
  up, safe because a ceiling never delivers more than the load) and only works
  for the other 61% without it. In the lattice-preserving version the plan *is*
  the percent: the failure mode does not exist. Measured: off-lattice cover
  under today's nearest-rounding reaches 1793.26 / 25 committing; with
  round-up, or with the lattice-preserving form, 1792.99 / 19.
- **It explains #497's band rather than working around it.** 2.85/3.00/3.15 are
  excluded today because the flow model assumes each dribbles a sub-resolution
  export. They only do that if the number is a *target*. With mode-aware flows
  they are "cover the house exactly" and the exclusion is unnecessary **on
  ceiling platforms** (it still earns its keep on target platforms, where the
  sub-resolution export is real).

This is P3 as written — "candidate value is computed by simulating that
command's response to the forecast" — so the #352 fix and 4b's discharge half
are the same piece of work, not a patch now and a rewrite later. It still
requires the platform capability (below), so it still sits behind 4a.

**Measured, all four worlds, DP re-optimising over the 37-fixture corpus:**

| world | corpus cost | vs baseline | committing exports | repro p99 |
|---|---|---|---|---|
| baseline | 1796.11 | — | 52 | exports 0.125 kWh |
| **+ exact-cover candidate** | **1792.99** | **−3.12** | **19** | LOAD_SUPPORT, exact cover |
| + cover + within-epsilon preference | 1793.47 | −2.64 | 8 | fixed |
| + cover + D3 | 1794.47 | −1.64 | 0 | fixed |
| D3 alone (the §5 rule) | 1799.78 | **+3.67** | 0 | fixed, but plans a 0.025 kWh phantom import |

Adding the missing candidate fixes the field case, removes 33 of the 52
committing exports, and makes the corpus **cheaper**. D3 alone costs 3.67 SEK
and leaves a planned import that execution erases — an R≠P of exactly the shape
Phase 4 exists to end.

**Consequences, in order of how much they change:**

1. **No principle needs amending.** The earlier proposal to amend P7 rested on
   "Shape B is decisively better under a point forecast, so P2 cannot reach
   it". That decisiveness is ~85% an artifact of the missing candidate: with
   exact cover injected the p99 margin collapses from 0.0388 SEK to 0.0067,
   *inside* the period's epsilon of 0.0069. P3 already claims #352; the
   architecture was right and the code was not implementing it. **Do not
   record P7 as falsified.**
2. **Every D3 measurement in §5 was taken on the impoverished action space**,
   where each non-committing alternative carries a forced sub-lattice import at
   buy price — the very tariff asymmetry #352 is about. It systematically
   overstates export margins. The +3.67 SEK and the 26/65 preference-firing
   count both need re-deriving once cover exists.
3. **4a becomes a prerequisite, not a parallel track** — see below.

### Ceiling semantics are per-platform, and the DP cannot see which (2026-08-14)

The exact-cover candidate is only sound where a discharge rate is a *ceiling*.
Measured across the controllers:

| platform | what a discharge number means |
|---|---|
| Growatt MIN (`tou_register`) | ceiling — delivers `min(number, actual load)` |
| solax-modbus Growatt TOU | ceiling |
| Growatt VPP | no rate for load support since #413 — natively load-following |
| **SolaX native** (`vpp_power`) | **target** — `LOAD_SUPPORT → -(rate% × max_discharge)` |
| Huawei, Growatt SPH (`period_list`) | no per-period rate at all |

`discharge_rate_is_load_following` exists as a controller `ClassVar`, but it
reaches only `battery_system_manager`'s gate and the controllers. **It is never
passed into the DP** (grepped 2026-08-14: no occurrence in
`dp_battery_algorithm.py`, `pwl_window_dp.py` or `action_selector.py`).

Two consequences:

- **A pre-existing gap, filed separately:** `_residual_cover_p`'s below-lattice
  cover candidate is added unconditionally, so on SolaX native / Huawei / SPH
  the DP already plans a delivery those platforms will not produce. Minor today
  (all three are experimental per the platform-maturity note) but real, and
  generalising cover without a capability gate would widen it from rare
  sub-step residuals to most periods.
- **Sequencing:** the #352 fix is "add the cover candidate *where the hardware
  load-follows*", which needs the capability in the optimizer. That is 4a. So
  **4a is now a prerequisite for the #352 fix**, not an independent track.

### What is left after the real fix

19 committing exports survive exact cover. Two optional cleanups, both measured
above: the within-epsilon preference (−0.48 SEK, leaves 8) and D3 (a further
~1.5 SEK, leaves 0). The 8 that survive both cover and the preference are
decisively profitable under the forecast — being paid for the commitment, in
the issue's own terms. **Neither cleanup should be built before 4a and the
cover candidate land and the numbers are re-measured on the honest action
space.**

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
| **4b** | Discharge candidates become executable commands. **Closes #352 Shape B via the exact-cover candidate** (§2), gated on 4a's load-following capability; D3 optional cleanup afterwards. Folds #511/#517 tests in as regression cover. | 4a, the beta | blocked on 4a + beta |
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

**D3 — What is "dominance OR forfeited headroom", concretely? 🟠 SUPERSEDED
AS THE PRIMARY FIX, 2026-08-14** — see "The root cause is a missing candidate"
below, added the same day after a `bess-analyst` second opinion. D3 was decided
on the reasoning in this section and then demoted within hours; the reasoning
is kept in full because the demotion is the interesting part. **Read the
root-cause subsection first — the measurements below were taken on an action
space now known to be impoverished, and the +3.67 SEK headline becomes
−1.64 SEK once the missing candidate is present.**

The rule stays on the table as *optional* cleanup for the residual (§"What is
left after the real fix"), not as the answer to #352.

The reasoning as it stood when decided:

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

**Beta gate CLEARED 2026-08-14 (owner).** The beta has been running without
reported issues, so its job — proving 25 closed reporter fixes on real
hardware — is done, and the owner is releasing it to `main`. Phase 4 no longer
waits on it.

The original reasoning, kept because it is the right test to re-apply if this
ever recurs: Phases 1–3 were parity-preserving, with all fixtures' actions and
SoE bit-identical from Phase 1's goldens onward. 4b/4c deliberately break that,
and a candidate-space change that moves most plans would have made any report
from those reporters ambiguous between "the audited refactor regressed
something" and "the new candidate space chose differently". That ambiguity is
what the gate existed to prevent; with the beta clean and released, there is
nothing left to confound.

One thing the clearing does not change: 4b still moves plans, so it re-pins
goldens and `expected_results` deliberately, stating measured deltas (see
"Expected golden churn").

Work that can proceed now, all non-behavioural: 4a (whose two decisions are
approved). The #352 reproduction fixture and the 22/16 reconciliation are
**done** (2026-08-13, §2), and D3 is decided and measured (§5, 2026-08-14).
The beta is the only thing 4b and 4c now wait on.

Every number in §2 and §5 is re-derivable:
`PYTHONPATH=. .venv/bin/python scripts/measure_export_commitment.py`.
