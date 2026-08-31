# BESS Domain Knowledge

This document contains the domain knowledge an analyst needs to answer
questions about the BESS Manager battery optimization system.  It is the
single source of truth for both the in-app AI chat and the GitHub analysis
agent.

For deeper investigation, use tools to read the source code directly.
Key files: `core/bess/dp_battery_algorithm.py` (optimizer),
`core/bess/models.py` (data models), `core/bess/energy_flow_calculator.py`
(flow decomposition), `core/bess/growatt_schedule.py` (schedule generation),
`core/bess/battery_system_manager.py` (orchestrator).


## How the System Works

BESS Manager optimizes a home battery to minimize electricity costs.  Every
15 minutes it re-runs a dynamic programming optimizer that looks at:

- **Electricity prices** (today + tomorrow when available, at 15-min resolution)
- **Solar production forecast**
- **Consumption prediction** (time-of-day shaped or flat, depending on strategy)
- **Current battery state** (charge level, cost basis of stored energy)
- **Battery parameters** (capacity, efficiency, cycle cost)

The optimizer produces a schedule of battery actions (charge / discharge /
idle) for each 15-minute slot from now through the end of available price
data.  This schedule is applied to the inverter via Home Assistant.

**Re-optimization**: The system re-runs every 15 minutes.  Each run uses the
latest actual data (replacing predictions with measurements) and may produce
a different schedule.  Common triggers for schedule changes:
- Tomorrow's prices become available (typically around 13:00 for Nordpool)
- Actual solar or consumption differs from the forecast
- Battery state differs from what was predicted


## The Dynamic Programming Algorithm

The optimizer uses **backward induction**.  Starting from the last period and
working backwards, it evaluates all possible battery actions at each period
and selects the one that minimizes total electricity cost over the remaining
horizon.

**State space**: Discretized battery state of energy (SOE) levels.

**Actions**: Charge, discharge, or idle at various power levels — filtered
by physical constraints (available energy, remaining capacity, power limits).
Discharge candidates enumerate the inverter's integer-percent rate grid,
plus one deliberate off-lattice candidate (#466 follow-up, generalized by
Phase 4b for #352): discharging exactly the forecast net-load residual,
wherever the lattice cannot represent covering it. Load-first hardware
delivers `min(actual load, ceiling)`, so commanding the smallest lattice
step at or above the residual delivers the residual exactly — the plan is
the *delivery*, the command is on the lattice. It is gated so it always
classifies as LOAD_SUPPORT and so a covering ceiling actually exists on
the platform (`_residual_cover_p` in `action_selector.py`, and
`load_support_delivers_exact_cover` in `execution_model.py` — the
candidate is withdrawn on hardware where a discharge number is a forced
power rather than a ceiling, #580).

Without it a period whose net load falls between two lattice steps has no
action that covers the house: the step below under-covers and imports the
difference at buy price, and every step above either is excluded as
unexecutable (#497 below) or exports for real at sell price. With buy >
sell that is a forced loss either way. Two user-visible symptoms came from
exactly this gap — the "morning IDLE" pattern at sunrise/sunset crossovers
(#466), and low-rate evening `BATTERY_EXPORT` periods written as
`grid_first`, which does not load-follow, so a load spike was imported
while the battery sat full (#352 Shape B). The export in the second case
was never the goal; it was the cheaper of two bad roundings.

**Transition**: Each action updates SOE accounting for charge/discharge
efficiency losses and updates the **cost basis** of stored energy.

**Objective**: Minimize net electricity cost (grid import cost minus export
revenue) while accounting for battery cycle degradation costs and a terminal
value for energy remaining at end of horizon.

**Terminal value**: Applies unconditionally at whatever the current horizon
boundary is — midnight-today when only today's prices are available,
midnight-tomorrow once tomorrow's prices have landed and the horizon
extends. Without it, the DP has no visibility past the horizon and would
have no reason not to drain the battery completely in the last period; this
holds regardless of where that boundary currently sits, since no provider
ever supplies data past midnight-tomorrow either. Each leftover kWh at the
horizon's end is valued at:

    value(u) = head_rate * min(u, knee_kwh) + tail_rate * max(0, u - knee_kwh)

a **concave** row, not a single rate (#602). `knee_kwh` is the household's own
net load from the boundary until tomorrow's PV covers it, so the *quantity*
carried is set by a load profile rather than by a price estimate;
`head_rate` is `median(buy_prices) * efficiency_discharge` — the purchase the
household avoids by having carried the energy. `tail_rate` is
`min(sell_prices) * efficiency_discharge` (the terminal day's window), since
energy beyond the knee is refilled by tomorrow's sun and is worth only what
exporting it earns; on a **fixed export tariff** `min` and `max` coincide, so
the floor would land exactly on the hold-versus-export tie and `tail_rate` is
0.0 there instead, matching #359's existing carve-out.

`head_rate` is deliberately **not** floored at
`max(sell_prices) * efficiency_discharge`. That was tried and reverted: it
prices terminal energy above what the DP can buy at inside the horizon, which
turns the terminal row into an arbitrage target — on `synthetic_seasonal_spring`
(median buy 1.05, best sell 1.90) the floored rate of 1.805 made the DP charge
40.6 kWh to bank 23.6 against a 42.64 SEK credit, which is #126/#244's
fictitious bonus at scale. The consequence of not flooring is that the rate
still decides *whether* to carry while the knee decides *how much* — a ~12%
move in the rate swings the full knee on #595's fixture. That is a known
limitation, not an oversight.

Before #602 this was one unbounded slope,
`median(buy_prices) * efficiency_discharge - cycle_cost` capped at
`max(sell_prices) * efficiency_discharge - cycle_cost`. That shape made midnight
SOE all-or-nothing: the DP compares the slope against the best in-horizon export
value, so every kWh was worth holding or none were. The `cycle_cost` deduction
also double-billed wear, which is charged on charging only. **Both the deduction
and the cap are gone** on days where the knee can bind; the quantity bound
replaces what the cap was doing, and does it better, because terminal energy is
monetised by self-consumption rather than only by export.

**When the knee cannot bind** — it exceeds usable capacity, i.e. every winter
day and any overcast one — the pre-#602 capped scalar above is still used
verbatim. Without PV to refill the pack there is no quantity at which a stored
kWh stops being worth the buy price, so the row would be straight *and*
uncapped, which is #126/#244's hoarding bug. #602's evidence covers only the
knee-bounded regime; #381's winter carry needs a knee derived from the next
cheap charging window and is not yet addressed.

(the formula lives in `core/bess/terminal_value.py`, called by
`BatterySystemManager._calculate_terminal_curve`, which owns fetching its
inputs and logging the result; see issues #126/#244/#246/#345/#422/#602). The same
function is what the forecast-robustness harness and the pinned scenario
corpus price the boundary with, so all three optimize against one objective.
This is the mechanism to check first for
"why didn't the battery discharge everything right before midnight" or "why
does it hold charge near the end of the horizon" — it applies at both the
today-only and today+tomorrow boundary, so this remains the first thing to
check even after tomorrow's prices have arrived (until #345, it was
incorrectly zeroed in that case; see the #345/#126 threads for the "tonight's
export moves a day later" symptom this was suspected of, and ultimately
ruled out for a specific bundle).

Unlike `buy_prices`, the `sell_prices` fed into the cap are **not** the full
remaining-horizon window — the caller (`_run_optimization`,
`battery_system_manager.py:~2050-2075`) scopes them to periods on the
terminal boundary's own calendar day only (issue #422). On a 48h-extended
horizon, using the full window let an already-committed near-term peak
(e.g. today's still-upcoming best sell slot) inflate the cap for tomorrow's
terminal boundary, making the DP hold charge through all of tomorrow's own
(lower but still profitable) export opportunities instead of exporting into
them — this was the actual mechanism behind the long-reported #126 "tonight
exports, tomorrow evening doesn't" symptom. `buy_prices` is unaffected by
this scoping — a median is already resistant to a single-period outlier, so
only the cap's `max()` needed the day boundary.

The cap is skipped entirely on a fixed/flat export tariff (`max(sell_prices)
== min(sell_prices)`, e.g. UK Octopus Outgoing Fixed) — there, every period
shares the same sell price, so `max(sell_prices)` is not a real future
opportunity being forgone, and applying the cap anyway forces terminal value
below the round-trip breakeven for any buy price, making it arithmetically
impossible to store surplus solar for post-horizon use (issue #359). On any
market with genuine price variation (Nordic, Belpex, UK variable-export),
this carve-out is inert and the cap applies exactly as described above.

**The DP only proposes executable discharges (issues #240, #497)**:
`_discharge_candidates` excludes any discharge that would overshoot the home
deficit by less than `GRID_FLOW_RESOLUTION_KWH` (0.1 kWh,
`core/bess/dp_constants.py`). Such a discharge is not executable on any
platform: load-following firmware throttles it back to the deficit, and on
hardware that would deliver it the resulting export is below the resolution of
the counters that measure exports. So no planned period can contain a
sub-resolution battery export, and every planned flow set balances exactly.

When judging whether a small discharge was "worth" `sell_price`, the answer is
that the DP was never offered that action -- the relevant comparison is between
covering load exactly and a genuinely larger, measurable export.

This replaced #240's approach, which let the DP propose the action and then
zeroed the export *credit* in `_compute_reward` while leaving
`battery_discharged` and `next_soe` carrying the full commanded setpoint. That
booked export revenue load-following hardware never earns, and
`EnergyData._calculate_detailed_flows` folded the orphaned export back into
`battery_to_home` (#350), producing periods whose flows did not add up (#497:
182 of 1875 fixture periods). Consequences of removing it, all measured:

- Planned flows always balance -- `assert_flow_coherence` checks this on every
  period of every fixture.
- Plan and execution agree exactly: realized cost equals planned cost on all 33
  fixtures, where 20 of them previously disagreed by up to 0.73 SEK.
- The DP's own objective and the reported `battery_solar_cost` now agree
  exactly, removing a long-documented reporting drift.
- Realized cost improved by a net 1.04 SEK across the corpus, because the DP had
  been optimising against revenue it could not collect.

The trade-off: when a deficit is smaller than the smallest discharge the
hardware can be commanded to perform, the DP proposes no discharge and the home
imports it. There is no platform-specific self-throttle threshold any more --
`self_throttle_export_threshold_kwh` was deleted along with its plumbing.

**Cost basis tracking (weighted average)**: When the battery charges at
different prices over time, the system tracks the cost of stored energy as a
**weighted average**, not FIFO. On charge: `new_cost_basis = (soe *
cost_basis + new_energy_cost) / next_soe`
(`core/bess/dp_battery_algorithm.py:496-498`). On discharge, `cost_basis` is
left unchanged — there is no "oldest energy first" queue or layered
accounting anywhere in the code.

**All-IDLE safety net (not a profit threshold)**: After optimization, an
all-IDLE schedule is unconditionally computed and swapped in only if its
`battery_solar_cost` is cheaper than the optimized schedule's
(`core/bess/dp_battery_algorithm.py`). Both sides of that comparison are first
credited for energy left at the boundary using the same terminal row the DP
optimized against (#602) — without it the net judges a plan that deliberately
carries energy by an objective that ignores the carry, and discards it. It
remains a plain cost comparison — there is **no minimum-profit threshold and no
day-fraction scaling**. An earlier design had a threshold/guardrail here; it was removed
in the "Bellman-optimality guardrail removal" refactor (commit
`ee24537f`/`f57d4fed`,
`docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md`)
because the DP's backward induction already finds the Bellman-optimal
schedule, making an extra economic gate redundant. What remains is a
numerical safety net for SOE-discretization residual, not an economic
judgment call. The fallback still passively absorbs any solar surplus into
available battery room and pays wear cost on it, but never discharges to
recoup that cost, so it isn't automatically better than what it would
replace.

**Shadow price (marginal value of stored energy)**: The backward induction
builds a value-to-go for every (period, SOE-level) state — the best achievable
result from that point onward.  The **shadow price** of a period is the slope
of that value across SOE: *how much one extra kWh of stored energy is worth,
in SEK, given the optimal future use of it*.  It is **not** the cost basis
(what the energy cost to store — a sunk cost).  It is the forward-looking
**opportunity value**, and it automatically accounts for everything the
optimizer can do with that kWh later: avoid a future expensive grid purchase,
export it at a future high sell price, or — crucially — nothing extra, because
upcoming solar will refill the battery anyway (**replenishment**).  Each
period's shadow price is stored on its decision data and is used at apply time
for the SOLAR_EXPORT discharge gate (below).


## The Governing Economic Law (read this first)

Every battery action is judged by its **marginal net value against the next-best
alternative for that same slot** — never by its gross value, and never against
"do nothing = 0".

The opportunity cost of a stored kWh is its **forward-looking `shadow_price`** (the
DP's value-to-go, priced per kWh **delivered** since #683), floored by
`sell_price / discharge_efficiency` when upcoming solar will replenish the battery
for free. Mind that denominator: `shadow_price` is directly comparable to
`buy_price`, but sits a factor `1/η` above `sell_price`, so comparing it to a raw
`sell_price` makes every export look like a 5.3% loss. It is **not** the sunk
`cost_basis`, and **not** zero.

Operational forms of the one law:

- **Discharge to grid** is worthwhile only if
  `sell_price × efficiency_discharge > opportunity_cost_of_stored_kWh`.
- **Discharge to cover home load** is worthwhile only if it beats the cheapest
  alternative for that kWh (usually a future avoided import at a higher buy price).
- **Charge** is worthwhile only if the stored kWh's future value exceeds what it
  cost to store it (grid/solar cost + wear).

The classic error this prevents: treating `sell_price > wear_cost` as "profitable".
That compares gross sale value to wear and ignores the counterfactual. If the real
alternative is "let solar keep charging one more slot and export one slot earlier",
the value captured is only the **differential** in sell price between the two slots,
which must still clear the wear cost. A 6 öre differential against a 40 öre wear
cost is a loss, not a 6 öre gain.

**Reconciliation with the code:** `_compute_reward`
(`core/bess/dp_battery_algorithm.py:409-541`) no longer implements an explicit
profitability floor. That anti-cycling floor was removed in the
"Bellman-optimality guardrail removal" refactor (commit
`ee24537f`/`f57d4fed`,
`docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md`);
the function's current docstring states "No profitability veto: every
physically valid discharge gets a finite reward... a separate floor on top
of that is redundant at best." The governing economic law above still holds
as the *outcome* of backward induction (the DP won't choose a discharge that
isn't marginally worthwhile), but it is enforced by the value-to-go
comparison across the whole horizon, not by a floor inside `_compute_reward`.

### Facts vs Economics — where each lives in a debug bundle

Answer "what happened" and "why" from different parts of the bundle, in that order:

- **Facts (what happened):** `## Optimization Schedules → ### Period Decisions`
  table. Columns: `Intent | Observed | BattAct | SOE start→end | BuyPrice |
  Savings`. A negative `BattAct` with a falling `SOE` is a battery discharge — read
  this before proposing any mechanism. Solar-only export shows `BattAct ≈ 0`.
- **Economics (why):** the Full Schedule JSON `<details>` block — `sell_price`,
  `buy_price`, `cost_basis`, `shadow_price` per period — plus `### Economic Summary`.
- **Period ↔ clock time:** slots are 15 minutes. Map the question's clock time to a
  period number and confirm it. Watch the off-by-one: the price shown for 15:45 is
  the 15:45 slot's price, not 16:00's.

### Illustrative: applying the law (method demo, not a lookup)

*Illustrative only — the method generalizes to any period. Do not pattern-match the
scenario; reproduce the reasoning steps.*

A battery discharges a small amount to grid in a slot where `sell = 0.46`,
`wear = 0.40`.

- **Wrong (gross):** `0.46 > 0.40 → +6 öre, profitable.`
- **Right (marginal):** the alternative is to let solar charge one more slot and
  export one slot earlier, so only the sell-price *differential* (~0.06) is gained,
  against 0.40 wear ⇒ ≈ `−0.34 SEK/kWh`, a loss. Equivalently: `shadow_price` (e.g.
  0.876) and `cost_basis` (e.g. 0.62) both exceed `sell 0.46`, so the stored kWh is
  worth more kept than exported ⇒ do not discharge.
- If different optimization runs disagree on such a near-threshold slot, the cause
  is `shadow_price` sensitivity across re-optimizations, not a missing mechanism.


## Strategic Intents

Every 15-minute slot gets a strategic intent based on the energy flows the
optimizer chose: **GRID_CHARGING**, **SOLAR_STORAGE**, **LOAD_SUPPORT**,
**BATTERY_EXPORT**, **SOLAR_EXPORT**, **IDLE**. The exact classification
thresholds live in `core/bess/strategic_intent.py` — read that file
directly rather than relying on a copy of the numbers here, since they are
implementation detail that can change independently of this doc.

**Hardware mapping**: Intents control actual inverter behavior (register-
based platforms — Growatt TOU/cloud/SPH; VPP-style platforms select
`grid_first`/`battery_first`/`load_first` per-period instead of via a
persistent mode, see the SOLAR_EXPORT and IDLE hardware-mapping notes below):
- GRID_CHARGING → battery_first mode + grid charge ON
- LOAD_SUPPORT → load_first mode
- BATTERY_EXPORT → grid_first mode (battery discharge to grid)
- SOLAR_STORAGE / SOLAR_EXPORT / IDLE → load_first mode (solar serves home first)

This `load_first` mapping is what register-based platforms (Growatt
TOU/cloud/SPH) use for all three. **VPP-style platforms diverge for IDLE**
(issue #466): `load_first` self-use discharges the battery to cover house
load, but IDLE's own DP cost model (`_idle_battery_flows` in
`dp_battery_algorithm.py`) never credits battery discharge — only passive
solar absorption. VPP-mode IDLE instead maps to `remote_control=Enabled`,
`vpp_power=+1` (`battery_first` hold), keeping self-consumption on
grid/solar. See `docs/INVERTER_PLATFORMS.md`'s "IDLE semantics" section for
the full mapping and why `grid_first` (the SOLAR_EXPORT pattern) doesn't
also fix this.

**Exception — at the reserve floor** (issue #592): the hold protects stored
energy, so at `min_soc` there is nothing to protect and it only keeps the
inverter under continuous remote control, preventing the BMS from sleeping.
VPP-mode IDLE with the battery at the floor releases instead
(`remote_control=Disabled`, `vpp_power=0`). Flow-neutral — released
`load_first` absorbs passive solar exactly as the hold does, and there is no
headroom to discharge. The VPP regression baseline's **commands** therefore
change at every such period (499 periods across 50 entries) while **realized
cost and SoE are unchanged to 0.000000000000** — the commands moving with the
energy fixed is the evidence, not a regression. Above the floor, nothing
changes.

### BATTERY_EXPORT vs SOLAR_EXPORT (why the split exists)

Both export to grid, but they are different situations and need different
inverter modes:
- **BATTERY_EXPORT**: the battery is *actively discharging to grid* for profit
  → `grid_first` + an action-derived discharge rate.
- **SOLAR_EXPORT**: the battery is *idle and full*; only the **solar surplus**
  flows to grid → `load_first`.  The battery is not pushed to grid.

Earlier both were one intent (`EXPORT_ARBITRAGE`) mapped to `grid_first`, which
wrongly locked the inverter in grid-export mode for hours during sunny
daytimes while the battery sat unable to help the house.

### The SOLAR_EXPORT discharge gate (load_first + discharge rate 0 or 100)

`discharge_rate` is a **hardware register** written every period, not just a
schedule label.  At `discharge_rate=0` the battery is forbidden to discharge at
all — so it cannot cover the house load if solar dips *within* a period.  At
`discharge_rate=100` `load_first` lets the battery cover an intra-period deficit
(it still won't export — that's grid_first).

Whether a SOLAR_EXPORT period should allow that cover is an **economic** choice,
decided per period from the **shadow price** (above):

> Cover the dip from the battery only when the stored energy is worth *less*
> than buying that energy from the grid right now:
> **`buy_price ≥ shadow_price` → rate 100, else rate 0`.**
> No efficiency factor appears (#683): `shadow_price` is denominated per kWh
> **delivered**, the same unit as `buy_price`. Covering `ΔE` from the battery
> consumes `ΔE/η` of stored energy, which would later have delivered `ΔE`
> anyway, so the opportunity cost is `ΔE × p_future` and `η` cancels on both
> sides.

**Where that comparison happens (#526).** It is made *inside the DP*, in
`_record_marginal_value`, at the point where the value function `V` is still in
hand — not downstream in `battery_system_manager.py`. The result is recorded as
`DecisionData.intra_period_discharge_allowed`, a plain boolean, and every
consumer (the BSM apply path and the inverter simulator) reads that boolean
rather than re-deriving the comparison.

The reason is that `shadow_price` is read from the value function *below* the
current state, so it does not exist at the bottom level — and a SoE at
or below the reserve floor clamps there. The DP used to skip the assignment in
that case, leaving the field at its `0.0` default, which is also what a
genuinely worthless kWh produces. Any consumer comparing against the scalar
therefore read "never computed" as "worth nothing", and `0.0` satisfies the
inequality for any positive buy price — so the ceiling opened on data nothing
had computed. **`shadow_price` is now reporting-only; do not derive a decision
from it.** Where no shadow price is computable there is no removable kWh below
that state, so the authorization is `False`: absence is not permission.

**How that price is read (#571, #683).** `_record_marginal_value` calls
`_value_of_delivering_below`, which reads the same piecewise-linear interpolant
the policy walks (`_interpolate_value`) **downwards** — downwards because the
gate authorizes energy *leaving* the battery, so what it must price is the value
given up going down. It is deliberately not `_local_value_slope`, the right-sided
reading the tie detector (#450) uses for a noise magnitude; swapping the two
systematically over-opens the gate.

Until #571 this function did its own index arithmetic, snapping to the *nearest*
grid point with `round()` while the interpolant floors. A state in the lower
half of a cell was therefore priced off the cell below — a region of the value
function the battery is not in — so the reported marginal value stepped
mid-cell instead of at cell boundaries. Signature in a bundle: two periods at
almost the same SoE reporting different `shadow_price`, or an isolated period
holding while its neighbours discharge. Measured effect of the fix on the
fixture corpus: 142 of 2168 gate decisions flipped, 141 of them opening a gate
that had been wrongly closed, with no change to planned energy or cost.

**Why one cell was the wrong span (#683).** Note first what was *not* wrong: the
old `buy_price × discharge_efficiency ≥ shadow_price` was dimensionally sound.
Covering `ΔE` consumes `ΔE/η` of stored energy, so `ΔE × buy ≥ (ΔE/η) × dV/dSoE`
reduces to exactly that test. #683 is filed as a units mismatch; it is not one,
and where `V` is smooth the new rule is algebraically identical to the old.

What was wrong is **estimation**. Even after #571 the reading was a *one-cell*
backward difference, and that cannot price this value function accurately. `SOE_STEP_KWH` (0.025) equals `POWER_STEP_KW × dt`, while converting
stored energy into delivered energy carries `η`. `V` is therefore a staircase
whose riser is one whole delivery step and which is flat once every `1/(1-η)`
cells, so a one-cell difference lands on a riser most of the time and reports the
*undiscounted* price — and on a flat cell reports far too little. `_value_of_delivering_below` prices the **delivery**
instead: delivering `SOE_STEP_KWH` costs `SOE_STEP_KWH/η` of stored energy, so the
interpolant is read across exactly the span the discharge consumes and the
staircase averages out by construction. The result is per delivered kWh, which is
why the rule above *loses* its `η` rather than gaining one.

Measured effect on the fixture corpus (2508 periods, 39 fixtures): planned
actions, intents and SoE trajectory **bit-identical everywhere** and cost delta
exactly zero — the gate is intra-period hardware authorization, which the DP's
cost model does not simulate. 122 gate decisions flipped (4.9%): **100 closing
and 22 opening.** The dominant correction runs *opposite* to the issue's original
"5.3% too strict" framing, because the one-cell difference was noisy in both
directions rather than η-biased — in 111 rule disagreements the old price
was 1.5–2.9× too *low*, authorizing discharge of energy worth well above the grid
price being paid. Against a 20-step reference price the median error falls from
6.7% to 2.7%. Where `V` is smooth the new reading is exactly `old/η` and the
decision is unchanged, which is why the median new/old ratio across all periods
is `1/η`.

What this works out to in practice — important for analysis:
- During SOLAR_EXPORT the battery is full and exporting surplus, so its marginal
  kWh **of stored energy** is only worth the **export (sell) price** — the
  surplus refills it for free (replenishment).  Since #683 the reported
  `shadow_price` is per kWh *delivered*, so it reads ≈ `sell_price ÷
  discharge_efficiency` (e.g. 0.3158 for a 0.30 sell price at η = 0.95), not
  ≈ `sell_price`.  This is a change of denomination only: the gate condition
  in terms of `buy` and `sell` is unchanged, because `buy ≥ sell/η` is the
  same test as the old `buy × η ≥ sell`.
- **Normal prices** (`buy > sell`): the gate is **100** — covering the dip from
  the battery beats buying from grid, because solar refills the battery.  This
  is the usual case.
- **Inverted prices** (export premium or negative buy, i.e. `sell ≥ buy×eff`):
  the gate is **0** — the energy is worth more exported than the cheap grid
  import it would replace, so export it and buy the dip from grid.

So a SOLAR_EXPORT period showing `discharge_rate=0` is **not a bug** — it means
prices were inverted that period.  And `discharge_rate=100` on SOLAR_EXPORT does
**not** mean the battery is being drained: `load_first` only discharges to an
actual house deficit, and at 15-minute resolution a SOLAR_EXPORT period is net
surplus (deficit 0), so planned vs realized economics are unchanged.  The gate
only affects *sub-15-minute* hardware behaviour.

**LOAD_SUPPORT uses this gate too, on TOU/register platforms (#520).** House
load exceeding the period forecast is the normal condition, not an edge case,
and there is nothing platform-specific in the DP's authorization — so the same
economic test applies:

```
discharge_rate = max(
    plan_scaled,
    intra_period_discharge_gate(decision.intra_period_discharge_allowed),
)
```

Raising, never lowering, the plan-scaled ceiling: gate closed → plan-scaled cap
and the deficit is imported; gate open → ceiling raised and the deficit is
covered from the battery.

This settles a change that flipped twice (#384/#385 shipped it, #393 reverted
it, #520 re-landed it). **Do not re-revert on #393's reasoning**, which was:
"a broad override of the #147 reservation pacing." That double-counts the
reservation. The authorization the gate reads **is** a dV/dSoE comparison, made
by the DP against its own marginal value of stored energy — the future value the
pacing protects is already inside it:

- Energy genuinely needed for a later peak → high `shadow_price` → gate
  **closed** → import. Reservation protected, by construction.
- Gate **open** → the energy is worth more used now than saved. There is
  nothing being reserved.

The gate does not override reservation pacing; it *evaluates* it. #393's
headline "the gate evaluates true for 51/67 (~76%) of LOAD_SUPPORT periods"
measured **gate-openness**, not pacing-override: it means that in 76% of those
periods battery-now genuinely beat grid-now.

The breadth is real and corpus-wide — re-measured post-#526 over the 36-fixture
corpus (603 LOAD_SUPPORT periods) the gate is open in **431 (71.5%)** and raises
the ceiling above the DP's plan-scaled rate in **427** of them. That is expected
under the argument above, and it is what makes the gate's correctness an
argument about what the DP's authorization *means* rather than a claim that it
rarely fires. (#520 also quotes an overlap of "9 periods — 1.5%" between
gate-open and "a genuine reservation the plan is holding"; that figure could not
be reproduced from the corpus under any definition tried when the TOU half
landed — treat the 71.5%/427 numbers above as the measured ones.)

Two limits to keep in mind when analysing this:

- `shadow_price` is the marginal value *at the planned SoE*. It is accurate for
  a modest overshoot; for a large one the true value of stored energy rises as
  SoE falls, so the test flatters battery use. That bounds *how much* extra to
  cover, not the direction of the rule — and it is why the gate is evaluated
  fresh each period.
- **The corpus cannot measure this gate's benefit.** Fixtures are 15-minute
  averages from point forecasts, where a sub-period spike is arithmetically
  invisible; only the *cost* (covering more of a planned partial cover from
  battery) is representable. The simulator therefore deliberately does **not**
  mirror the gate for LOAD_SUPPORT (`inverter_simulator._map_rates`) — doing so
  moves 27 of 36 fixtures by +25.67 SEK of realized cost in total (largest
  single fixture `historical_2025_01_12_evening_peak_no_solar` at +8.420 SEK;
  range −0.340 .. +8.420; re-measured post-#526), which is the unmeasurable
  trade-off's cost half alone, not a real result. For
  SOLAR_EXPORT/SOLAR_STORAGE that cost is zero (planned deficit is zero), which
  is why the simulator does mirror the gate for those.

**VPP platforms are still excluded from the ceiling-raising form**
(`discharge_rate_is_load_following` is False there): their `discharge_rate` is
an immediate forced power command, not a load-following ceiling (#324), so
opening the gate would command a full-power discharge rather than permit a
gentle cover. The VPP half of #520 instead expresses the same economic test as
an **energy budget** (`core/bess/vpp_load_tracking.py`): a closed gate on a
`LOAD_SUPPORT` period yields a budget equal to that period's planned discharge
energy (`budget_for_period`), and an opt-in
(`vpp_load_tracking_enabled`, default off) tick loop rewrites `vpp_power`
against the measured house deficit until the budget is spent, then holds
(`VPP_HOLD_POWER_PCT` — `battery_first` at +1%). An open gate returns no budget
and control is released exactly as #413 does today. The earlier proposal to map
only the gate's release/hold *decision* (draft PR #537) was withdrawn: on VPP a
bare hold abandons the planned discharge entirely (118.11 kWh across the
corpus), where TOU's closed gate still delivers it. `simulation/vpp_simulator.py`
models the budget-capped branch; with the opt-in off the VPP corpus stays
byte-identical.

The `shadow_price == 0.0` ambiguity that #520's TOU half would otherwise have
inherited (an uncomputed bottom-grid-level value opening the ceiling
unconditionally) no longer exists: #526 moved the decision into the DP and
withholds authorization where no shadow price is computable. See the "Where
that comparison happens" note above.

See `core/bess/tests/unit/test_load_support_discharge_gate.py` and
`test_load_support_gate_regression_393.py` (real captured data,
`regression_2026_07_26_203726.json`) — both assert the ceiling follows the
gate. Their assertions were deliberately inverted by #520. That fixture is
still in the majority-gate-open regime #393 identified, though the exact figure
has drifted with the DP: 41/68 (60.3%) on the current grid versus #393's 51/67
(76%).

### The inverter AC output cap (solar clipping avoidance)

`inverter_max_ac_power_kw` (BatterySettings, default 0 = disabled) models a
hybrid inverter whose **total AC output** (PV DC→AC conversion plus battery
discharge) is capped — e.g. 5 kW on a Growatt MIN 5000TL-XH — while DC-coupled
PV *above* the cap can still charge the battery directly, but only while the
battery has room.  With the cap set:

- **Clipped solar is worth zero** in the DP: per period, solar not stored
  DC-side is deliverable to home/grid only up to
  `cap × (1 − inverter_ac_power_margin) × dt`; the excess is `clipped_solar`
  (reported per period on `EnergyData` and as `clippedSolar` in the API).
  A full battery during above-cap solar is therefore genuinely costly, which
  is what pushes the optimizer to reserve headroom for the midday peak.
  `clipped_solar` also absorbs export-limit-curtailed PV (#269/#502) — same
  field, second cause: when `export_curtailment_enabled` and a period would
  export below `export_curtailment_price_floor`, the solar-sourced share of
  that export (never the battery-sourced share, since the hardware
  export-limit only throttles PV) is reported as unharvested here rather
  than at its honest negative-price cost, since it will be curtailed to
  zero at runtime. Applied only at reporting seams
  (`apply_export_curtailment_to_period_data` in `models.py`) — the
  `PeriodData` BSM actually stores stays at the honest price, since the
  execution-time curtailment trigger and the DP's own guardrail comparison
  both require it.
- **Deferring absorption uses the SOLAR_EXPORT-below-max bypass (#313)**:
  normally IDLE passively absorbs surplus, so a reward change alone cannot
  defer charging.  The existing bypass candidate (SoE held exactly unchanged,
  surplus exports up to the cap, the rest clips) is what expresses "export
  the surplus, keep the room" — with the cap set, its reward is cap-aware, so
  the DP chooses it ahead of the above-cap window.  These periods classify as
  **SOLAR_EXPORT** with `battery_action = 0` and a not-full battery, meaning
  "deliberately holding for later overflow".
- **The bypass is only offered where that classification actually lands
  (#630)**: nothing commands "hold and export" directly — it is delivered by
  the SOLAR_EXPORT label writing `charge_rate=0`.  That label needs
  `grid_exported > 0.01 kWh` (`FLOW_NOISE_FLOOR_KWH`); below it the period
  falls through to **IDLE**, whose command is `load_first` at charge rate
  100, which absorbs the surplus instead.  Planning the export anyway meant
  the battery ran fuller than planned until it hit a bound and spilled the
  difference.  `_solar_export_bypass_is_unexecutable` in `action_selector.py`
  withholds the candidate there, so a sub-floor surplus is planned as
  absorbed — which is what the hardware does.  Charge-side twin of
  `_residual_cover_p`'s LOAD_SUPPORT gate, on the same constant.
- **Hardware mapping**: SOLAR_EXPORT blocks passive charging (#313), stopping
  `load_first` from filling the battery from surplus solar. On a genuinely
  full battery this is a no-op. The mechanism differs by platform: register-
  based hardware (Growatt TOU/cloud/SPH) writes `charge_rate=0` via the EMS
  register; VPP-style hardware has no such register — it instead selects
  `grid_first` (battery held flat) via a forced `vpp_power=0` command with
  remote control kept enabled, instead of disabling remote control into
  self-use (#355, not yet real-hardware-validated — see
  `docs/superpowers/specs/2026-07-20-vpp-passive-charge-block-design.md`).
  The shadow-price *discharge* gate above is unchanged and orthogonal.
- **Discharge shares the cap**: battery discharge is limited to the AC
  headroom the (possibly clipped) solar leaves
  (`cap − min(solar, cap)` per period), both in the DP's feasible actions and
  in the simulator.
- The **margin** (default 0.05) is a model-side haircut on the cap
  compensating for hourly Solcast forecasts flattening sub-period peaks; it is
  never written to hardware.
- Requires per-period charge-rate control (Growatt MIN).  On platforms
  without it (SPH, SolaX native) the plan is cap-aware but deferred
  absorption is not hardware-enforceable.

### The grid import (fuse) cap (#429)

`HomeSettings.power_monitoring_enabled` (default False) makes the DP model the
house's fuse service limit as a **grid-import** energy cap, the input-side
counterpart to the AC output cap above — the two are independent constraints
on opposite sides of the same AC stage and both apply simultaneously when
configured.

- **Derivation**: `voltage × max_fuse_current × safety_margin × phase_count`
  (`_effective_import_cap_kwh`, `dp_battery_algorithm.py`) — each phase is an
  independent fuse, so a balanced house can import up to `phase_count` times
  a single phase's ceiling before any individual phase is stressed.
  `HomePowerMonitor` (`core/bess/power_monitor.py`) relies on the same
  balanced-load assumption at runtime: on a fully unloaded 3-phase house it
  authorizes the battery up to its full `max_charge_power_w` (not a single
  phase's worth), since `available_pct` is computed relative to
  `max_charge_power_w / phase_count` per phase. `HomePowerMonitor` remains
  the real-time backstop against *unbalanced* loads — it measures actual
  per-phase current and throttles battery charging against the single
  worst-loaded phase (a deliberate fix for that case, commit `37201cb9`,
  #11) — but the DP's `home_consumption` forecast is a single household-total
  figure with no per-phase breakdown, so it cannot reproduce that live check
  and instead plans against the balanced-load assumption. Off (`None`) when
  `power_monitoring_enabled` is False, matching the AC cap's own
  `<= 0.0 → None` convention.
- **Total import, not charging-only**: the cap bounds `grid_imported` (house
  load + battery grid-charging) jointly, not just the charging component —
  `HomePowerMonitor` only throttles charging today because that is the only
  lever a runtime monitor has; the DP has discharge as a second lever and must
  use it, or it just reproduces the runtime blind spot inside the plan too.
- **Constrain, never raise**: same convention as the AC cap and temperature
  derating (mask actions, don't except). A period whose forecast load alone
  exceeds the cap forces the battery to cover the excess via discharge; if
  even full discharge can't bring total import under the cap, the DP falls
  back to the minimum-import action available rather than erroring — a real
  fuse would also just run hot, not crash the planner.
- **Grid-charging is throttled, not blocked outright**: when serving the load
  already consumes the cap's headroom, `grid_to_battery` is reduced to
  whatever room is left (`_state_transition`'s STORE branch) rather than the
  charge action being excluded wholesale — the model-side equivalent of
  `HomePowerMonitor.calculate_available_charging_power`'s runtime throttle.
- **Absent/implausible settings**: hard failure at settings-validation time
  (`HomeSettings.__post_init__` raises if `power_monitoring_enabled` is set
  with non-positive `max_fuse_current`/`voltage`/`safety_margin`), never a
  silent no-op inside the DP — matches `BatterySettings.__post_init__`'s
  existing validation pattern for `inverter_max_ac_power_kw`.
- **Out of scope**: export-side/feed-in capacity limits (a different
  regulatory concept), and any change to `HomePowerMonitor`'s own runtime
  behavior — it remains the real-time safety net; this constraint just makes
  the *plan* agree with it.

### Export curtailment and the charge-early tie-break (#269)

When export curtailment is active (enabled AND the platform supports
export-limit control), periods priced below the curtailment floor get an
effective sell price of 0.0 for the DP's reward calculation only
(`optimize_battery_schedule`'s `reward_sell_price`); reported economics
and the execution-time trigger still use the real price. Execution-side,
BSM writes the hardware export limit (Growatt "Meter 1" + 0%) on any
period with planned export below the floor and releases it otherwise
(`battery_system_manager.py`, `_export_limit_curtailed`).

Flooring the sell price creates *exact reward ties by construction*:
whenever the remaining below-floor solar surplus exceeds battery headroom,
"charge now, curtail later" and "curtail now, charge later" earn identical
reward (signature in a bundle: `shadow_price == cycle_cost_per_kwh` in
those periods). The replay therefore applies a charge-early tie-break -- the tie
policy's charge-early row (`tie_policy.py`, row 4), applied once for both
the grid and PWL replays: among candidates within the #466 epsilon, prefer the highest
`next_soe`, but never one that imports more grid energy than the argmax
winner, and never overriding a discharge winner. Charge-early is
stochastically dominant — equal model reward, strictly better under
forecast error in either direction (captures above-forecast PV that
curtailment would otherwise clip at the panel; preserves slack toward the
next positive-price block).

**General invariant**: any reward shaping that flattens the objective
(floors, caps, zeroing) manufactures indifference regions and MUST ship
with an explicit tie-break policy stating which physically-preferred
action wins inside the flat region — float noise is not a policy.

Shaping is not the only source of a flat region (#606). Consecutive periods
inside one hourly price block can be bit-identical in price, load and solar,
and where they are all unconstrained the objective is *exactly* invariant to
how a fixed total is split across them — only the sum reaches the next
period. Every split is an optimum, so the choice fell to accumulated rounding
in the value function (measured: 0.93 ULP) and the emitted plan differed by
interpreter at bit-identical cost. `tie_policy.py`'s row 5 now resolves these
by a stated order over actions. Signature in a bundle: adjacent periods with
identical inputs whose actions permute between runs while total cost does
not move at all.


## Execution Layer: What Can Override the Schedule

The DP schedule is not the last word — several mechanisms outside the
optimizer can change what the hardware actually does. Check these *before*
concluding a mechanism is "missing" from the DP when observed behavior
doesn't match the schedule:

- **Discharge inhibit sensor**: an external `binary_sensor` (auto-detected by
  entity ID suffix `_charging`/`_is_charging`, e.g. EV charging status) can
  force `discharge_rate` to 0 regardless of what the schedule says, checked
  independently of the 15-min optimization cycle
  (`core/bess/battery_system_manager.py:3089-3113`, polled every minute) and
  applied at schedule-write time
  (`core/bess/battery_system_manager.py:2578-2582`). If a period's
  `Observed` behavior shows no discharge despite `Intent: BATTERY_EXPORT` or
  `LOAD_SUPPORT`, check for an active discharge-inhibit sensor before
  suspecting the DP or the intent-to-hardware mapping.
- **Temperature derating**: charge power can be capped below the configured
  max on cold days via a weather-forecast-driven derating curve
  (`core/bess/battery_system_manager.py:1917-1966`,
  `_get_temperature_derated_charge_limits`). If the weather entity isn't
  configured, this **silently returns no derating** rather than failing —
  so its absence in one installation vs. presence in another is expected,
  not a bug.
- **`charging_power_rate` setting is cosmetic after startup (known
  limitation, not a documented mechanism)**: this settings-page value only
  seeds the initial charge-power target once, before the first control
  cycle. Every cycle after that, the actual hardware charge rate comes from
  `INTENT_TO_CONTROL`, which only ever emits 0% or 100% — it never reads
  this setting again (`core/bess/battery_system_manager.py:2037-2064`,
  `adjust_charging_power`). If a user reports "changing the charge power
  rate slider did nothing," this is why — it is a known bug, tracked in
  `TODO.md`, not a settings-propagation issue to re-diagnose from scratch.

## Price Calculation

The optimizer works with buy and sell prices derived from spot prices:

    buy_price  = (spot + markup) * VAT_multiplier + additional_costs
    sell_price = spot + export_compensation

For Octopus Energy (UK), prices are already final — no markup/VAT applied.

For when a discharge is worthwhile, see **The Governing Economic Law** above —
gross `sell_price` vs `cycle_cost` is *not* the test; marginal value vs the
counterfactual is.


## Energy Flow Decomposition

The system decomposes measured energy totals into detailed flows using
energy conservation, but flows are **clamped to measured grid totals**
(`grid_imported`/`grid_exported`) rather than derived by pure subtraction —
pure subtraction can invent flows out of cross-sensor noise (fixed in PR
#342). See `core/bess/models.py` (`EnergyData._calculate_detailed_flows`,
~lines 90-146) and `core/bess/energy_flow_calculator.py` (~lines 176-183) for
the current formulas, e.g.:

    solar_to_battery = max(0, solar_production - export_to_grid
                             - self_consumption + battery_discharged)
    solar_to_battery = min(solar_to_battery, battery_charged, solar_production)

Home consumption gets solar first (free), then grid.  Battery charges from
solar first (free), then grid (paid) — but the exact split is reconciled
against measured grid import/export, not assumed from production figures
alone.

A second, related noise source lives one level up: even after #342's
zero-aggregate cap, a `battery_to_grid` residual can still survive when its
governing aggregate (`battery_discharged`) is itself nonzero — the residual
is then indistinguishable from ordinary lifetime-counter quantization
(documented 0.1 kWh resolution, `sensor_collector.py:235`) rather than a real
export, and it corrupts `infer_intent_from_flows`'s `observed_intent`
(`BATTERY_EXPORT` requires an inverter mode change; a residual this small
proves nothing about mode). Fixed in #350: `_calculate_detailed_flows` folds
any `battery_to_grid` below the 0.1 kWh floor back into `battery_to_home`,
but *only* when `battery_to_home > 0` — i.e. only when the battery was
already covering a genuine home deficit and the residual plausibly reflects
under-reading on that same deficit. When `battery_to_home == 0` (home's need
already fully met by solar), any nonzero export — however small — has no
other channel to have come from and is left as a real export (see the R==P
Bellman-guardrail regression test in `test_dp_no_guardrails.py`, which
requires exactly this for a genuine 0.05 kWh 100%-export discharge). Note the
DP's own planning-time classifier, `classify_strategic_intent` in
`strategic_intent.py`, already used `battery_to_grid > 0.1 kWh` as its
threshold — #350 brings the observational path's noise handling in line with
that existing precedent, though the two classifiers remain otherwise
distinct (planning vs. after-the-fact labeling).


## Prediction Snapshots and Expected Savings

Every time the optimizer runs, a **prediction snapshot** is saved recording:

    expected_savings = actual_savings + predicted_savings

- **Actual savings**: Sum of savings for completed time slots (past).
- **Predicted savings**: Sum of savings for future time slots (from the
  latest optimization schedule).

**Expected savings should NOT naturally decrease as time passes.**  As the
day progresses, predictions become actuals, but the total should stay
roughly the same IF the system performs as predicted.

If expected savings DROP between snapshots, it means something changed:

1. **Tomorrow's prices became available** — the optimizer now sees a longer
   horizon and may shift profitable discharge from today to tomorrow.
   Check: did the schedule's horizon expand?  Do tomorrow's prices exist?

2. **Actual solar was lower than forecast** — less free energy means more
   grid purchases.  Check: compare Historical Data solar column vs what
   the schedule predicted for the same time slots.

3. **Actual consumption was higher than estimated** — more demand than
   expected (e.g., EV charging).  Check: compare Historical Data import
   column vs schedule predictions.

4. **Prices changed between runs** — updated price data shifted the
   economics.  Check: logs for price fetch events.

**NEVER say savings "naturally decay" or "diminish over time."** A drop
is always caused by a specific, identifiable change.


## Consumption Prediction Strategies

The optimizer needs a consumption forecast.  Four strategies exist:

- **ha_statistics** (recommended): Builds a 96-period time-of-day profile
  from the past 7 days of HA Recorder data, bucketed by hour-of-day.  For
  each hour it drops only the single highest (and lowest, if ≥5 samples)
  of the 7 daily values before averaging.  This discounts a one-off
  irregular spike (e.g. an unusual EV charging session on one day) but
  does **not** strip out a regular/nightly EV charging habit — if most of
  the 7 samples for an hour are elevated together, the average stays high
  and the forecast correctly bakes that load in.  Higher during evening
  peaks, lower overnight.  A regular habit can be excluded deliberately via
  **Managed Loads**, below.
- **load_power_7d_avg**: Same concept, from the past 7 days of the `local_load_power` sensor in HA's recorder — 15-min resolution, and works on platforms with no lifetime load-energy entity.
- **sensor**: Reads a 48-hour rolling average sensor.  Produces a flat
  prediction (same value all day).
- **fixed**: A single fixed kWh/hour value.  Does not adapt.

**Refresh cadence** (issue #395): the quarterly optimization job (every 15
min) refreshes the consumption forecast on a strategy-aware basis, not just
at startup/23:55.  `sensor` and `fixed` refetch every quarterly cycle — cheap
and, for `sensor`, actually intraday-moving.  `ha_statistics` and
`load_power_7d_avg` average a window of full calendar days ending at today's
midnight, so that value is provably unchanged until the date rolls over —
they're cached and only refetched once the date changes, not on a clock
timer.  Solar has no cache at all: it's fetched live from the HA forecast
sensor on every quarterly run.

### Planned Consumption Changes (issue #428)

All four strategies above describe *normal* usage — they are built from
history, or from a constant.  None of them can know that the EV is charging
tonight, that the pool pump is being skipped, or that the house is empty for
a week.  The **overlay** is the input channel for exactly that: the user
declares what differs from normal, and BESS composes it onto whichever
strategy is configured.

It is **not a fifth strategy**.  It is a post-processing stage, so it applies
identically on top of `ha_statistics`, `load_power_7d_avg`, `sensor` and
`fixed`.  An install with no overlay entity configured keeps precisely the
forecast it would have had — "no overlay" is a supported configuration, not a
degraded one, which is why the feature has no cold-start step.

The user points BESS at a template sensor (`consumption_overlay`) whose
`blocks` attribute is a sparse list of timestamped spans:

    {start, end, energy_kwh, mode}

`energy_kwh` is the total for the whole span, apportioned across the periods
the span overlaps — so 15-minute, hourly and arbitrary block boundaries all
work, and a horizon longer than 96 periods needs no special case.  `mode` is
`add` (the default; negative values subtract) or `set` (replace the base
across the span).  A `set` block covering part of a period replaces only that
fraction, so a block ending at 07:10 does not erase 07:00–07:15 wholesale.

**Where it applies, and why that matters**
(`battery_system_manager.py::_apply_consumption_overlay`): in
`_gather_optimization_data`, *after* the daily prediction cache and *after*
the tomorrow-horizon extension.  Applying it inside `_get_consumption_forecast`
instead would trap it in the date cache — an overlay edited at noon would do
nothing until the next day — and would let the extension duplicate today's
blocks onto tomorrow while dropping blocks genuinely declared for tomorrow.

**DST**: the overlay builds its own period grid with
`consumption_overlay.period_starts_from`, stepping in UTC and converting back,
rather than using `time_utils.period_index_to_timestamp`.  That helper does
wall-clock arithmetic (`day_start + 15min * i`), which on the fall-back day
steps straight over the repeated local hour: index 11 lands at UTC 00:45 and
index 12 at UTC 02:00, so every later period is an hour late and the day's
last four indices collide with the next day's first four.  Harmless for the
display and logging that helper was written for; not harmless for a consumer
whose numbers depend on it, which the overlay is the first of.  The helper's
own flaw is untouched here and still awaits a fix.

**Failure behaviour**: a configured overlay entity that is missing,
unavailable, or malformed raises `ConsumptionOverlayError` rather than being
skipped — a user who declared an EV session is worse served by an
optimization that quietly ignored it.  The one exception is over-subtraction:
a block removing more load than the base forecast holds *in that period*
clamps it to zero (negative consumption is not physical) and records a
`CONSUMPTION_OVERLAY_CLAMPED` runtime failure, so it is surfaced rather than
silent.  Only periods the overlay itself drove negative count towards that
failure — a negative the base forecast already carried is floored the same
way but is not blamed on the overlay (issue #734).


### Managed Loads (issue #706)

`ha_statistics`'s trimmed mean (above) discounts a one-off spike but bakes in
a *regular* habit — a nightly EV charge reads as part of "normal" load, so
the learned baseline overstates typical consumption by however much of that
habit occurred in the 7-day training window.  Managed Loads is the
deliberate-exclusion mechanism: the user names the load's own
cumulative/lifetime energy sensor (`home.managed_load_sensors`, a list), and
its per-hour energy is subtracted from `lifetime_load_consumption`'s raw HA
Recorder statistics *before* the hour-of-day buckets are built, so the
learned "normal" becomes the residual — house load with the managed load
excluded.  The user then re-declares any expected managed-load energy via
Planned Consumption Changes (`add` mode), which composes on top of the
residual exactly as it does on top of any other baseline.

Scoped to `ha_statistics` only: `load_power_7d_avg` averages instantaneous
`local_load_power` samples from the recorder, a different data source/shape
than HA Recorder's cumulative `change` values, and needs its own subtraction
mechanism if ever added.

**Failure behaviour** (`managed_loads.subtract_managed_loads`): a configured
managed-load sensor with no statistics data raises `ManagedLoadsError` rather
than silently forecasting on the un-subtracted baseline — the forecast would
otherwise quietly overstate consumption by the missing residual. Subtraction
can only reduce recorded load, never invert it: an hour where the managed
load's own draw exceeds the total load sensor's (a sensor/entity mismatch) is
clamped to zero and logged, the same "surface it, don't absorb it" pattern
the overlay uses for over-subtraction.


## Savings Calculation

There are two savings metrics.  The distinction matters when reporting numbers:

**Total savings** (shown on the dashboard Savings card):

    total_savings = grid_only_cost - hourly_cost

This is the full benefit of having solar + battery compared to grid-only.

**Battery-only savings** (per-period `hourly_savings` in data tables):

    hourly_savings = solar_only_cost - hourly_cost

This isolates the battery's contribution on top of what solar already saves.

Total savings = solar savings + battery savings.  Summing per-period
`hourly_savings` gives a lower number than the dashboard total because it
excludes the solar benefit.

Positive savings = the system saved money.  Negative savings = the battery
action cost more than doing nothing (can happen during charging periods —
the benefit comes later when discharging).

Cost baselines:
- **grid_only_cost**: Cost if no solar or battery existed (all consumption from grid)
- **solar_only_cost**: Cost with solar but no battery optimization
- **hourly_cost** (aka optimized cost): Actual cost with full optimization


## Evidence-Based Analysis

When analyzing system behavior:

- Every claim must be backed by specific data — a row in the data tables,
  a log line, or a line of source code.
- NEVER speculate.  Do not use "likely", "probably", "suggests", "may have".
  State what happened with evidence, or say you don't have enough data.
- Start from what the data shows, not from a theory.
- Use tools (read_file, search_code) to verify claims against actual code.
