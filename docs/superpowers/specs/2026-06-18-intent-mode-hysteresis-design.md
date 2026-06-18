# Design: intent-mode hysteresis to stop sub-resolution dither churn

**Date:** 2026-06-18
**Investigation:** [`../../investigations/intent-dither-morning.md`](../../investigations/intent-dither-morning.md)
**Related PR:** #141

## Problem

When the battery sits near its SoE floor (or any level the optimal control wants
to *hold*), the DP renders fractional optimal control on the `SOE_STEP_KWH = 0.1`
grid as an alternating ±0.1 kWh (~0.4 kW) action pattern. Each sign flip crosses
the `classify_strategic_intent` threshold → flips the strategic intent →
maps to an inverter mode change (`grid_first` ⇄ `load_first`). Result: needless
Modbus writes / TOU-segment churn and a flickering UI timeline that confuses
users. It is **not** an economic bug — the trajectory is cost-optimal.

## Goal & hard invariants

- Stop the mode/intent flicker and the resulting inverter churn + UI confusion.
- **Do not change the optimizer, the reward function, the chosen SoE trajectory,
  or the reported economics.** `battery_solar_cost` must be byte-identical
  before/after on any input.
- No economic tuning knob. Parameters must be operationally/physically grounded
  (inverter behaviour), not fitted to a price outcome.

## Approach (chosen): downstream min-dwell hysteresis

A stabilization stage sits **between** the optimizer's per-period strategic-intent
stream and the consumers of that stream (the inverter TOU schedule builder and the
UI). It does not touch the per-period economics.

### The rule

Walk the full-day intent array and derive a *committed mode* stream:

- Map each period's strategic intent to its inverter mode
  (`GRID_CHARGING → battery_first`, `EXPORT_ARBITRAGE → grid_first`, else
  `load_first` — the existing mapping).
- Start committed = mode of the first period (seeded from the currently-applied
  hardware mode at horizon start).
- For each subsequent period whose candidate mode differs from committed: look
  ahead at the run length of that candidate. **Commit the change if the run is at
  least `mode_min_dwell_periods` long, OR if any action in the run is backed by a
  clearly-controllable power (`|action_kw| ≥ significant_power_kw`).** Otherwise
  hold the committed mode.

Persistence is the discriminator a magnitude filter can't provide: the real drain
persists (commits), the dither alternates every 1–2 periods (held). The
`significant_power_kw` override is a *safety guard* so a genuine brief
high-power action (e.g. a sharp price-spike discharge) is never suppressed.

### Parameters (config, grounded — not economic)

- `mode_min_dwell_periods` — minimum consecutive periods a new mode must persist
  before it commits. Default **3** (≈ 45 min at quarterly resolution). Rationale:
  debounce; tied to the cost of a TOU/Modbus reconfiguration, not to price.
  Measured insensitive (dwell 3 ≡ 4 on the reproduction day).
- `significant_power_kw` — power above which a mode change commits immediately
  regardless of dwell. Default a clearly-above-noise value (e.g. **1.0 kW**); the
  ~0.4 kW dither is well below it. Protects real brief actions.

Both are exposed in config with the defaults above; neither is fitted to savings.

## Where it lives

`core/bess/battery_system_manager.py`, where `full_day_strategic_intents` is
assembled and frozen (~lines 1947–1979) before being handed to the inverter
controller and surfaced to the UI. The hysteresis is applied to produce the
**applied/committed** intent stream used for:

1. the Modbus/TOU schedule comparison that decides whether to rewrite, and
2. the strategic-intent surfaced to the frontend timeline.

The raw per-period optimizer intent (`PeriodData.decision.strategic_intent`)
stays untouched for the economic/decision record. The hysteresis is a **pure
function** of the full-day intent + per-period action arrays — recomputed
deterministically each optimization run, holding no cross-run state, so it stays
consistent with the existing per-period intent-freezing logic.

## Component boundary

- **Input:** ordered list of `(strategic_intent, battery_action_kw)` per period +
  the currently-applied hardware mode (seed).
- **Output:** ordered list of committed strategic intents (same length).
- **Pure / no I/O / no optimizer coupling** → unit-testable in isolation.

Proposed home: a small standalone function (e.g.
`stabilize_intents(intents, actions, applied_mode, dwell, significant_power)` in a
new `core/bess/intent_hysteresis.py`) so it can be tested without the DP.

## Edge cases (must be covered by tests)

1. **Non-zero-centered flicker** (wobble between two charge levels, or near full
   SoE): the rule keys on *committed mode persistence*, not zero-crossing → handled.
2. **Genuine brief high-power action** (1-period real discharge into a spike):
   protected by the `significant_power_kw` override → commits immediately, not
   suppressed.
3. **Floor / ceiling** with passive solar forcing movement: committed mode simply
   persists; hysteresis does not fight physics.
4. **Cross-run consistency:** recomputed each run from the full intent array; no
   stateful carry-over that could disagree with the frozen past-period intents.
5. **Horizon start / no history:** committed seed = currently-applied hardware
   mode (or first period's mode if unknown).
6. **Resolution:** dwell is in *periods*; behaviour is documented for both
   quarterly (0.25 h) and hourly (1.0 h) resolutions.

## Validation plan

- **Economic invariance:** assert `result.economic_summary.battery_solar_cost` is
  byte-identical with hysteresis applied vs not (the optimizer output is unchanged
  by construction; this is a guard test).
- **Regression on the reproduction day:** reconstruct the 2026-06-16 inputs;
  assert (a) full-day mode-changes drop (10 → ≤4 at dwell 3) and the morning
  P26–49 shows a single stable `grid_first` band then `load_first`, and (b)
  cost unchanged.
- **Unit tests** for `stabilize_intents` covering each edge case above.
- **Full suite:** `pytest -m "not slow"` then `pytest -m slow` (algorithm +
  integration) green; `black . && ruff check .` clean.

## Explicitly out of scope

- No change to `_compute_reward`, `_discretize_state_action_space`, the
  anti-cycling discharge gate, or `SOE_STEP_KWH`/`POWER_STEP_KW`.
- No change to reported savings.
- Frontend visual segment-merging is **not** required (the stabilized intent
  stream already removes the flicker the UI renders); not pursued here.
