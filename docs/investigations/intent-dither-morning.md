# Investigation: morning intent dither (`SOLAR_STORAGE` ⇄ `EXPORT_ARBITRAGE`)

**Status:** root cause confirmed; fix not yet implemented.
**Severity:** cosmetic + operational (UI flicker + needless inverter-mode churn).
**Economic impact:** none — the optimizer's schedule is already cost-optimal.
**Reproduction data:** [`intent-dither-sample.txt`](./intent-dither-sample.txt) (anonymized user log, 2026-06-16).

## Symptom (as reported)

On a sunny day the schedule timeline shows the battery rapidly alternating
between **Storing Solar** (`SOLAR_STORAGE`, yellow) and **Selling to Grid**
(`EXPORT_ARBITRAGE`, green) all morning, even though the buy/sell spread is tiny
(~0.10 SEK) — far below the 0.40 SEK/kWh cycle cost. The user suspected either
(a) wasteful charge/discharge cycling, or (b) that the algorithm stores solar in
the morning when it should sell it and charge later in the cheap midday dip.

## What the data actually shows

Battery for this run (sample log §1): 20.0 kWh total, **2.2 kWh reserved (floor)**,
0.40 SEK/kWh cycle cost, started the day at **2.8 kWh** — i.e. only ~0.6 kWh above
the floor after the night.

Morning section of the optimizer table (sample log §2, periods 26–49 ≈ 06:30–12:15):

```
P26 06:30  buy/sell 1.46/1.14  Sol 0.6  SoE 3.19  Action -0.10  EXPORT_ARBITRAGE
P32 08:00  buy/sell 1.56/1.22  Sol 1.3  SoE 2.59  Action -0.10  EXPORT_ARBITRAGE
P35 08:45  buy/sell 1.48/1.16  Sol 1.3  SoE 2.29  Action -0.10  EXPORT_ARBITRAGE
P36 09:00  buy/sell 1.41/1.10  Sol 1.6  SoE 2.40  Action +0.10  SOLAR_STORAGE
P37 09:15  buy/sell 1.37/1.07  Sol 1.6  SoE 2.29  Action -0.10  EXPORT_ARBITRAGE
P38 09:30  buy/sell 1.31/1.02  Sol 1.6  SoE 2.40  Action +0.10  SOLAR_STORAGE
...
P50 12:30  buy/sell 1.02/0.79  Sol 1.9  SoE 4.75  Action +1.60  SOLAR_STORAGE  ← real charging starts
```

Key facts:

1. **The battery does NOT meaningfully store in the morning.** SoE drifts from
   ~3.3 down to **2.29 kWh (≈ the 2.2 floor)** between 06:30 and 08:45 — it is
   *draining* its small overnight surplus and exporting it at the morning price
   peak (sell 1.14–1.22). After that it sits at the floor.
2. **Real charging starts at 12:30 (P50)** at the day's lowest sell price (0.79 →
   0.71), filling the battery for the evening peak. This is exactly the
   "sell morning, charge midday, discharge evening" strategy.
3. The morning `SOLAR_STORAGE`/`EXPORT_ARBITRAGE` labels are driven by **±0.10 kWh
   actions** while net SoE is flat at the floor — discretization dither, not real
   cycling.

### The optimizer is provably optimal here

Two checks (run against the real per-period data in the sample log):

- The DP already drains the morning surplus to the floor and refills midday —
  the reported behavior, not a bug.
- Re-running with the **anti-cycling discharge gate fully disabled**
  (`dp_battery_algorithm.py:304–340`, the `return float("-inf")` pruning removed)
  produced an **identical schedule and identical cost (−45.4995 SEK)**. So the
  gate is non-binding and is not suppressing any more profitable plan. A global
  optimizer with unrestricted discharge does not choose to drain harder and
  refill — the morning→midday spread (~0.31 SEK) does not cover the 0.40 SEK/kWh
  cycle cost of the extra round trip.

**Conclusion:** there is no economic optimization bug. The only defect is the
cosmetic/operational dither.

## Root cause

`classify_strategic_intent` (`core/bess/decision_intelligence.py:414`) labels each
period purely from the sign of the (sub-)threshold action and flow magnitudes:

```python
if power < -_POWER_THRESHOLD_KW:          # _POWER_THRESHOLD_KW = 0.1 kW
    if energy_data.battery_to_grid > 0.1:
        return "EXPORT_ARBITRAGE"
    return "LOAD_SUPPORT"
elif power > _POWER_THRESHOLD_KW:
    ...
    return "SOLAR_STORAGE"
```

When the battery is parked at its floor, the DP is economically **indifferent**
between SoE steps and emits ±0.10 kWh actions (one `SOE_STEP_KWH`) period to
period. Each sign flip crosses the intent classifier's threshold and flips the
strategic intent.

Downstream, every intent flip maps to an inverter mode change
(`EXPORT_ARBITRAGE → grid_first`, `SOLAR_STORAGE → load_first`; see
`core/bess/inverter_controller.py` and the controller mapping). The sample log
§3 shows the resulting intent transitions and §4 shows the TOU schedule churning
between `grid_first` and `load_first` six times across the morning — needless
Modbus writes for ~1 kWh of economically irrelevant shuffling.

## Proposed fix (dead-band / hysteresis)

Goal: suppress intent/mode changes driven by economically negligible sub-step
actions, **without** altering the optimizer's chosen SoE trajectory or its cost.

Two candidate layers (prefer the first; the second is optional belt-and-braces):

1. **Classifier dead-band** — in `classify_strategic_intent`, treat actions whose
   energy is at/below one `SOE_STEP_KWH` (0.1 kWh) *and* whose net battery-to-grid
   / solar-to-battery flow is below a small epsilon as `IDLE` rather than
   `EXPORT_ARBITRAGE`/`SOLAR_STORAGE`. This collapses the dither to a stable
   `IDLE` (Standby) band when the battery is effectively parked.

2. **Intent hysteresis at apply time** — in `battery_system_manager` where the new
   strategic-intent array is compared against the currently applied one
   (`Modbus strategic intents differ from period N`), do not trigger a schedule
   rewrite when the only differences are sub-threshold flips that don't change the
   physical battery mode meaningfully.

### Acceptance criteria

- On the reproduction data, the morning (P26–49) no longer alternates
  `SOLAR_STORAGE`/`EXPORT_ARBITRAGE` every period; it shows a single stable mode
  (expected: `IDLE`/Standby while parked at the floor).
- `result.economic_summary.battery_solar_cost` is unchanged (−45.4995 SEK on this
  data) — the fix must be display/scheduling only, not economic.
- A regression test reconstructs this scenario (settings + per-period
  buy/sell/solar/consumption from the sample log) and asserts both: (a) no
  per-period intent flip-flop while SoE is within one step of the floor, and
  (b) total cost unchanged vs. the pre-fix baseline.

## Files of interest

- `core/bess/decision_intelligence.py:414` — `classify_strategic_intent`
- `core/bess/dp_battery_algorithm.py:106` — `SOE_STEP_KWH = 0.1`
- `core/bess/dp_battery_algorithm.py:304–340` — anti-cycling discharge gate
  (confirmed non-binding here; do **not** change as part of this fix)
- `core/bess/battery_system_manager.py:1947–1979` — strategic-intent freezing /
  apply-time comparison
- `core/bess/inverter_controller.py` — intent → inverter mode mapping
- `frontend/src/components/BatteryModeTimeline.tsx` — consumes `strategicIntent`
