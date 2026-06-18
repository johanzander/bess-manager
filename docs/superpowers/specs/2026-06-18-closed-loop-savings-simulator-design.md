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

A simulator that, on the **same scenario inputs** the optimizer used (solar, home
consumption, buy/sell prices), takes the **applied control commands** derived from
a plan and returns the **realized energy flows and savings** of executing those
commands. The bar: executing the plan's control should reproduce the plan's
economic output **exactly** — and any gap is a finding, not noise.

This is a **pure simulation**. We are not comparing against real hardware or
measured logs; there is no "reality" to calibrate against here. We are verifying
that the **control layer faithfully executes what the optimizer planned**, and
that a control change (the hysteresis) doesn't alter that.

## Scope

**In (v1):**
- Sequential within-scenario SoC evolution under applied inverter modes (SoC
  carries forward period to period).
- Realized flows (solar→home/battery/grid, grid→home/battery, battery→home/grid)
  and realized cost/savings using the **same** price/cost accounting
  (`EnergyData` / `EconomicData`) **and the same discretization** as the
  optimizer — so that faithful control yields cent-exact equality and any residual
  difference is meaningful, not a numerical artifact.
- Per-platform mode semantics for the **Growatt MIN / modbus** path first.

**Out (v1) — explicit non-goals:**
- **Validation against real-world logs / measured hardware data.** Out of scope —
  this is a scenario-driven simulation, not a hardware-fidelity exercise.
- Re-running the optimizer with simulated actuals (the full re-optimization
  feedback loop). v1 simulates *execution* of a fixed command sequence; it does
  not close the loop back into planning.
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

## Validation — two exact checks, no tolerances

Both checks are **cent-exact**. There is no tolerance anywhere: this is a pure
simulation sharing the optimizer's accounting and discretization, so a faithful
result is an *exact* result. A mismatch is a finding to investigate, never a band
to widen.

### 1. Plan-faithfulness — realized economics == planned economics (the core bar)

For each scenario, run the optimizer to get the plan and its economic output `P`,
derive the applied control commands from the plan, simulate executing those
commands on the **same scenario inputs**, and assert the realized economic output
`R == P` **exactly**.

This is the central claim you are asserting and I now agree with: *if the control
layer faithfully executes the plan, the simulated economics must equal the planned
economics.* So:

- `R == P` ⇒ the control layer faithfully realizes the plan. ✅
- `R != P` ⇒ a **finding**: the modes/TOU commands do **not** losslessly carry the
  optimizer's planned control. This is more fundamental than the dither symptom —
  it would mean part of the optimizer's claimed savings is not realizable as
  written — and it is exactly the kind of thing this simulator exists to surface.
  We investigate and resolve the gap; we do not absorb it into a tolerance.

(Implementation note: the simulator must use the **same discretization** as the
optimizer so that a faithful control produces *exactly* `P`, with no spurious
rounding gap — otherwise an `R != P` could be a numerical artifact rather than a
real finding. Getting this right is part of the work.)

### 2. The A/B economic gate (what gates a control change — also exact)

A control change (e.g. the hysteresis) is judged by the **delta of realized
savings** between two command sequences run through the **same** simulator on the
**same** scenario inputs:

```
delta = realized_savings(modified modes) − realized_savings(baseline modes)
```

Asserted **exactly, to the cent**. `delta == 0` ⇒ the change is provably
economically neutral; a non-zero delta is the exact economic impact, surfaced for
an explicit accept/reject decision. **No band** — a band would mask a real loss.

## How it unblocks the intent-dither hysteresis

Once plan-faithfulness (check 1) holds on representative scenarios:

1. Scenario inputs → `optimize_battery_schedule` → schedule + planned economics.
2. Derive (a) baseline applied modes and (b) hysteresis-stabilized modes.
3. Simulate both → realized savings A and B (same simulator, same inputs).
4. Assert `delta = B − A == 0` exactly (check 2). Non-zero ⇒ the exact economic
   impact, surfaced for explicit accept/reject. Evaluated across the dithering
   reproduction scenario and a set of others.

This is the economic verification that is currently impossible.

### Reusing existing scenarios

The existing scenario JSONs already feed the optimizer (`base_prices`,
`home_consumption`, `solar_production`, `battery`). The simulator tests reuse them:
optimizer → derive modes → simulate. Lock regressions with a **single**
`expected_savings` field per scenario — the test asserts `planned == expected_savings`
(regression lock) **and** `realized == planned` (the faithfulness relation, which
needs no stored number). Two separate planned/realized fields would be redundant
and could drift apart, masking exactly the `R != P` finding check 1 exists to
catch. A/B fixtures assert `realized(baseline) == realized(hysteresis)` exactly.
Add a *dithering* scenario (the reproduction day, generatable via
`scripts/mock_ha/scenarios/from_debug_log.py`).

## Risks

- **Plan-faithfulness may not hold today.** If the simulator shows `R != P` for the
  current control, that is a genuine (and more fundamental) finding — the coarse
  mode/TOU commands don't losslessly carry the optimizer's fine-grained planned
  power. That would reframe the dither work: the real issue would be the
  optimizer↔control contract, not a downstream label filter. We must be prepared
  for this outcome.
- **Mode→behaviour modeling** (per platform) is the substantive logic; encoded
  explicitly from the controller mappings and verified by check 1.
- **Scope creep** toward the full re-optimization feedback loop — explicitly
  deferred; v1 is execution-only.

## Decisions to confirm

1. **Platform scope v1 = Growatt MIN / modbus only** (the reproduction platform).
   Agree?
2. **v1 is execution-only** (no optimizer re-run feedback loop). Agree to defer the
   full loop?
3. **Pure simulation, no real-world/log calibration** in scope; verification is
   scenario-based and **cent-exact** (`R == P`, and A/B `delta == 0`), with any
   mismatch treated as a finding. Agree?
