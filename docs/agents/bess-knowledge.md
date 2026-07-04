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

**Transition**: Each action updates SOE accounting for charge/discharge
efficiency losses and updates the **cost basis** of stored energy.

**Objective**: Minimize net electricity cost (grid import cost minus export
revenue) while accounting for battery cycle degradation costs and a terminal
value for energy remaining at end of horizon.

**Cost basis tracking (FIFO)**: When the battery charges at different prices
over time, the system tracks the cost of stored energy using FIFO (first-in,
first-out) accounting.  When the battery discharges, the oldest (cheapest)
energy is used first.  This determines the true profit of a discharge action.

**Profit threshold**: After optimization, the battery's own contribution
(`solar_only_cost - battery_solar_cost` — how much better the schedule is
than solar alone, not than a zero-solar grid-only baseline) is compared
against a minimum threshold scaled by remaining day fraction. If that's too
low, an all-IDLE fallback is computed as a candidate replacement — but it is
only used if it's actually cheaper than the rejected schedule. The fallback
still passively absorbs any solar surplus into available battery room and
pays wear cost on it, but never discharges to recoup that cost, so it isn't
automatically better than what it would replace.

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
DP's value-to-go slope), floored by `sell_price` when upcoming solar will replenish
the battery for free. It is **not** the sunk `cost_basis`, and **not** zero.

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
(`core/bess/dp_battery_algorithm.py:361-394`) implements this as an anti-cycling
floor — for a discharge it raises the effective floor to `sell_price` whenever solar
will replenish the discharged capacity, so `sell × efficiency_discharge < sell ≤
floor` blocks the trade. The function's older docstring phrasing ("value >
cost_basis") describes that floor's implementation, not the user-facing law above.

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
optimizer chose.  These are classified from the actual flow pattern:

| Intent | Condition | What it means |
|--------|-----------|---------------|
| **GRID_CHARGING** | grid_to_battery >= 0.1 kWh | Buying cheap grid electricity to store in battery |
| **SOLAR_STORAGE** | solar_to_battery > 0.1 kWh, grid_to_battery < 0.1 | Storing excess solar production for later |
| **LOAD_SUPPORT** | battery_to_home > 0.1 kWh, battery_to_grid <= 0.1 | Using battery to power home (avoid expensive grid) |
| **BATTERY_EXPORT** | battery_to_grid > 0.1 kWh | Selling stored battery energy to grid at high prices |
| **SOLAR_EXPORT** | power ≈ 0, solar_to_grid > 0.01 kWh | Solar surplus exporting directly to grid, battery idle |
| **IDLE** | No significant battery flows | No profitable action — direct solar/grid consumption |

**Hardware mapping**: Intents control actual inverter behavior:
- GRID_CHARGING → battery_first mode + grid charge ON
- LOAD_SUPPORT → load_first mode
- BATTERY_EXPORT → grid_first mode (battery discharge to grid)
- SOLAR_STORAGE / SOLAR_EXPORT / IDLE → load_first mode (solar serves home first)

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
> **`buy_price × discharge_efficiency ≥ shadow_price` → rate 100, else rate 0`.**
> (The efficiency factor applies only to the buy side — the shadow price is
> already per-kWh-of-stored-energy.)

What this works out to in practice — important for analysis:
- During SOLAR_EXPORT the battery is full and exporting surplus, so its marginal
  kWh is only worth the **export (sell) price** — the surplus refills it for
  free (replenishment).  The shadow price therefore ≈ the sell price.
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
energy conservation:

    solar_to_home    = min(solar_production, home_consumption)
    solar_to_battery = min(remaining_solar, battery_charged)
    solar_to_grid    = remaining_solar - solar_to_battery
    grid_to_home     = home_consumption - solar_to_home
    grid_to_battery  = battery_charged - solar_to_battery

Home consumption gets solar first (free), then grid.  Battery charges from
solar first (free), then grid (paid).


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
  from the past 7 days of HA Recorder data.  Uses trimmed mean to filter
  out spikes like EV charging.  Higher during evening peaks, lower overnight.
- **influxdb_7d_avg**: Same concept but queries InfluxDB instead of HA.
- **sensor**: Reads a 48-hour rolling average sensor.  Produces a flat
  prediction (same value all day).
- **fixed**: A single fixed kWh/hour value.  Does not adapt.


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
