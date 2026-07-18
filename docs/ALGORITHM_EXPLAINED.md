# BESS Algorithm Explained

This document explains how BESS Manager actually decides what to do with your
battery — the reasoning model, the economics, and what the schedule labels
mean. It's written for anyone who wants to understand *why* a schedule looks
the way it does, not just how to read the dashboard (see
[USER_GUIDE.md](USER_GUIDE.md) for that) or how the code is structured (see
[SOFTWARE_DESIGN.md](SOFTWARE_DESIGN.md) for that).

## 1. What Kind of System This Is

BESS is a **financial optimizer**, not a rule-based scheduler. It doesn't
have a library of named strategies it picks between — "charge in the
morning," "discharge at the evening peak," and so on aren't modes you select
or the system chooses among. There is one algorithm: given prices, forecasts,
and the battery's current state, it computes the schedule of charge/discharge
actions that minimizes your total electricity cost over the time horizon it
can see. Everything the dashboard shows — GRID_CHARGING, SOLAR_STORAGE,
BATTERY_EXPORT, and the rest — is a *label describing what that one
computation decided*, applied after the fact by looking at the resulting
energy flows. Nothing in the optimizer consults a label to decide what to do;
the label is assigned to describe what it already did.

That doesn't make the labels unimportant — they do real work, just not the
work of "choosing a strategy." Different inverter platforms (Growatt
MIN/MID/MOD, Growatt SPH, SolaX) need different low-level commands to
accomplish the same intent — one might need a TOU-segment write, another a
per-period Modbus register, another a persistent active-power command. The
intent labels are the abstraction layer that makes this possible: the
optimizer's output is translated once into a small set of labels
(GRID_CHARGING, SOLAR_STORAGE, LOAD_SUPPORT, BATTERY_EXPORT, SOLAR_EXPORT,
IDLE), and each inverter platform's controller has its own mapping from those
labels to the actual hardware calls it needs to make. That's what lets one
optimizer support genuinely different hardware without duplicating the
decision logic per platform.

## 2. Inputs to the Algorithm

Every time the optimizer runs, it's given:

- **A price forecast** — buy and sell price for every 15-minute period from
  now through the end of available data. This typically covers the rest of
  today; once tomorrow's day-ahead prices are published (time varies by
  provider), the horizon extends to cover tomorrow too.
- **A solar production forecast** — expected solar output per period, from
  your configured forecast source.
- **A consumption forecast** — expected home load per period. Several
  strategies exist for producing this, covered in
  [USER_GUIDE.md's Consumption Prediction section](USER_GUIDE.md#consumption-prediction).
- **The battery's current state** — its state of energy (SOE, in kWh) and
  the cost basis of what's currently stored (see below).
- **Battery parameters** — total capacity, min/max SOE limits, max
  charge/discharge power, charge and discharge efficiency, and the cycle
  cost (see [Section 4](#4-the-economics-explicitly)).

## 3. How the Optimizer Reasons

The algorithm is **dynamic programming** using **backward induction**:
starting from the last period in the horizon and working backward to now, it
evaluates every feasible action (charge / discharge / idle) at every period,
and computes the best achievable outcome from that point onward for each
possible battery state. By the time it reaches the current period, it knows
— for every possible starting state of energy — what the optimal action is
and what it's worth. It then reads off the schedule forward from the
battery's actual current state.

This search works over a discretized grid: the battery's possible state of
energy and the possible power levels at each step are both broken into a
finite set of values, not treated as continuous. This is a computational
necessity — dynamic programming needs a finite state space to search
exhaustively — not a modeling choice with independent significance. The
specific granularity is an implementation detail that can change, so it's
not documented here.

**Shadow price**: at each period, the backward pass produces a **value-to-go**
for every possible state of energy — the best achievable result from that
point onward, for that state. The *slope* of that value across state of
energy is the **shadow price**: how much one additional kWh of stored energy
is worth right now, given the optimal use the algorithm can find for it
across the rest of the horizon. This is a forward-looking number. It
automatically accounts for everything the optimizer might do with that kWh
later — avoid a future expensive grid purchase, sell it at a future high
price, or, if upcoming solar will refill the battery anyway, add nothing
extra at all.

**Cost basis** is a different, backward-looking number: what the currently
stored energy actually cost to acquire, tracked as a running weighted
average as the battery charges from different sources at different prices.
It's a sunk cost — useful for reporting and for validating that a plan makes
sense, but it does not drive the optimizer's decisions. The forward-looking
shadow price does.

**The governing rule**: every action is judged by its **marginal value
against the next-best alternative for that same slot** — never by its gross
value, and never against "doing nothing = 0." Concretely:

- Discharging to the grid is worthwhile only if the sell price (after
  discharge efficiency losses) exceeds the opportunity cost of that stored
  energy — its shadow price, not its cost basis.
- Discharging to cover home load is worthwhile only if it beats the
  cheapest alternative for that energy, usually a future avoided grid
  import at a higher buy price.
- Charging is worthwhile only if the stored energy's future value exceeds
  what it costs to store — the price paid for it (grid or forgone solar
  export) plus the cycle-wear cost.

A common but incorrect way to judge a decision is comparing the *gross* sell
price against the wear cost — "sell price is €0.46, wear cost is €0.40, so
selling nets €0.06, profitable." That's wrong because it ignores what the
real alternative was. If the real alternative to discharging now was to let
solar charge for one more period and export *then* instead, the value
actually captured is only the *difference* in sell price between those two
moments — often much smaller than the gross sell price — and that difference
has to clear the wear cost on its own. A €0.06 differential against a €0.40
wear cost is a loss, not a €0.06 gain.

**Why there's no fixed price threshold**: a related, common assumption is
that there's a rule like "don't charge unless the price is at least the
cycle cost below today's peak." There is no such rule anywhere in the
system. Every slot's action is judged against the specific alternatives
available to that slot — which differ throughout the day, and even between
re-optimizations on the same day as new information arrives — not against a
single number picked from the day's price curve.

**The numerical safety net**: after building a schedule, the system also
computes a plain all-IDLE schedule (battery untouched, solar passively
absorbed) and uses whichever of the two is cheaper. This is not a
configurable threshold and not an economic judgment call — backward
induction already guarantees the optimizer's own schedule can never come out
worse than doing nothing, since idling is always one of the actions
available at every period. The only way the built schedule could still cost
a hair more than all-IDLE is a tiny numerical artifact from the discretized
state grid, and this comparison exists purely to catch that.

## 4. The Economics, Explicitly

**Buy and sell price** are derived from the spot price plus your configured
contract terms:

```
buy_price  = (spot + markup) × VAT_multiplier + additional_costs
sell_price = spot + export_compensation
```

(Provider-specific — some providers, like Octopus, already publish a final
per-contract price with no separate formula needed.) Buy and sell price are
often quite different for the same spot value, because markup and VAT
typically apply to imports and not to exports — this asymmetry is real and
is one reason a decision can look surprising if you're mentally using one
price where the optimizer is using the other.

**Three cost baselines** are used to measure how well the system is doing:

- **grid_only_cost** — what you'd pay if you had no solar and no battery,
  buying every unit of consumption from the grid. The reference point for
  "how much is this whole system worth."
- **solar_only_cost** — what you'd pay with your solar installed but no
  battery optimization (solar covers what it can, the rest comes from the
  grid, any surplus is exported). The reference point for "how much is the
  battery specifically adding."
- **hourly_cost** (optimized cost) — what you actually pay with the full
  system running.

From these, two different savings numbers are computed, and they answer
different questions:

```
total_savings   = grid_only_cost - hourly_cost      (solar + battery, full benefit)
battery_savings = solar_only_cost - hourly_cost      (battery's contribution on top of solar)
```

`total_savings` is what the dashboard's headline Savings figure shows.
`battery_savings` isolates just the battery's part — summing it will give a
smaller number than the dashboard total, because it deliberately excludes
the benefit solar alone already provides. Negative savings for a period
doesn't mean something went wrong — it commonly shows up during a charging
period, where the cost is paid now and the benefit arrives later when that
energy is used or sold.

**Cycle cost**: charging or discharging the battery has a modeled wear cost,
configured as `cycle_cost_per_kwh` — a per-kWh charge applied to energy
moved through the battery, representing degradation. This is not money your
utility ever sees; it's the algorithm's own estimate of what cycling the
battery is costing you in shortened lifespan, and it's the number that has
to be cleared by the marginal value comparison described in
[Section 3](#3-how-the-optimizer-reasons) before any charge or discharge is
worth doing. It's also the practical lever if you want to change how readily
the battery cycles against a given price spread: raise it and the optimizer
needs a bigger spread to justify moving energy through the battery; lower it
and smaller spreads become worthwhile. Change it only if it doesn't reflect
what your battery's actual degradation costs you — it isn't a dial for
tuning "more aggressive" behavior for its own sake.

## 5. Energy Flow Decomposition

Sensors report a handful of aggregate totals per period — solar produced,
battery charged, battery discharged, grid imported, grid exported, home
consumption. The system decomposes these into the detailed flows shown on
the dashboard (solar→home, solar→battery, solar→grid, grid→home,
grid→battery, battery→home, battery→grid) using energy-conservation logic,
with one important correction: the detailed flows are **capped by the
measured totals**, not derived by pure subtraction. Independent sensors
occasionally disagree by a small, expected amount (the system tolerates up
to roughly 0.2 kWh of cross-sensor noise per period without treating it as
an error) — deriving flows by pure subtraction can turn that noise into an
invented flow to an entity that actually consumed or discharged nothing.
Capping each flow at what its governing total actually allows avoids that.

The energy-conservation logic follows a fixed priority order: solar serves
home consumption first, then the battery, with any remainder going to the
grid — the same order for the battery's charging source (solar first, grid
second). This "priority" is about how the *already-known* totals for a
period get split into that detailed breakdown for reporting — it's a
bookkeeping convention, not a decision the algorithm makes at run time (the
actual charge/discharge decision is driven by the economics in
[Section 3](#3-how-the-optimizer-reasons)). Concretely: if a period measured
3 kWh of solar, 1 kWh of home consumption, and 2 kWh of battery charging, the
breakdown attributes solar to home first (1 kWh, since solar is free and
home load is served by it before anything else is considered), then
whatever solar remains to the battery (2 kWh here — exactly enough, so
nothing was left to export or need from the grid in this example). If home
consumption exceeds what solar covers, the shortfall
is attributed to the grid; same for the battery — solar first, grid for
whatever charging solar didn't cover.

One consequence worth calling out because it surprises people: **solar can't
be shifted between periods.** Whatever surplus your panels produce in a given
15-minute period is captured, exported, or used at home *in that same
period* — there's no way to skip storing one period's solar in hopes of
storing it later at a better price. By the next period, that energy is
already gone (already exported or consumed), and a new period's solar
production is what's on offer. So a schedule that stores solar during a
period with a mediocre sell price isn't a worse choice than waiting — that
period's solar was only ever available then.

## 6. What Each Intent Label Means

Every 15-minute period gets a label describing the energy flows the
optimizer's decision produced for it, assigned after the fact by looking at
those flows:

| Intent | What it describes |
|---|---|
| **GRID_CHARGING** | The battery is being charged from the grid — the current buy price is cheap enough that storing it (net of wear cost) is worth more than not. |
| **SOLAR_STORAGE** | Solar surplus is being stored in the battery instead of exported — holding it for later use or sale is currently worth more than exporting now. |
| **LOAD_SUPPORT** | Stored energy is powering the home directly — avoiding that grid purchase right now is the best use the optimizer found for that energy. |
| **BATTERY_EXPORT** | Stored energy is being sold to the grid — at this price, selling now beats every other use the optimizer can find for it across the rest of the horizon. |
| **SOLAR_EXPORT** | Solar surplus is going straight to the grid, battery untouched — storing it wouldn't currently clear the wear cost, or the battery has no room. |
| **IDLE** | No battery action clears its cost right now — nothing is cheap enough to be worth charging into, and nothing currently needs the stored energy enough to beat holding it. |

The exact numeric conditions used to classify a period's flows into one of
these labels are implementation detail (in `core/bess/decision_intelligence.py`)
and can change independently of this document — the table above describes
the economic story each label represents, not a formula to reproduce.

Two clarifications worth making explicit, since they're easy to get wrong:

**IDLE vs. SOLAR_STORAGE** aren't distinguished by how much activity there
is. SOLAR_STORAGE covers any period where the battery's stored energy
measurably increased at all, including a small passive trickle far too small
to represent an active charging decision. IDLE is the true fallback: no
measurable charging, no measurable discharging, and no measurable solar
export either — e.g. solar production and home consumption happened to
roughly match, so nothing meaningful moved in any direction that period.

**A period's flows aren't reduced to "whichever is biggest."** Solar can be
flowing to the battery *and* to the grid in the same period — e.g. the
battery absorbs solar up to its remaining room while genuine surplus beyond
that is exported at the same time. That period is still labeled
SOLAR_STORAGE, because the label describes what the battery itself did (it
charged), not a comparison of which flow carried more energy. Classification
looks at the battery's own net action first (its power, or its net change in
stored energy when power rounds down to noise), then which source explains
that action — it never compares flow magnitudes against each other to pick a
"dominant" one. In practice this shows up when the battery reaches its
maximum state of energy mid-period: solar keeps arriving, the battery has no
more room, and the surplus is exported in the same period the battery was
still charging — still labeled SOLAR_STORAGE.

**Why BATTERY_EXPORT and SOLAR_EXPORT are different labels**, even though
both send energy to the grid: on some inverter platforms they require
genuinely different hardware modes — BATTERY_EXPORT means the battery is
actively discharging to the grid for profit, which needs the inverter told
to actively push power out; SOLAR_EXPORT means the battery is idle (often
full), with only the solar surplus flowing to the grid, and the battery
itself shouldn't be pushed to export. Conflating the two into one mode used
to lock some inverters into grid-export behavior for hours during sunny
periods even while the battery sat unable to help the house — that's why
the split exists. But the split isn't purely a hardware necessity: the two
are genuinely different economic decisions (one is "sell stored energy now
because that beats every other use for it," the other is "there's nothing
better to do with this surplus than export it"), and keeping them separate
also gives a clearer picture in the dashboard of what's actually happening,
independent of which hardware is involved.

One nuance specific to SOLAR_EXPORT periods: whether a brief mid-period dip
in solar (solar output fluctuating faster than the 15-minute schedule
resolution) gets covered from the battery or from the grid is itself an
economic decision, made fresh each period from the shadow price — the
battery covers it only when the stored energy is currently worth less than
buying that same amount from the grid. Seeing this choice flip between
periods on an otherwise-similar SOLAR_EXPORT stretch is not a bug; it
reflects that comparison changing as prices and the shadow price move.

## 7. Continuous Re-optimization

The system re-runs the full optimization every 15 minutes, using the latest
actual measurements in place of what was previously predicted. This means
the schedule you're looking at is a live prediction, recalculated from
whatever is currently known — not a fixed commitment. It's expected to
change, for any of several reasons:

- **Tomorrow's prices become available** (timing varies by provider) — the
  horizon extends, and the optimizer may find it more profitable to shift
  energy from tonight's plan into tomorrow's.
- **Actual solar or consumption differs from what was forecast** — less
  solar than expected means more grid purchases; more consumption than
  expected means the same.
- **The battery's actual state differs from what was predicted** — a
  fresh optimization always starts from the real current state, not the
  previously predicted one.

**Terminal value**: when the horizon does *not* yet extend into tomorrow
(tomorrow's prices aren't published yet), the optimizer has no visibility
past the end of what it can see — without some estimate of what leftover
stored energy is worth beyond the horizon, it would have no reason not to
drain the battery completely in the last visible period. To avoid that, any
energy still stored at the horizon's end is assigned an estimated value
based on typical prices, capped so it can never exceed what could actually
be realized by selling right now at the best available price. This is the
mechanism to check first if the battery appears to be holding charge near
the end of what's currently known, or not fully discharging right before
midnight — once tomorrow's real prices arrive and the horizon extends, this
estimate is replaced by the real future prices, and the schedule
re-optimizes against those instead.

**Expected savings and why the number can look like it drops**: at each
optimization run, the system records `expected_savings = actual_savings (for
completed periods) + predicted_savings (for the remaining schedule)`. This
total should stay roughly stable over the course of a day, if the system is
performing as predicted — it's the total of what's already realized and
what's still expected. If it drops between two snapshots, that's always
caused by one of: tomorrow's prices arriving and shifting value into a
longer horizon, actual solar coming in lower than forecast, actual
consumption coming in higher than forecast, or prices changing between
optimization runs. It is never "natural decay" — a drop always traces to a
specific, identifiable change in the inputs.
