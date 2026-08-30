# VPP load tracking — design

**Issue:** #520 (VPP half). **Date:** 2026-08-23. **Status:** approved. The
economic model (`vpp_load_tracking.py` + the `simulate_vpp` budget branch,
opt-in and off by default) landed first; the live tick-loop / lifecycle /
frontend half is a follow-up.

## Problem

`LOAD_SUPPORT` on Growatt VPP releases control to the inverter entirely —
`_intent_to_vpp` returns `(0, False)`, remote control **disabled**, for any rate
(`solax_modbus_growatt_controller.py:424`, #413). The inverter then runs its own
load-following self-use, unbounded by anything the optimizer planned.

That release was itself a fix: forcing a fixed discharge rate caused avoidable
imports and exports whenever the plan's load forecast missed. But it overshoots.
Releasing means VPP can cover a spike and can never *hold*: when `shadow_price`
says the stored energy is worth more at the evening peak, VPP has no way to
express that, and the inverter self-consumes the reservation anyway.

The two platforms are therefore missing opposite halves of one behaviour, which
is what #520 exists to settle:

| | gate runs? | `LOAD_SUPPORT` behaviour | missing half |
|---|---|---|---|
| TOU / register | yes (since #524) | plan-scaled cap, ceiling raised when the gate is open | — |
| VPP | never | always releases control (#413) | **never holds** |

The economic test contains only prices and the plan:

```
buy_price × efficiency_discharge >= shadow_price
```

Nothing in it is platform-specific. Same house, same prices, same plan should
give the same behaviour on both platforms. It does not.

### Why the previous design was withdrawn

Draft PR #537 mapped a closed gate onto VPP as a `battery_first` hold. On TOU a
closed gate still delivers the planned discharge and merely declines to raise
the ceiling; on VPP that mapping delivers **nothing**. All 172 gate-closed
`LOAD_SUPPORT` periods in the then-36-fixture corpus carry a real planned
discharge — 118.11 kWh the design would have abandoned. Caught by @ridax67
before any test did; PR closed 2026-08-11.

The root cause of that failure is the thing this design has to fix. VPP carries
`BATTERY_EXPORT`'s planned magnitude faithfully, but collapses `LOAD_SUPPORT`'s
101 possible rates to a single command (release / don't release). **"Deliver the
plan, no more" is inexpressible on VPP today.** Any design that only re-maps the
existing command vocabulary inherits that, which is why the fix has to add
expressiveness rather than re-route it.

## Approach

Track `vpp_power` against measured house load between period boundaries, so the
commanded power is the *net* intent rather than a fixed figure real load eats
into. Unblocked economically on 2026-08-11 when @ridax67 supplied Growatt VPP
protocol **V2.01**, confirming `vpp_power` / `vpp_time` / `vpp_remote_control`
are **RAM** registers — a frequent write loop carries no flash-wear cost.
@ridax67 has run exactly this as a hand-written HA automation since day one on
VPP and reports the inverter shows no stress.

Tracking is what makes the bounded middle expressible: the battery follows real
load (so a spike is covered) up to a bound the plan sets (so a reservation is
protected). That is the same behaviour TOU got in #524, arrived at through the
one mechanism VPP's register model allows.

### Control law: energy budget, not power cap

Two readings of "no more" were considered.

A **power cap** — command `min(deficit, planned rate)` — cannot overshoot at any
instant and needs no state. But it leaves the spike under-covered: Frank's
reported 4.8 kW actual against a 1.96 kW forecast would command 1.96 kW and
import the remaining 2.84 kW, which is the failure #352 reports. It fixes the
waste without fixing the spike.

An **energy budget** — command the measured deficit, stop once the period's
planned kWh is spent — covers the spike while it lasts, then hands back.

The budget is correct because `shadow_price` prices a **kWh, not a kW**: the
gate's test is a per-kWh comparison, so the quantity worth bounding is energy.
The issue records the matching limitation, which argues the same way:

> `shadow_price` is the marginal value at the planned SoE. It is accurate for
> covering a modest overshoot; for a large one the true value of stored energy
> rises as SoE falls, so the test flatters battery use.

Bounding total energy is precisely what stops a large overshoot from running
past the point where that approximation holds. A power cap does not bound it at
all — it bounds the rate and lets the period run for its full duration.

**Budget exhaustion is a hand-back, not an error.** Once spent, the command
drops to hold and the remainder of the period imports. That is the reservation
being protected, and it is the intended outcome of a closed gate.

### Cadence: confined to the feature

The shared `BackgroundScheduler` keeps its existing cron cadence, unchanged.
Every job in `_init_scheduler_jobs` is a `CronTrigger` at one minute or slower;
adding a 10 s `IntervalTrigger` there would make a fast tick a property of the
whole runtime — thread-pool pressure, misfire listener, log volume, a new
scheduling primitive — for one platform's one intent.

Instead the tracking component owns its own clock. A dedicated worker exists
**only** while a tracking-eligible period is running, started and stopped at the
15-minute boundary by the code that already runs there (`apply_period`). When
the feature is off, or the period is not VPP + `LOAD_SUPPORT`, no thread exists.

Default tick 10 s, matching the P1 meter's own update rate (so it does not
sample faster than the data changes) and the cadence @ridax67 has proven on
hardware. Configurable, so a system that struggles can be dialled back without a
release.

The 1-minute alternative — reusing the existing cron — was rejected on the
design's own terms: a kettle cycle can begin and end inside one tick, and that
is the case the feature exists for.

### Opt-in

`vpp_load_tracking_enabled: bool = False`, following the existing shape of
`power_monitoring_enabled` (`settings.py:217`) and `export_curtailment_enabled`
(`settings.py:132`) — optional, sensor-dependent features defaulting off and
surfaced in `SettingsPage.tsx`. Shown only when control mode is VPP.

Opt-in **replaces** a capability/health-check gate rather than supplementing
one. Because the user has explicitly asked for tracking, there is no
silent-degradation path to design around: opted in with no resolvable load
sensor is a configuration error surfaced loudly in health, not a quiet fall back
to #413 release behaviour. That satisfies `rules.md`'s no-fallbacks rule
directly rather than by exception.

Shipping experimental first, per the platform-maturity convention. @ridax67 has
the hardware and an existing automation to compare against.

## Components

**Sensor input — already present, nothing new to configure.**
`SensorCollector._POWER_SENSOR_GETTERS` (`sensor_collector.py:742`) already
resolves `local_load_power` → `get_local_load_power()` alongside `pv_power`,
`import_power` and `export_power`, and `sample_live_power` already polls them
every minute (#387). The separate forward/reverse-counter case @ridax67
described for Growatt is handled upstream by `_resolve_power_sensor_ids`'s
sign-splitting getters (`sensor_collector.py:122-124`). This design consumes
that plumbing; it does not add a user-facing sensor setting.

**Ownership — BSM drives, controller maps.** The tick logic lives on
`BatterySystemManager`, which reads the sensors, computes the command and
delegates the write. The controller stays a stateless intent→register mapper.
This follows the API→BSM ownership pattern and keeps scheduling out of a class
whose job is mapping. A controller-owned thread was rejected for putting a
second scheduler owner in the fleet; a separate `VppLoadTracker` class was
rejected as indirection for one caller and one method — a pure helper function
gets the same testability.

**Write discipline.** Between boundaries the loop rewrites **only** `vpp_power`.
The full `vpp_remote_control` / `vpp_time` / `vpp_power` sequence is still
written at each 15-minute boundary by `apply_period` — per @ridax67, *"you still
need to send the correct sequence with time every 15 minute"* — which is also
what refreshes the fallback timer (#404). The controller already dedupes
unchanged writes via `_last_written_vpp_power`
(`solax_modbus_growatt_controller.py:134`), so a stable load produces no Modbus
traffic.

## Data flow

Each tick, while a tracking-eligible period is active:

1. Read `get_local_load_power()` and `get_pv_power()`.
2. `deficit = max(0, home − solar)`.
3. Subtract energy already spent this period from the budget.
4. Budget remaining → command `deficit`; budget spent → command hold.
5. Write `vpp_power` only if the commanded percentage changed.

The accumulator resets at the 15-minute boundary, where the gate's
`buy × efficiency >= shadow_price` test sets the budget for the period:

| gate | budget | meaning |
|---|---|---|
| **closed** | the period's planned discharge kWh | the reservation is worth more later — deliver the plan, no more. **This is the behaviour VPP cannot express today.** |
| **open** | unbounded within the period (bounded only by SoE floor, physical rating and AC headroom) | the energy is worth more used now than saved, so cover whatever load appears |

The open case is deliberately equivalent to today's released self-use, which is
why this design does not regress #413 — it adds the closed case that #413 threw
away. It mirrors TOU's `max(plan_scaled, intra_period_discharge_gate(...))`
from #524: a closed gate holds at the plan, an open gate raises the ceiling.

## Error handling

**Stale readings are the sharper risk than absent ones.** An absent sensor is
caught once, at opt-in, by the health check. A sensor that resolves and then
goes stale or returns garbage *while the loop is commanding power* is the
hazard, because the loop would otherwise hold a stale figure against a load that
has since changed.

Policy: a read failure, or a reading older than a staleness bound (**3 ticks**),
stops the loop commanding and **releases control** — reverting to today's #413
behaviour — rather than holding the last value. Logged once per period, not per
tick, and surfaced in health.

Releasing rather than holding is deliberate: released self-use is the behaviour
VPP has shipped for a year, so it is the known-safe state, whereas a stale
command is an unbounded claim about a load nobody is measuring.

A hardware dead-man's switch already backs this: `vpp_time`'s ~20-minute
fallback (#404) reverts the inverter to its own self-use if BESS stops writing
entirely.

## Testing

**Primary RED test is a plan-faithfulness scenario**, not a unit test on the
mapper — per `docs/agents/simulator.md`, a synthetic-input unit test on
`_intent_to_vpp` can pass while the new branch is unreachable by any real
DP-produced schedule.

```python
from core.bess.tests.helpers import run_scenario_realized
result, realized_cost = run_scenario_realized(scenario)
assert realized_cost == pytest.approx(result.total_cost, ...)   # R == P
```

`vpp_simulator` gains the budget-capped branch. Today its release branch models
the deficit as covered *"unconstrained by any planned rate"*
(`vpp_simulator.py:188`), bounded only by physical rating, SoE floor and AC
headroom — so the budget cap is a genuine simulated behaviour change, and
`R == P` only continues to hold if the simulator models it.

**The corpus and baseline do not move.** Because the flag defaults off, the
38-fixture corpus and the #539/#540 VPP baseline stay valid and need no
re-pinning; the new branch gets its own fixtures with the flag enabled. This is
the main reason the opt-in shape is smaller and safer than a default-on one — a
default-on version would have forced a deliberate re-pin of both.

Coverage to add:

- gate closed, load below plan → follows load, no overshoot, budget unspent
- gate closed, spike above plan → covers the spike, then hands back at
  exhaustion; planned discharge still fully delivered (the 118.11 kWh #537
  would have abandoned)
- gate open, spike → covers it without handing back, i.e. #413 behaviour is
  not regressed
- stale sensor mid-period → releases control, logged once
- flag off → byte-identical to today's #413 behaviour
- boundary → full write sequence, accumulator reset

Per `feedback_ui_controls_need_playwright`, the settings toggle needs an
`e2e/tests/*.spec.ts` covering its logic, not only a component unit test.

## Scope assessment

**Structural.** The work needs a new owner — a tick component and a settings
field — rather than fitting inside an existing method's contract. The owner is
BSM because it already owns sub-period control adjustment
(`adjust_charging_power`, `apply_discharge_inhibit`) and already holds the plan
the budget derives from.

**Workaround check.** The diff adds no parameter, flag, default-fallback, second
construction site or extra trigger whose only job is to route around an
ordering/timing/dependency problem. The one added flag is a user-facing opt-in
for an experimental feature, not an internal routing switch. The tracking loop
is not a workaround for the 15-minute cadence: it exists because the hardware
command is a forced power that only means the right thing when it is recomputed
against measured load — the same reason @ridax67's automation exists.

The one item to watch in review is the dedicated worker thread. It is confined
to the feature and to eligible periods by construction, but it is the piece most
likely to be argued as belonging on the shared scheduler; the reason it is not
there is recorded above.

## Dependency: #683 must land first

This design maps the gate's **decision** rather than its rate, so it inherits
whatever that decision is worth. #683 establishes that the decision is currently
biased: `_record_marginal_value` tests `buy × η >= shadow_price`, but
`_value_slope_below` returns `shadow_price` **undiscounted** in the
discharge-limited regime, because `SOE_STEP_KWH` (0.025) equals
`POWER_STEP_KW × dt` (0.025) while the SoE→delivery conversion carries η. The
value function is therefore a staircase whose riser is one full delivery step,
and a one-cell backward difference lands on a riser 19 times in 20.

The two sides are in different units, making the gate a factor `1/η` too strict
— it demands the current price beat the competing future price by 5.3%, and it
is wrong on exact ties. Verified reproducible on current `main`.

**Building the VPP half first would ship that bias to a second platform**: VPP
would faithfully hold in exactly the cases where the gate is wrong to close, and
the hold would look like correct behaviour because it is the behaviour #520 asks
for. Land #683, then build this.

Measured impact of the bias is small in money (~0.1 eurocent over the
diagnosed night) but confined to the overnight discharge-limited regime — which
is where users notice, because it is where the battery visibly holds charge
while the house imports.

## Out of scope

- The TOU half's *plumbing* — done, #524, and provably live: the gate raises the
  ceiling to 100% against a 7–8% plan-scaled rate in the diagnosed bundle. What
  is not done is the valuation it reads, which is #683 above.
- #571 / #579 — `np.round` snapping making `V` locally non-concave. Fixed and
  shipped in v10.1.0. A *different* defect at the same seam; it does not address
  the units mismatch, and at the diagnosed states it changes nothing (the SoEs
  land exactly on grid points, where `round()` and `ceil()-1` pick the same
  cell).
- #526 — `shadow_price == 0.0` at bottom-of-grid. Correctly handled already.
- Changing what the DP plans for VPP. 4a already declares Growatt VPP
  `LOAD_SUPPORT` load-following (because #413 releases control), and tracking
  keeps that declaration true, so the planner is untouched.

Refs #520, #352, #384, #385, #393, #413, #147, #324, #404, #466, #537, #539.
