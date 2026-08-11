# Phase 4: Executable-command candidates (P3) — design

**Status: D1, D2 and D4 approved 2026-08-11. D3 remains open by choice.**
Phase 4's plan entry requires a design doc before code and says `rules.md`'s
new-class approval applies — the modules named in D1 and D2 below carry that
approval.

**4a is startable.** 4b additionally needs D3 and the #352 reproduction
fixture; 4b and 4c both wait for the beta to ship (§7). 4d has been removed
from Phase 4 entirely and is now Phase 5 in the parent plan.

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

### The #352 evidence does not currently reproduce, and that is a blocker

Scanning all 36 fixtures for BATTERY_EXPORT periods planned below the house
deficit: **0 periods**, none in the 0.1–0.5 kWh band — against the plan's
recorded "22 sub-load `grid_first` periods, 16 in the band" from 2026-08-10.

The corpus plans have not moved in between (the action-selector goldens
predate that date and still pass bit-identically), so the two measurements
count different things. Most likely the corpus is simply the wrong instrument:
no fixture comes from a configuration like #352's reporter's (5 kW inverter,
UK/Octopus, evening load against a 0.6–0.95 kW `grid_first` commitment).

**Two things must land before 4b is written**, both non-code:

- A reproduction fixture built from a real bundle via
  `scripts/mock_ha/scenarios/from_debug_log.py`. Nothing can be seen to fail
  without it, which this repo now requires of every fix.
- Reconciliation of the 22/16 figure. It is the justification for the work.

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
| **4b** | Discharge candidates become executable commands. Closes #352 Shape B. Folds #511/#517 tests in as regression cover. | 4a, D3, the #352 fixture, the beta | blocked |
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

**D3 — What is "dominance OR forfeited headroom", concretely? ⬜ OPEN, and
deliberately so.** #354's two-sided materiality test kept as candidate scoring.
P7 constrains the shape: risk handling must be **structural, not stochastic**,
so no probability distribution over load. Likely reading: a low-rate
`grid_first` export is admissible only if the planned export dominates the
plausible in-period load excursion, or if declining it forfeits headroom that
has real value. Undecided: whether the threshold is configured, derived from
the lattice, or derived from forecast granularity.

**Do not settle this before the #352 reproduction fixture exists.** The bug
does not currently reproduce on any fixture (§2), so a predicate chosen now
would be fitted to no observable failure. This is the one decision where
waiting is the correct action rather than a delay.

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
  0.1–0.5 kWh home-dominant band #511 does not reach.
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

Work that can proceed now, all non-behavioural: the #352 reproduction fixture,
the 22/16 reconciliation, D3, and 4a (whose two decisions are approved).
