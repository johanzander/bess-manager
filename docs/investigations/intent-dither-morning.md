# Investigation: morning intent dither (`SOLAR_STORAGE` ⇄ `EXPORT_ARBITRAGE`)

**Status:** root cause confirmed; solution chosen and measured. Design spec:
[`../superpowers/specs/2026-06-18-intent-mode-hysteresis-design.md`](../superpowers/specs/2026-06-18-intent-mode-hysteresis-design.md).
**Severity:** cosmetic + operational (UI flicker + needless inverter-mode churn).
**Economic impact:** none — the optimizer's schedule is already cost-optimal.
**Reproduction data:** [`intent-dither-sample.txt`](./intent-dither-sample.txt) (anonymized user log, 2026-06-16).

## Symptom (as reported)

On a sunny day the schedule timeline shows the battery rapidly alternating
between **Storing Solar** (`SOLAR_STORAGE`, yellow) and **Selling to Grid**
(`EXPORT_ARBITRAGE`, green) all morning, even though the buy/sell spread is tiny
(~0.10 SEK) — far below the 0.40 SEK/kWh cycle cost.

## What the data shows

Battery (sample log §1): 20.0 kWh total, **2.2 kWh reserved (floor)**, 0.40
SEK/kWh cycle cost, started the day at **2.8 kWh** — ~0.6 kWh above the floor.

Morning section of the optimizer table (sample log §2, periods 26–49):

```
P26 06:30  buy/sell 1.46/1.14  Sol 0.6  SoE 3.19  Action -0.10  EXPORT_ARBITRAGE
P32 08:00  buy/sell 1.56/1.22  Sol 1.3  SoE 2.59  Action -0.10  EXPORT_ARBITRAGE
P35 08:45  buy/sell 1.48/1.16  Sol 1.3  SoE 2.29  Action -0.10  EXPORT_ARBITRAGE  (≈ floor)
P36 09:00  buy/sell 1.41/1.10  Sol 1.6  SoE 2.40  Action +0.10  SOLAR_STORAGE
P37 09:15  buy/sell 1.37/1.07  Sol 1.6  SoE 2.29  Action -0.10  EXPORT_ARBITRAGE
P38 09:30  buy/sell 1.31/1.02  Sol 1.6  SoE 2.40  Action +0.10  SOLAR_STORAGE
...
P50 12:30  buy/sell 1.02/0.79  Sol 1.9  SoE 4.75  Action +1.60  SOLAR_STORAGE  ← real charging
```

The optimizer is doing the right thing: drain the small overnight surplus to the
floor during the morning price peak (export), hold at the floor, then charge
midday at the lowest sell price for the evening peak. The morning behaviour is
cost-optimal.

## Root cause

`±0.1 kWh per quarter ≈ 0.4 kW`. The underlying optimal control near the floor is
**fractional** (the battery wants to move a fraction of a step per period). The DP
state grid (`SOE_STEP_KWH = 0.1`) can't represent a fraction, so it renders it as
an **alternating ±1-step pattern whose running average equals the fractional
target**. Each sign flip crosses the threshold in `classify_strategic_intent`
(`core/bess/decision_intelligence.py:414`), flipping the strategic intent, which
maps to an inverter mode change (`grid_first` ⇄ `load_first`) — needless Modbus
writes and a flickering UI. **The dither is the optimal trajectory drawn on a
coarse grid, not a bug in the economics.**

## What was ruled out (with evidence)

1. **Coarser SoE step (0.1 → 0.2):** degrades the whole optimization; doesn't
   remove dither (becomes ±0.2). Rejected.
2. **Magnitude filter — "remove all actions ≤ 0.1 kWh":** **catastrophic.**
   Measured cost went from −45.50 → −19.13 SEK (**+26.4 SEK**, savings halved).
   The morning −0.1 actions are *load-bearing* (drain-to-floor + export); zeroing
   them makes the battery idle and passively store the morning solar, charging to
   full by 10:00 — exactly wrong. A magnitude filter **cannot tell the ~0.4 kW
   dither from the ~0.4 kW real drain** — same magnitude.
3. **Tie-break in the DP argmax:** these aren't economic ties (the jagged path is
   the strict grid optimum; re-running with the anti-cycling gate disabled gave a
   byte-identical trajectory and cost). A threshold-free tie-break is a no-op.
4. **Constrain optimizer action space to ≥ min controllable power (Option A):**
   **measured worse.** At ≥0.5 kW: savings −0.41 SEK *and* mode-changes 10 → 14,
   morning flips 5 → 8. Forbidding small actions makes the battery overshoot and
   correct with larger ±0.2 swings — coarser control increases churn. Rejected.

## Chosen solution: downstream min-dwell hysteresis (Option C)

Leave the optimizer, reward function, and reported economics **untouched**. Insert
a stabilization stage between the per-period strategic-intent stream and the
inverter TOU schedule + UI: a mode change commits only when it **persists** (and
isn't a noise-level flip); short, sub-controllable flips inherit the prior mode.

Persistence is the discriminator that magnitude can't provide: the real drain
persists (same mode for many periods → commits), the dither alternates every
period (never persists → held).

**Measured (real day):** mode-changes 10 → **4** (dwell = 3), savings **identical
(62.48 SEK)**, morning stabilizes to `grid_first` (export/hold band) then
`load_first` (charge band). Result was the same at dwell 3 and 4 (insensitive).

Full design, parameters, edge-case handling, and validation plan are in the
[design spec](../superpowers/specs/2026-06-18-intent-mode-hysteresis-design.md).
