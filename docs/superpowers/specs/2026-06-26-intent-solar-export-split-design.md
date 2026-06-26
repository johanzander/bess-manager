# Design: Split EXPORT_ARBITRAGE into BATTERY_EXPORT + SOLAR_EXPORT

**Date**: 2026-06-26  
**Status**: Approved

## Problem

`EXPORT_ARBITRAGE` is used for two distinct situations that need different inverter modes:

1. **Battery actively discharging to grid** — correct, needs `grid_first`
2. **Solar surplus going directly to grid, battery completely idle** — wrong, locks inverter in `grid_first` with `discharge_rate=0`, blocking battery from supporting house load

The root cause is the fallthrough in `classify_strategic_intent` (`decision_intelligence.py:443-444`):

```python
elif energy_data.grid_exported > 0.01 and energy_data.solar_to_grid > 0.01:
    return "EXPORT_ARBITRAGE"
```

This fires whenever solar is exporting and the battery has no action — regardless of whether the battery is involved at all. The result is `grid_first` mode for hours at a time during solar-heavy daytime periods, while the battery sits idle and unable to cover house load shortfalls.

## Solution

Split `EXPORT_ARBITRAGE` into two intents with different semantics and the same asymmetric mode assignment:

| Intent | Meaning | Battery action | Inverter mode |
|---|---|---|---|
| `BATTERY_EXPORT` | Battery discharging to grid for profit | `power < -0.1` AND `battery_to_grid > 0.1` | `grid_first` |
| `SOLAR_EXPORT` | Solar surplus going directly to grid, battery idle | `power ≈ 0`, solar exporting | `load_first` |

`SOLAR_STORAGE` (battery charging from solar, storing for later export) is unchanged — it is already the correct "export-window waiting" state, already mapped to `load_first`.

`BATTERY_EXPORT` is a pure rename of `EXPORT_ARBITRAGE` — no semantic change, just a clearer name that parallels `SOLAR_EXPORT`.

## Intent Table (complete, post-change)

| Intent | Trigger | Mode | Grid charge | Charge rate | Discharge rate |
|---|---|---|---|---|---|
| `GRID_CHARGING` | `grid_to_battery > solar_to_battery` | `battery_first` | On | 100% | 0% |
| `SOLAR_STORAGE` | charging from solar | `load_first` | Off | 100% | 0% |
| `LOAD_SUPPORT` | `battery_to_home > 0.1 kWh` | `load_first` | Off | 0% | action-derived |
| `BATTERY_EXPORT` | `battery_to_grid > 0.1 kWh` | `grid_first` | Off | 0% | action-derived |
| `SOLAR_EXPORT` | solar exporting, battery idle | `load_first` | Off | 100% | 0% |
| `IDLE` | no significant battery activity | `load_first` | Off | 100% | 0% |

`SOLAR_EXPORT` uses the same hardware settings as `IDLE` (solar exports naturally in `load_first` when surplus exceeds consumption — no special mode needed). It exists as a distinct intent purely for display and future UI distinction between "solar exporting" and "truly nothing happening."

## Changes

### 1. `core/bess/decision_intelligence.py`

- Change fallthrough (line 443-444): `return "EXPORT_ARBITRAGE"` → `return "SOLAR_EXPORT"`
- Rename all `"EXPORT_ARBITRAGE"` string literals → `"BATTERY_EXPORT"`
- Update docstring for `classify_strategic_intent`

### 2. `core/bess/inverter_controller.py`

- In `INTENT_TO_CONTROL`: rename `EXPORT_ARBITRAGE` key → `BATTERY_EXPORT`; add `SOLAR_EXPORT` with same settings as `IDLE` (`grid_charge=False, charge_rate=100, discharge_rate=0`)
- In `INTENT_TO_MODE`: rename `EXPORT_ARBITRAGE` → `BATTERY_EXPORT`; add `SOLAR_EXPORT` → `"load_first"`
- In `INTENT_DESCRIPTIONS`: rename key, update description to "Selling stored battery energy to grid"; add `SOLAR_EXPORT` → "Solar surplus exporting directly to grid"
- In `_map_intent_to_rates`: rename branch; add `SOLAR_EXPORT` branch (same as `IDLE`: `return False, 0`)
- Update class docstring

### 3. `core/bess/dp_schedule.py`

- In `get_hour_settings`: rename `"EXPORT_ARBITRAGE"` → `"BATTERY_EXPORT"`; add `elif intent == "SOLAR_EXPORT": state = "idle"` (maps to `load_first` via the default path, discharge rate 0)

### 4. `core/bess/dp_battery_algorithm.py`

- Rename `EXPORT_ARBITRAGE` string literal in `StrategicIntent` enum → `BATTERY_EXPORT`
- Rename all string references throughout

### 5. Remaining backend files (mechanical rename only)

`models.py`, `growatt_min_controller.py`, `growatt_sph_controller.py`, `solax_modbus_growatt_controller.py`, `solax_controller.py`, `battery_system_manager.py`, `debug_data_exporter.py`, `schedule_store.py`, `daily_view_builder.py`, `ai_chat.py`, `api_dataclasses.py`, `api.py`, `scripts/bess-mcp-server.py` — rename `EXPORT_ARBITRAGE` → `BATTERY_EXPORT` everywhere.

### 6. Frontend (3 files)

- `BatteryModeTimeline.tsx`: add `SOLAR_EXPORT` to `StrategicIntent` type union; add entry to display config (label: "Solar Export", colour: a yellow-green); add to `INTENT_ORDER`; rename `EXPORT_ARBITRAGE` → `BATTERY_EXPORT`
- `SystemStatusCard.tsx`: rename `EXPORT_ARBITRAGE` key; add `SOLAR_EXPORT: 'Solar Exporting'`
- `InverterStatusDashboard.tsx`: rename key; add `SOLAR_EXPORT` with appropriate colour class

### 7. Tests (17 files, ~97 occurrences)

- Mechanical rename: `EXPORT_ARBITRAGE` → `BATTERY_EXPORT` throughout
- New tests in `test_optimization_algorithm.py` or `test_surplus_disposition.py`:
  - `test_classify_solar_export_no_battery`: power=0, solar_to_grid>0 → `SOLAR_EXPORT`
  - `test_classify_battery_export_requires_discharge`: power=-1kW, battery_to_grid>0.1 → `BATTERY_EXPORT`
  - `test_solar_export_maps_to_load_first`: `SOLAR_EXPORT` intent → `load_first` mode
  - `test_battery_export_maps_to_grid_first`: `BATTERY_EXPORT` intent → `grid_first` mode
- Update `test_period_groups.py` and `test_min_schedule_e2e.py`: any assertion that previously expected `EXPORT_ARBITRAGE` for a zero-action solar period should now expect `SOLAR_EXPORT` or `IDLE`

### 8. Docs

- `docs/SOFTWARE_DESIGN.md`: update intent table and add rationale for the split
- `docs/agents/bess-knowledge.md`: update intent descriptions table

## Non-goals

- No changes to the DP optimisation algorithm's cost model or decision logic
- No changes to inverter hardware control beyond what follows from the mode mapping
- No changes to savings calculation (savings are tied to energy flows, not intent labels)
- No UI redesign — only adding `SOLAR_EXPORT` to existing display maps

## Test surface

Run after implementation:

```bash
.venv/bin/pytest -m "not slow"   # fast unit + integration tests
.venv/bin/pytest -m slow         # algorithm + E2E (includes inverter platform tests)
```

All 17 test files touching `EXPORT_ARBITRAGE` must pass with the renamed `BATTERY_EXPORT`. The new `SOLAR_EXPORT` tests must pass. No existing algorithm behaviour changes — only intent labels and inverter mode for zero-action solar-export periods.
