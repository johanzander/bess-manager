# Design: closed-loop savings simulator (applied modes → realized flows → savings)

**Date:** 2026-06-18
**Motivated by:** [`../../investigations/intent-dither-morning.md`](../../investigations/intent-dither-morning.md)
and the realization that no test today can verify the realized economic impact of
an inverter-control change.

## Why this exists

Every savings figure in the system and the test suite is the **optimizer's
open-loop plan**, computed from the chosen battery *actions* (`optimize_battery_schedule`
→ `PeriodData.economic`). Nothing computes "given these *applied inverter modes*
and real conditions, what savings actually result." Confirmed:

- `scripts/mock_ha/server.py` is **record-and-replay** — static sensors + recorded
  service calls. A mode command does not evolve SoC from solar/load.
- `tests/integration/test_cost_savings_flow.py` asserts the optimizer's *planned*
  savings, not a simulation of inverter control.

Consequence: the realized economic impact of any applied-mode change (e.g. the
intent-dither hysteresis) is **unverifiable** with current tests. The whole
control layer is tested for *translation correctness* (right TOU registers for an
intent), never for *resulting savings*. This simulator closes that gap and is the
prerequisite for the intent-dither fix (PR #141).

## Goal

A faithful, validated simulator that takes a sequence of **applied control
commands** + **real conditions** and returns **realized energy flows and
savings** — enabling A/B comparison of two command sequences (e.g. optimizer's
raw modes vs hysteresis-stabilized modes) with a trustworthy savings delta.

## Scope

**In (v1):**
- Sequential within-day SoC evolution under applied inverter modes (SoC carries
  forward period to period — this is the "closed loop" for state).
- Realized flows (solar→home/battery/grid, grid→home/battery, battery→home/grid)
  and realized cost/savings using the **existing** price/cost accounting
  (`EnergyData` / `EconomicData`) so results are apples-to-apples with reported
  planned savings.
- Per-platform mode semantics for the **Growatt MIN / modbus** path first (the
  platform in the reproduction log and one of the only real-world-tested
  platforms).
- A **calibration/validation harness** against real debug logs.

**Out (v1) — explicit non-goals:**
- Re-running the optimizer with simulated actuals (the full re-optimization
  feedback loop). v1 simulates *execution* of a fixed command sequence; it does
  not close the loop back into planning. Flagged as a later extension.
- Platforms beyond Growatt MIN (SPH, SolaX) — add once the core is validated.
- Battery degradation beyond the existing cycle-cost model.

## Design

- **New module:** `core/bess/simulation/inverter_simulator.py`.
- **Core entry point** (shape, not final signature):
  `simulate(control_sequence, conditions, battery_settings, initial_soc) -> SimulationResult`
  - `control_sequence`: per-period applied mode (`grid_first` / `load_first` /
    `battery_first`) + charge/discharge rate — i.e. what the controller would
    actually write.
  - `conditions`: per-period `solar`, `home_consumption`, `buy_price`,
    `sell_price`.
  - `SimulationResult`: per-period realized `EnergyData` + `EconomicData`, plus a
    total realized cost / savings-vs-grid-only.
- **Per-period model:** given mode + conditions + current SoC, apply the
  platform's mode policy to determine the battery charge/discharge that period,
  then derive detailed flows via the **existing** `EnergyData` logic and carry SoC
  forward. Where possible reuse existing primitives (`_state_transition`'s
  passive-solar/charge-rate clamping already models the `load_first` idle case).
- **Mode policy** is encoded explicitly and documented from the controller
  mappings (e.g. `EXPORT_ARBITRAGE→grid_first` exports solar + discharges to grid
  per rate; `SOLAR_STORAGE/IDLE/LOAD_SUPPORT→load_first` self-consume + store
  surplus; `GRID_CHARGING→battery_first` charges from grid). This mode→behaviour
  mapping is the genuinely new logic and the main fidelity risk.

## Validation — three checks, only one of which is a tolerance

These are deliberately separated; conflating them hides real economic effects.

### 1. Exact internal consistency (to the cent)

The simulator shares `EnergyData` / `EconomicData` and the price/cost accounting
with the optimizer. Therefore, where an applied mode maps to an **unambiguous**
battery action, the simulator must reproduce the optimizer's per-period flows and
`economic.hourly_cost` **exactly** (within float rounding). This proves the
accounting is wired identically and is a no-tolerance unit/integration test.

### 2. The A/B economic gate (to the cent — this is what gates a control change)

A control change (e.g. the hysteresis) is judged by the **delta of realized
savings** between two command sequences run through the **same** simulator under
the **same** conditions:

```
delta = realized_savings(modified modes) − realized_savings(baseline modes)
```

Because simulator-vs-reality error is identical on both sides, **it cancels in the
delta** — so this is reported and asserted **exactly, to the cent**, not within a
percentage band. A band here would *mask* a real loss. If `delta == 0` the change
is provably economically neutral; if non-zero, the exact figure is surfaced for an
explicit accept/reject decision. **No tolerance.**

> Note: `realized != planned` in general, and that is expected — inverter modes
> are *policies* (`grid_first`/`load_first`), not power setpoints, so the executed
> power is whatever conditions dictate under the policy, not the optimizer's exact
> planned power. This plan-vs-execution gap **pre-exists** any control change; the
> gate above compares realized-vs-realized, not realized-vs-planned.

### 3. Model-fidelity calibration vs real logs (the only tolerance, and it is not the gate)

To trust that our `mode → flow` *policy model* matches the real inverter, feed the
simulator the **actually-applied modes + actual conditions** from real debug logs
and check it reproduces the **measured** SoC/flows. Reality carries weather
deviation, measurement noise, and unmodeled losses, so this check is inherently
**within a tolerance** (starting point, to be tightened empirically: per-period
SoC ±0.2 kWh, per-period grid energy ±0.2 kWh). This validates the *model*, not a
control change. If it cannot reproduce actuals within tolerance, that is itself a
finding — our mode→behaviour understanding is incomplete — and must be resolved
before checks 1–2 can be trusted.

## How it unblocks the intent-dither hysteresis

A/B harness, once the simulator is fidelity-validated (check 3):

1. Day conditions → `optimize_battery_schedule` → schedule.
2. Derive (a) baseline applied modes and (b) hysteresis-stabilized modes.
3. Simulate both → realized savings A and B (same simulator, same conditions).
4. Report `delta = B − A` **exactly, to the cent** (check 2). `delta == 0` ⇒ the
   hysteresis is provably economically neutral; a non-zero delta is the exact
   economic impact, surfaced for an explicit accept/reject decision — never hidden
   in a tolerance band. Evaluated across the reproduction day and a set of
   scenarios.

This is the economic verification that is currently impossible.

### Reusing existing scenarios

The existing scenario JSONs already feed the optimizer (`base_prices`,
`home_consumption`, `solar_production`, `battery`). The simulator tests reuse them:
optimizer → derive modes → simulate. Lock regressions by extending the schema with
`expected_planned_savings` and `expected_realized_savings`; A/B fixtures assert
`realized(baseline) == realized(hysteresis)` exactly. Add a *dithering* scenario
(the reproduction day, generatable via `scripts/mock_ha/scenarios/from_debug_log.py`)
and *calibration* scenarios that carry the **measured actual** flows for check 3.

## Risks

- **Fidelity of mode→behaviour modeling** (per platform) is the hard part —
  mitigated by the calibration gate against real logs (no calibration, no trust).
- **Tolerance choice** trades sensitivity vs false alarms; start loose, tighten as
  the model proves out against multiple logs.
- **Scope creep** toward the full re-optimization feedback loop — explicitly
  deferred; v1 is execution-only.

## Decisions to confirm

1. **Platform scope v1 = Growatt MIN / modbus only** (the reproduction platform).
   Agree?
2. **v1 is execution-only** (no optimizer re-run feedback loop). Agree to defer the
   full loop?
3. The **A/B economic gate is exact (to the cent)** — no tolerance; a tolerance
   exists *only* for model-fidelity calibration vs noisy real logs (check 3).
   Agree with this split?
