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

**Profit threshold**: After optimization, total savings are compared against
a minimum threshold scaled by remaining day fraction.  If savings are too
low, the schedule is rejected in favor of all-IDLE to prevent cycling for
marginal gains.


## Strategic Intents

Every 15-minute slot gets a strategic intent based on the energy flows the
optimizer chose.  These are classified from the actual flow pattern:

| Intent | Condition | What it means |
|--------|-----------|---------------|
| **GRID_CHARGING** | grid_to_battery >= 0.1 kWh | Buying cheap grid electricity to store in battery |
| **SOLAR_STORAGE** | solar_to_battery > 0.1 kWh, grid_to_battery < 0.1 | Storing excess solar production for later |
| **LOAD_SUPPORT** | battery_to_home > 0.1 kWh, battery_to_grid <= 0.1 | Using battery to power home (avoid expensive grid) |
| **EXPORT_ARBITRAGE** | battery_to_grid > 0.1 kWh | Selling stored energy to grid at high prices |
| **IDLE** | No significant battery flows | No profitable action — direct solar/grid consumption |

**Hardware mapping**: Intents control actual inverter behavior:
- GRID_CHARGING → battery_first mode + grid charge ON
- LOAD_SUPPORT → load_first mode
- EXPORT_ARBITRAGE → grid_first mode (enables grid export)
- SOLAR_STORAGE / IDLE → load_first mode (solar serves home first)


## Price Calculation

The optimizer works with buy and sell prices derived from spot prices:

    buy_price  = (spot + markup) * VAT_multiplier + additional_costs
    sell_price = spot + export_compensation

For Octopus Energy (UK), prices are already final — no markup/VAT applied.

A discharge is profitable when:
    sell_price (or avoided buy_price) > cost_basis + cycle_cost

Where cost_basis is the price at which the energy was originally stored
(tracked via FIFO), and cycle_cost is the battery wear cost per kWh.


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
