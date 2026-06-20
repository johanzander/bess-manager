# LOAD_SUPPORT Discharge Pacing — Design Spec

## Goal

Make the inverter execute LOAD_SUPPORT periods at the power level the DP optimizer planned, instead of always dumping at 100% rate.

## Background

Issue #147. The DP optimizer correctly models partial discharge for LOAD_SUPPORT (e.g., discharge 0.4 kW, let grid cover the remaining 4.6 kW deficit, reserve battery for the expensive peak later). But `_map_intent_to_rates` always returns `discharge_rate=100` for LOAD_SUPPORT, so the inverter dumps at full rate and drains the battery early. The plan-faithfulness simulator exposes this as R−P deviations of 1–5 SEK on high-consumption days.

EXPORT_ARBITRAGE already scales `discharge_rate` from the planned battery action. LOAD_SUPPORT needs the same treatment.

## Architecture

The Growatt MIN executes LOAD_SUPPORT as `load_first` with a per-period `discharge_rate_pct` written at runtime via `_apply_period_schedule → compute_rates_for_period → _map_intent_to_rates`. The TOU batch schedule never creates explicit slots for `load_first` (it is the inverter default). So the fix is entirely in the real-time control translation layer — no DP changes, no TOU builder changes, no new intents.

Hardware validation: `discharge_rate_pct` in `load_first` mode is a power cap — 100% = full `max_discharge_power_kw`, 10% = 10% of that. Confirmed on GEN4 Modbus.

## Changes

### `core/bess/inverter_controller.py` — `_map_intent_to_rates`

Replace the hardcoded `return False, 100` for LOAD_SUPPORT with the same scaling logic used for EXPORT_ARBITRAGE:

```python
elif intent == "LOAD_SUPPORT":
    if battery_action_kw < -0.01:
        discharge_rate = min(
            100,
            max(0, int(abs(battery_action_kw) / self.max_discharge_power_kw * 100)),
        )
    else:
        discharge_rate = 0
    return False, discharge_rate
```

### `core/bess/simulation/inverter_simulator.py` — `_map_rates`

Identical change for LOAD_SUPPORT (this function mirrors the production controller):

```python
if intent == "LOAD_SUPPORT":
    if action_kw < -0.01:
        rate = min(100, max(0, int(abs(action_kw) / settings.max_discharge_power_kw * 100)))
    else:
        rate = 0
    return False, rate
```

### `core/bess/tests/unit/test_scenarios.py`

Remove `xfail` from the four scenarios currently failing due to this bug:
- `synthetic_consumption_high_no_solar` (R−P was +4.88 SEK)
- `synthetic_seasonal_winter` (R−P was +2.03 SEK)
- `synthetic_consumption_ev_charging` (R−P was +2.03 SEK)
- `historical_2025_01_12_evening_peak_no_solar` (R−P was +0.96 SEK)

### `core/bess/tests/unit/test_optimization_algorithm.py` (or new file)

Add unit tests for the updated `_map_intent_to_rates`:
- LOAD_SUPPORT with `battery_action_kw = -1.5` and `max_discharge_power_kw = 6.0` → `discharge_rate = 25`
- LOAD_SUPPORT with `battery_action_kw = -6.0` → `discharge_rate = 100`
- LOAD_SUPPORT with `battery_action_kw = 0.0` → `discharge_rate = 0`

## Why R==P Holds

The simulator's `_map_rates` and the production controller's `_map_intent_to_rates` are mirrors. After this fix both compute the same `discharge_rate` from the same planned action. The simulator's `mode_to_power` for `load_first` already applies `rate_kw` as a cap: `min(deficit, rate_kw * dt, available)`. With the planned rate < deficit (which holds by construction for LOAD_SUPPORT — any period where discharge exceeds deficit would be classified as EXPORT_ARBITRAGE), the battery delivers exactly the planned amount.

## Robustness

Rate-limiting LOAD_SUPPORT does not under-cover home consumption: the grid always covers whatever the battery doesn't. If actual consumption exceeds the forecast, the grid picks up the extra — the battery is preserved for the expensive peak the optimizer planned for. This is strictly better than dumping now and buying expensive grid power later.

## Out of Scope

- `INTENT_TO_CONTROL` static dict (used only for SPH display, not for MIN hardware writes)
- `group_periods_by_intent` base-class method (display only)
- Any scenarios where R−P deviation is driven by forecast error rather than control faithfulness
