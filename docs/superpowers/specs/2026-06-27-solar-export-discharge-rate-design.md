# Design: SOLAR_EXPORT intra-period discharge gate (shadow-price)

**Date**: 2026-06-27
**Status**: Approved
**Depends on**: the BATTERY_EXPORT + SOLAR_EXPORT intent split (branch
`feat/battery-export-solar-export-split`).

## Problem

`SOLAR_EXPORT` maps to `load_first` + `discharge_rate=0`. The `discharge_rate`
is written to the Growatt hardware as a register
(`_write_period_to_hardware` → `set_discharging_power_rate`), so `0` blocks the
battery from discharging at all — including covering house load if solar dips
*within* a period.

This is the reporter's actual concern, and the intent split alone did **not**
fix it: with `discharge_rate=0`, `grid_first` and `load_first` are identical for
a full battery (both hold and export surplus). To let the battery cover an
intra-period solar deficit you need `discharge_rate > 0`.

But `discharge_rate=100` *always* is also wrong: daytime battery energy is
usually reserved for the higher evening peak, so blindly covering a cheap
midday dip from the battery raids that reserve.

## The economics (what "mathematically best" means)

When an unforecast intra-period deficit `D` appears, cover it from battery
**iff** it beats buying from grid:

```
cover from battery  ⟺  P_buy_now · eff_d  ≥  V_stored
```

where `V_stored` is the **marginal opportunity value** of 1 kWh of stored SoE —
the best the optimizer could otherwise do with it. `V_stored` has three
components that a naive price comparison misses:

1. **Future buy-avoidance** — discharge later to dodge a peak buy price.
2. **Future export revenue** — sell later at `P_sell`.
3. **Replenishment** — if more solar surplus is coming, the battery refills for
   free, so spending energy now costs only the foregone *export* on the
   refill (`≈ P_sell`), not the peak. In that regime covering the dip now is a
   net gain even though `P_buy_now < evening peak`.

`cost_basis` is the **wrong** proxy: it is the FIFO *sunk cost* (an anti-loss
floor in the DP), almost always below the daytime buy price, so it would emit
`discharge_rate=100` all day and raid the reserve — the opposite of the goal.
`max(buy_prices[period:])` captures only component (1) and is systematically too
conservative (misses (2) and (3)).

The quantity that encodes all three exactly is the **DP value-function shadow
price** — the gradient of cost-to-go with respect to SoE, already computed by
the optimizer.

## Solution

Extract the shadow price from the DP and gate `discharge_rate` on it for
`SOLAR_EXPORT` periods only.

### Shadow price extraction

The backward pass `_run_dynamic_programming` (`dp_battery_algorithm.py`) builds
`V[t, i]` = optimal value-to-go from the start of period `t` entering with SoE
level `i`. `V` is in **reward units (SEK, higher = better)**: `value = reward +
V[t+1, next_i]` and `reward = -total_cost`, so `dV/dSoE > 0` — a stored kWh is
worth `dV/dSoE` in the future.

`optimize_battery_schedule` currently discards `V` (`_, policy, _, _ = ...`).
Capture it, and in the forward reconstruction loop — which already computes the
grid index `i = round((soe - min_soe)/SOE_STEP_KWH)` for each period — compute:

```
shadow_price(t) = (V[t, i] - V[t, i-1]) / SOE_STEP_KWH      # SEK per kWh SoE
```

**Backward** difference (not forward): the gate is a *discharge* decision —
pricing the marginal kWh you would *remove* from level `i`. This is also exactly
correct at a full battery (`i = len-1`), the common SOLAR_EXPORT case, where a
forward difference is undefined. At `i = 0` (empty) there is nothing to
discharge; skip the override.

Persist it on a new field `DecisionData.shadow_price: float = 0.0`. It flows
unchanged into the `ScheduleStore` with the rest of `period_data`.

### Apply-time gate

In `_apply_period_schedule` (`battery_system_manager.py`), between rate
computation and the discharge-inhibit block, for `SOLAR_EXPORT` only:

```python
buy_prices, _ = self.price_manager.get_available_prices()
stored = self.schedule_store.get_latest_schedule()
idx = period - stored.optimization_period
shadow = stored.optimization_result.period_data[idx].decision.shadow_price
eff_d = self.battery_settings.efficiency_discharge
discharge_rate = 100 if (buy_prices[period] * eff_d) >= shadow else 0
```

**Efficiency factor — the one trap:** multiply only the buy side by `eff_d`
(using 1 kWh of SoE delivers `eff_d` kWh to home, avoiding `eff_d · P_buy`).
`shadow_price` is already per-kWh-of-SoE with future efficiencies baked into
`V`; multiplying it by `eff_d` too would double-count.

The override runs before the inhibit gate, so an inhibit sensor still zeroes it,
and `_desired_discharge_rate` must reflect the post-override value.

### Why the simulator and plan-faithfulness are unaffected

A `SOLAR_EXPORT` period is net-surplus at 15-min resolution (`solar ≥ home`,
battery full), so in `mode_to_power` the `load_first` deficit is 0 and power is
0 **regardless of `discharge_rate_pct`**. Rate 0 and rate 100 are economically
identical in the model. The gate is a *sub-15-minute* hardware behavior,
invisible to the simulator. So:

- `inverter_simulator._map_rates` keeps returning `(False, 0)` for SOLAR_EXPORT.
- The unconditional plan-faithfulness check (`test_scenarios.py`,
  `test_plan_faithfulness.py`) stays green.

## Changes

1. `core/bess/models.py` — add `shadow_price: float = 0.0` to `DecisionData`.
2. `core/bess/dp_battery_algorithm.py` — capture `V` from
   `_run_dynamic_programming`; in the forward loop compute the backward-difference
   shadow price at index `i` and assign to `period_data.decision.shadow_price`.
3. `core/bess/battery_system_manager.py` — SOLAR_EXPORT gate in
   `_apply_period_schedule` before the inhibit block.
4. No change to `inverter_simulator.py` or `verification.py`.

## What the shadow price turns out to be during SOLAR_EXPORT

**Updated 2026-07-03 (issue #204):** the anti-cycling discharge gate in
`_compute_reward` used to let the DP take marginal, unprofitable discharges
during solar-surplus periods (crediting them with `avoid_purchase_value` even
when there was no grid purchase to displace). Fixing #204 closed that leak —
and it turns out the empirical `shadow ≈ sell` result below was partly an
artifact of it: the buggy discharge path let the DP dodge the wear cost of the
forced passive-solar recharge that a not-quite-full battery incurs every period
during a surplus. With the gate fixed, that recharge cost is no longer
avoidable, and the shadow price correctly rises to include it. The reasoning
that follows is updated accordingly; the mechanism (backward-difference on `V`)
is unchanged.

A SOLAR_EXPORT period is, by definition, a **full battery actively exporting
surplus**. The marginal stored kWh is replenishable from the ongoing surplus,
but that refill is not free: every period spent below full pays the passive-
charging cycle cost (`cycle_cost_per_kwh`) that a full battery avoids. So the
marginal stored kWh's opportunity value is the **export floor (sell price)
plus that forced-replenishment cycle cost**, not sell price alone. Consequences:

- **Normal prices, buy comfortably above the (now higher) shadow price**: gate
  → **100**. Covering an intra-period dip from the battery still beats buying
  from grid.
- **Buy price too close to sell** (shadow price, inflated by cycle cost, now
  exceeds `buy·eff_d`): gate → **0**, even though `buy > sell`. The
  replenishment cost eats the spread that used to make covering the dip
  worthwhile.
- **Inverted prices** (`sell ≥ buy·eff_d` — export premium, negative buy):
  gate → **0**. The energy is worth more exported than the cheap grid import it
  would displace; export it and buy the dip from grid.

The gate is no longer "100 except under export-premium conditions" — it now
also depends on `buy` clearing the cycle-cost-inclusive shadow price, not just
`buy > sell`. The shadow price (not a constant, and not a bare sell-price
proxy) is required precisely because that threshold moves with `cycle_cost_per_kwh`
and the price levels. The reserve-for-peak behaviour shows up at
LOAD_SUPPORT/discharge periods, where the gate does not apply.

## Tests

- `test_solar_export_covers_dip_when_buy_exceeds_export` (slow): normal prices →
  `shadow ≈ sell`, `shadow < buy·eff_d`, gate → 100 (replenishment).
- `test_solar_export_holds_when_export_more_valuable` (slow): inverted prices →
  `shadow > buy·eff_d`, gate → 0 (proves the gate is not a no-op).
- `test_solar_export_discharge_rate_gate_boundary`: the gate function, including
  the `>=` equality boundary.
- Existing R==P plan-faithfulness checks and `test_surplus_disposition`
  SOLAR_EXPORT assertions stay green unchanged (the gate is sub-15-min and the
  simulator is untouched).

## Edge cases

- **Full battery (`i = len-1`)**: backward difference is exact; no clamping.
- **Empty (`i = 0`)**: nothing to discharge; skip override (rate stays 0).
- **SoE between grid levels**: evaluate at the same snapped `i` the policy used.
- **End-of-horizon**: use `V[t]` at `i` with `t < horizon`; never reach the
  terminal row.
- **Efficiency**: `eff_d` on the buy side only.
