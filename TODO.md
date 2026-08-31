# Energy Management System Improvements - Prioritized Implementation Plan


### **A negative base consumption forecast is floored silently when an overlay is configured**

**Impact**: Low | **Effort**: Low | **Dependencies**: `core/bess/consumption_overlay.py`, `core/bess/battery_system_manager.py`

**Description**: After the #734 fix, `apply_overlay` still floors every negative in the composed forecast to zero, but only attributes a period to `clamped_periods` when the overlay itself drove it negative. A negative the configured consumption strategy emitted (net-metering / bad-recorder artifact) is therefore floored with no log line and no runtime failure — but only when an overlay entity is configured; without one, `_apply_consumption_overlay` returns early and the negative reaches the DP unchanged. Pre-#734 it produced a (misattributed) `CONSUMPTION_OVERLAY_CLAMPED` warning. The reporter's own suggestion: validate/report a negative base forecast separately from overlay over-subtraction, so the data-quality problem surfaces regardless of overlay config. Raised in the #734 code review.


### **`sample_live_power()` gates on the wrong sensor list**

**Impact**: Low | **Effort**: Low | **Dependencies**: `sensor_collector.py`

**Description**: `sample_live_power()` early-returns on `if not self.power_sensors`, but `power_sensors` comes from `_resolve_power_sensor_ids()`, which deliberately *excludes* shared signed entities (their direction is unrecoverable from an InfluxDB period mean). The sampling loop itself never touches `power_sensors` — it calls the sign-splitting getters, which handle those entities fine. So an install whose only mapped power sensors are the shared signed ones gets no live sampling at all, silently disabling the `PowerSampleBuffer` path that `_shared_signed_power_entities()`'s docstring names as the covering fallback for exactly those installs. The guard should test the flow map / getters instead. Pre-existing; found during the #604 review, which widens the set of installs hitting the exclusion.


### **`ha_recorder_helper.get_sensor_data_batch` rescans each sample list per period**

**Impact**: Low | **Effort**: Low | **Dependencies**: `core/bess/ha_recorder_helper.py`

**Description**: `get_sensor_data_batch` loops `for period in range(96)` and, inside, re-walks each entity's full sorted sample list to find the last value at/before the period boundary — O(96·S) per sensor. A single forward-merge pass (advance one pointer through the sorted samples as `period` increases) is O(S+96). Verbatim port of `influxdb_helper._parse_batch_response`'s existing nested loop; not a regression. Matters once PR 2 of #722 wires this into cold-start backfill over up to ~10 days of state changes. Raised in the PR 1 (#722) code review.


### **Dashboard banners re-implement the same amber/red shell four times**

**Impact**: Low | **Effort**: Low-Medium | **Dependencies**: `frontend/src/components/*Banner*`, `DashboardPage.tsx`

**Description**: `AlertBanner`, `RuntimeFailureAlerts`, the inline yellow partial-data `<div>` in `DashboardPage.tsx`, and now `DeprecationBanner` (#722 PR 4) each hand-roll the same Tailwind shell — `bg-amber-50 dark:bg-amber-900/20 border …`, `flex items-start space-x-3` + icon + `h3` + `aria-label="Dismiss"` X button, same action-link classes. Styling/dark-mode/spacing changes have to be made in every copy and will drift. A shared presentational `<BannerShell variant tone>` carrying the shell + dismiss button once would collapse them. Raised in the #722 PR 4 review; `DeprecationBanner` is self-contained and removed in PR 6, so this is only worth doing if the shell is extracted for the others too.


### **`describe_failing_checks()` is dead code after the device-grouping banner**

**Impact**: Low | **Effort**: Low | **Dependencies**: `health_check.py`, `test_describe_failing_checks.py`

**Description**: PR #701 replaced the only two production call sites of `describe_failing_checks()` (in `api.py` and `battery_system_manager.py`) with the new device-grouping helpers, leaving it exercised only by its own `test_describe_failing_checks.py`. Not wrong, just dead weight — a follow-up removal (function plus its dedicated test file) should land separately from the banner PR.

### **DP-results/schedule log can be dropped by an unexpected exception after `should_apply`**

**Impact**: Low | **Effort**: Medium | **Dependencies**: `battery_system_manager.py`

**Description**: PR #701 moved `print_optimization_results`/`log_battery_schedule` to run after `_apply_period_schedule()` inside `if should_apply:`. `update_battery_schedule`'s outer `except Exception` (logs + returns False) now sits between the optimization and the log block, so an exception raised in the `should_apply=True` path before the log calls (e.g. a genuine bug in `_apply_period_schedule`/`_capture_prediction_snapshot`) would silently drop the DP-results/schedule tables for that cycle — the diagnostic you'd want when something downstream breaks. No concrete repro: the realistic failure surfaces (discharge-inhibit read, `apply_period`, hardware write) are already internally guarded. Design observation from the #701 review, not a demonstrated bug.


## 🔴 **CRITICAL PRIORITY** (System Reliability)

### 0. **Fix Battery Discharge Power Control Bug**

**Impact**: High | **Effort**: Medium | **Dependencies**: Growatt inverter control

**Description**: Discharge power seems to always be 100% leading to higher export than intended during BATTERY_EXPORT operations.

### **Charging power rate setting has no effect**

**Impact**: Medium | **Effort**: Medium | **Dependencies**: `inverter_controller.py`, `battery_system_manager.py`, `power_monitor.py`

**Description**: The `charging_power_rate` setting (default 40%) is overridden every cycle by `adjust_charging_power()`, which reads `charge_rate` from `INTENT_TO_CONTROL` — always 0 or 100. The configured value is only used as the initial `target_charging_power_pct` in `HomePowerMonitor`, but is immediately overwritten by the first `adjust_charging_power()` call. This affects all platforms.

**User-reported symptom**: Log shows "charging power 40%" but the inverter always charges at 100%.

**Options to consider**:
1. Remove the setting entirely if per-intent 0/100 is the intended design (and update UI to not show a configurable value)
2. Use the setting as an actual cap: `charge_rate = min(intent_charge_rate, configured_rate)`
3. Make `INTENT_TO_CONTROL` use the configured rate instead of hardcoded 100 for charging intents

**Files**: `core/bess/inverter_controller.py` (lines 33-47), `core/bess/battery_system_manager.py` (lines 2538-2548), `core/bess/power_monitor.py` (line 67), `core/bess/settings.py` (line 54)

## 🟡 **HIGH PRIORITY** (Core Functionality)

### **Add SolaX Modbus inverter support**

**Impact**: High | **Effort**: High | **Dependencies**: Inverter abstraction layer, `GrowattScheduleManager`

**Description**: Add support for the [homeassistant-solax-modbus](https://github.com/wills106/homeassistant-solax-modbus) integration alongside the existing Growatt integration. This would allow BESS Manager to be used with SolaX inverters, significantly expanding the supported hardware.

**Implementation**:

- Introduce an inverter abstraction layer (interface/protocol) that `GrowattScheduleManager` and a new `SolaXScheduleManager` both implement
- Implement `SolaXScheduleManager` using SolaX Modbus entities for TOU schedule deployment and battery mode control
- Add inverter type selection to settings (`config.yaml`, `BatterySettings`, setup wizard)
- Route schedule deployment through the selected inverter manager in `BatterySystemManager`
- Verify sensor mapping: SolaX entities for battery SOC, charge/discharge power, and grid import/export may differ from Growatt names
- Update health checks to validate the correct inverter entities based on selected type
- Add SolaX-specific documentation to `docs/INSTALLATION.md`

**Files**: `core/bess/growatt_schedule_manager.py` (extract interface), new `core/bess/solax_schedule_manager.py`, `core/bess/battery_system_manager.py`, `core/bess/settings.py`, `backend/settings_store.py`, `config.yaml`

---

### **Surface Inverter Max AC Power in the setup wizard**

**Impact**: Medium | **Effort**: Low | **Dependencies**: `SetupWizardPage.tsx`

**Description**: `inverter_max_ac_power_kw` (PR #305) caps combined solar + discharge AC output at the inverter's rated power, preventing over-discharge plans on hybrid inverters — but it's opt-in (default 0/disabled) and currently only surfaced in Settings → Battery, not the setup wizard. Issue #304 (ridax67) hit exactly this — a planned discharge exceeding the inverter's 10kW AC limit — and had to be told about the setting after the fact. New users are unlikely to discover it unless they hit the symptom first.

**Implementation**: Add the `inverterMaxAcPowerKw` / `inverterAcPowerMargin` fields to the battery step of `SetupWizardPage.tsx`, likely alongside other inverter-rating fields, with a short explanation of when to set it (hybrid/DC-coupled inverters where solar + discharge can exceed the inverter's AC rating).

**Files**: `frontend/src/pages/SetupWizardPage.tsx`, `frontend/src/components/settings/BatteryFormSection.tsx` (for reference on existing field wiring)

---

### **Rename `strategic_intent` to `battery_intent` throughout the codebase**

**Impact**: Low | **Effort**: Low | **Dependencies**: `strategic_intent.py`, `dp_battery_algorithm.py`, `sph_schedule.py`, `models.py`, frontend

**Description**: The term "strategic intent" has been replaced with "battery intent" in the software design document. Rename accordingly in code:

- `StrategicIntent` enum → `BatteryIntent` (`dp_battery_algorithm.py`)
- `strategic_intent` field → `battery_intent` in `DecisionData` (`models.py`)
- All assignments and references in `strategic_intent.py`, `sph_schedule.py`, `battery_system_manager.py`, and any API serialization
- Frontend: any display label or type referencing `strategicIntent` / `strategic_intent`

### **Minor cleanup from issue #201 (stale health-check banner) fix**

**Impact**: Low | **Effort**: Low | **Dependencies**: `core/bess/influxdb_helper.py`, `backend/api.py`

**Description**: A few small, non-blocking cleanups identified during code review of the #201 fix:

- `get_sensor_data_batch` and `get_power_sensor_data_batch` (`core/bess/influxdb_helper.py`) each have their own copy of the `if not is_influxdb_configured(): ...` early-return guard — could be factored into a shared decorator/helper if a third call site appears.
- `GET /api/system-health` and `POST /api/system-health/recheck` (`backend/api.py`) share the same `_require_configured_system` + health-check + `convert_keys_to_camel_case` + `HTTPException(500)` shape, differing only in whether the result is cached. Worth revisiting if a third variant is ever needed.
- The new 5-minute health-check cron job (`backend/app.py`) also re-runs `test_influxdb_connection()` for the subset of users who *do* have InfluxDB configured (it correctly skips for everyone else). This is intentional — same cadence agreed for the dashboard banner — but worth knowing if InfluxDB load ever becomes a complaint.

### **Investigate redundant `power` gate in strategic intent detection**

**Impact**: Low | **Effort**: Low | **Dependencies**: `strategic_intent.py`, `dp_battery_algorithm.py`

**Description**: In `create_decision_data` (`strategic_intent.py`), strategic intent is determined by an outer `power < -0.1` / `power > 0.1` check followed by inner energy flow checks (`battery_to_grid`, `grid_to_battery`). The `power` check is likely redundant: the detailed flows in `EnergyData` are derived automatically via `_calculate_detailed_flows()` from `battery_charged`/`battery_discharged`, so if `power < -0.1` then `battery_discharged > 0` and the flow checks already handle the distinction. The inner flow thresholds (0.1 kWh) also provide the same noise filtering as the outer power threshold. Verify whether the outer `power` gate can be removed and intent determined solely from energy flows.



### 1. **Improve Battery SOC and Actions Component**

**Impact**: Medium-High | **Effort**: High | **Dependencies**: Backend cost calculations

**Description**: Core feature enhancement showing detailed battery optimization reasoning

**Current State**: `BatteryLevelChart.tsx` exists with SOC and battery action visualization. Missing: cost breakdown table and actual/predicted timeline split.

**Implementation**:

- **Add actual/predicted timeline split** with visual distinction
- **Add detailed cost breakdown table**:

```text
  Base case cost:     65.69 SEK (Actual: 27.06 + Predicted: 38.63)
  Grid cost:         -14.90 SEK (Actual: 28.13 + Predicted: -43.03)
  Battery wear cost:   9.89 SEK (Actual: 2.60 + Predicted: 7.29)
  Total savings:      80.59 SEK (Actual: -1.07 + Predicted: 81.67)
```

**Technical Tasks**:

- Update `BatteryLevelChart.tsx` for actual/predicted split
- Create cost breakdown table component
- Add hover tooltips with detailed calculations
- Integrate with backend hourly cost data

---

### 3. **Move Relevant Parts of Daily Summary to Dashboard**

**Impact**: Medium | **Effort**: Low-Medium | **Dependencies**: Dashboard layout

**Current State**: `SavingsPage` contains energy independence metrics that belong on Dashboard

**Implementation**:

- **Extract Energy Independence Card**: Self-sufficiency %, Grid independence time, Solar utilization %
- **Remove duplicates**: Eliminate redundant cost/savings between Dashboard and Savings pages

**Technical Tasks**:

- Create `EnergyIndependenceCard.tsx` component
- Extract logic from `SavingsPage.tsx`
- Add to `DashboardPage.tsx`
- Remove duplicate information

---

### 6. **Demo Mode for Users Without Configured Sensors**

**Impact**: Medium | **Effort**: Medium | **Dependencies**: Backend architecture, Mock data

**Description**: Allow users to run and explore the system without requiring fully configured Home Assistant sensors. This enables evaluation, development, and troubleshooting scenarios.

**Implementation**:

- **Enhanced mock data generation**: Create realistic synthetic energy data, battery states, and pricing
- **Demo mode toggle**: Configuration option to enable full demo mode vs partial sensor availability
- **Graceful degradation**: System operates with missing sensors using reasonable defaults
- **Demo data scenarios**: Multiple realistic scenarios (high solar, EV charging, peak pricing days)
- **Visual indicators**: Clear UI indication when running in demo/mock mode

**Benefits**: Users can evaluate the system before full HA integration, developers can test without hardware, easier onboarding experience

**Current State**: `ha_api_controller.py` has a basic `test_mode` / `set_test_mode()` infrastructure but no synthetic data generation or UI indicators.

**Technical Tasks**:

- Extend existing test mode functionality in `ha_api_controller.py`
- Create comprehensive mock data generators for all sensor types
- Add demo mode configuration to `config.yaml`
- Update frontend to show demo mode indicators
- Ensure optimization algorithms work with mock data

## 🟢 **LOW PRIORITY** (Polish)

### 7. Add Prediction accuracy and history

### 8. Intent is not always correct for historical data

**Current State**: The inverter sometimes charges/discharges small amounts like 0.1kW. Or its a rounding error or inefficiencies losses when calculating flows. I don't think its a strategic intent, but it is interpreted as one.

### **Make ha_statistics consumption forecast work on all platforms**

**Impact**: Medium | **Effort**: Medium | **Dependencies**: `battery_system_manager.py`, `ha_api_controller.py`

**Description**: The `ha_statistics` consumption forecast strategy currently requires a native `lifetime_load_consumption` HA entity to query HA Recorder statistics. Platforms without this entity (GEN4 Growatt Modbus, SolaX Native) fall back to the `fixed` profile, losing the time-of-day shaped consumption forecast.

**Fix**: Instead of querying a single load consumption entity, query the 3 universal sensors (`lifetime_solar_energy`, `lifetime_import_from_grid`, `lifetime_export_to_grid`) and derive load per hour: `load = solar_change + import_change - export_change`. Same physics, works on every platform.

**Files**: `core/bess/battery_system_manager.py` (`_get_ha_statistics_forecast`)

### **Change default consumption_strategy from `sensor` to `ha_statistics`**

**Impact**: Medium | **Effort**: Low | **Dependencies**: `settings.py`, `settings_store.py`

**Description**: The default `consumption_strategy` is still `sensor` (the legacy grid-import proxy that ignores solar self-consumption and requires a hand-written template sensor). `ha_statistics` is more accurate and needs no manual sensor setup, so it should be the default. Depends on `ha_statistics` working on all platforms (see above) so the default doesn't silently fall back to `fixed`.

**Fix**: Change `DEFAULT` / `consumption_strategy` default to `ha_statistics` in `core/bess/settings.py:183` and the settings-store defaults; update `docs/USER_GUIDE.md` (currently labels `sensor` as "(default)").

**Files**: `core/bess/settings.py`, `backend/settings_store.py`, `docs/USER_GUIDE.md`

## 🔵 **ROBUSTNESS IMPROVEMENTS** (System Observability)

### **Measure TOU write volume properly before optimizing it further**

**Impact**: Medium | **Effort**: Medium | **Dependencies**: `growatt_min_controller.py`, `core/bess/tests/conftest.py`, debug bundles

**Description**: There is no repeatable way to measure how many inverter writes a real day costs, and three separate attempts during #589 each produced a different answer for harness reasons rather than code reasons:

- driving `update_battery_schedule` over 96 cycles through `MockHomeAssistantController` measures nothing, because `read_inverter_time_segments()` (`conftest.py`) always returns `empty_slot_table()`. Every segment looks absent from hardware on every cycle, so the plan is rewritten wholesale and no gate can affect the count. It also makes the disable path dead, since every slot reads back disabled.
- the same harness with a modelled slot table but a **frozen SOC** invents churn: the DP believes the battery never charges and walks a window's end forward one quarter-hour per cycle, indefinitely.
- replaying a scenario fixture over 96 cycles **suppresses** churn: the fixture is one snapshot, so every cycle re-solves identical inputs and the plan barely moves.

The only faithful instrument found was replaying a debug bundle's recorded per-run forecasts (`## Prediction Snapshots` → per-run `strategic_intent`) straight through the controller — no DP re-solve, so the harness can neither invent nor suppress plan movement. On `bess-debug-2026-08-12-202906.md` (83 real runs) that gives 149 writes before #554, 32 after, and 32 with #589 — i.e. #554 captured essentially all of it on that day.

**Why it matters**: #589 was written on the premise that ~+8 writes/day of deferrable end-churn remained after #554. One real day does not support that. The remaining writes there were all changes taking effect at or before the current period — plan reshaping, which is #485's territory, not a write-gate's.

**Fix**:

1. Promote `_SimulatingController`'s slot modelling (in `test_growatt_tou_scheduling.py`) into `conftest.py` so the shared mock stops being blind to redundant writes and to the disable path. Removes the duplicate at the same time.
2. Turn the bundle replay into a checked-in script, and teach it the compact `predicted_periods_delta` encoding introduced by #555/#567 — only the three pre-#555 bundles can be replayed today.
3. Re-measure across several real days. Only then decide whether any further write-gating work (or #485) is worth doing, and let that data set the target rather than a single day.

---

### **Retry discovery on startup when HA WebSocket is not ready**

**Impact**: High | **Effort**: Low | **Dependencies**: `ha_api_controller.py`, `battery_system_manager.py`

**Description**: BESS Manager starts as an HA add-on and can launch before HA's WebSocket API is fully ready. When the initial `discover_integrations()` WS connection fails during early boot, `nordpool_config_entry_id` stays None and the system enters degraded mode with no price data — even though HA becomes ready seconds later. Observed on Niklas's system (b18, 2026-05-26): WS failed at 05:08 (4 min after boot), but by 05:45 discovery worked fine.

**Fix**: Re-attempt discovery with short backoff (e.g. 5s, 10s, 20s) until `config_entry_id` is populated or a max number of retries is reached.

---

### **Improve InfluxDB Health Check to Verify Sensor Coverage**

**Impact**: Medium | **Effort**: Low-Medium | **Dependencies**: `health_check.py`, `influxdb_helper.py`

**Problem**: The "Historical Data Access" health check reports OK as long as InfluxDB is reachable and the bucket contains *any* row. It uses a `limit(n: 1)` probe — equivalent to pinging the database. It does not verify that the specific sensors the BESS system needs are actually present. As a result, it reported OK on 2026-04-03 even though 4 of 10 required sensors had no data in InfluxDB.

**Note**: A sensor showing value 0 (e.g. `battery_input_energy` at day start) is valid — cumulative sensors legitimately start at 0. The check must verify **existence** (any data point in past 7 days), not recent non-zero values.

**Current behavior** (`influxdb_helper.py:test_influxdb_connection()`):

```flux
from(bucket: "...")
  |> range(start: -24h)
  |> limit(n: 1)
```

Passes if *any* measurement returns a row. No knowledge of which sensors were found.

**Desired behavior**:

For each sensor configured in the BESS system (from `METHOD_SENSOR_MAP`), run a targeted query:

```flux
from(bucket: "...")
  |> range(start: -7d)
  |> filter(fn: (r) => r["entity_id"] == "sensor.battery_input_energy")
  |> limit(n: 1)
```

Report:

- **OK**: all core sensors found in InfluxDB
- **WARNING**: optional sensors missing (configured but no InfluxDB data)
- **ERROR**: core energy sensors missing (battery, grid, consumption)

**Technical Tasks**:

- Extend `test_influxdb_connection()` to accept a list of entity IDs to probe
- Pass the configured sensor entity IDs from `METHOD_SENSOR_MAP` (or a defined "core" subset)
- Return per-sensor results so `check_historical_data_access()` can report which sensors are missing
- Distinguish core sensors (battery_input_energy, battery_output_energy, grid_import, grid_export, load_energy) from optional (ev_energy_meter, solar forecasts)
- Surface missing optional sensors as WARNING, missing core sensors as ERROR
- This will make "Historical Data Access" reflect actual data availability, not just connectivity

---

## 🔵 **KNOWN ISSUES** (From Code Review — 2026-06-24)

### Event Loop Blocking in demo→live Transition

**Impact**: Low (only at mode switch) | **Effort**: Medium

**Description**: `BatterySystemManager.set_demo_mode()` (formerly `reinitialize_tou_schedule()`) is called directly inside the `async def patch_settings` handler. On the demo→live transition it runs `_initialize_tou_schedule_from_inverter()` + `initialize_hardware()`, blocking the event loop while performing up to 36 synchronous HTTP calls to Home Assistant (reading all 9 TOU slots × 4 entities each). Should be offloaded to a background thread or thread pool executor.

**File**: `backend/api.py` — `patch_settings` / `setup_complete`, `core/bess/battery_system_manager.py` — `set_demo_mode`, `core/bess/ha_api_controller.py` — `read_tou_segments_from_entities`

---

### Startup Race: Concurrent `_initialize_tou_schedule_from_inverter` Calls

**Impact**: Low | **Effort**: Low

**Description**: `BatterySystemManager.start()` calls `_initialize_tou_schedule_from_inverter()` at startup (`battery_system_manager.py:533`), and the same path is triggered again by `set_demo_mode(False)` (`battery_system_manager.py:574`, formerly `reinitialize_tou_schedule()`) when switching demo→live. There is no threading lock protecting against concurrent calls. If both happen in rapid succession (fast live switch during startup), both threads may issue overlapping hardware writes.

**File**: `core/bess/battery_system_manager.py`

---

## 🔄 **ARCHITECTURAL IMPROVEMENTS** (From Historical Design Analysis)

### 10. **Machine Learning Predictions**

**Impact**: Medium | **Effort**: High | **Dependencies**: Historical data, ML framework

**Description**: ML-based consumption and solar predictions to improve optimization accuracy beyond current HA sensor forecasts.

**Implementation**:

- Integrate with existing PredictionProvider framework
- Historical data analysis for pattern recognition (weather, season, usage patterns)
- Adaptive prediction models with confidence scoring
- Accuracy tracking and model performance metrics

### 11. **Performance Monitoring and Metrics**

**Impact**: Medium | **Effort**: Medium | **Dependencies**: Analytics framework

**Description**: Comprehensive performance tracking for optimization effectiveness and system reliability.

**Implementation**:

- Optimization accuracy tracking (predicted vs actual savings)
- Battery performance degradation monitoring
- Energy balance validation metrics and alerts
- Component timing and performance metrics collection
- Automated reporting and alerting for anomalies

### 12. **Data Export and Analysis Tools**

**Impact**: Low | **Effort**: Medium | **Dependencies**: Data stores

**Description**: Export capabilities for external analysis and system backup.

**Implementation**:

- JSON/CSV export of historical energy data and optimization decisions
- Configuration backup/restore functionality
- Optimization decision logs with reasoning export
- Integration with external analytics tools (Grafana, etc.)

## 🟠 **POTENTIAL IMPROVEMENTS**

### Full Arbitrage Cycle Savings Display

**Impact**: Medium | **Effort**: Medium | **Dependencies**: models.py, savings page UI

**Description**: The savings table shows per-hour P&L (`solar_only_cost - hourly_cost`). This is correct and honest, but charging hours show negative savings and discharge savings appear in later hours (or the next day for overnight cycles). The daily total can appear negative when charging happened today but discharge is scheduled for tomorrow.

**Idea**: Add a "full cycle savings" summary somewhere in the savings page or dashboard that aggregates completed charge→discharge cycles and shows the net arbitrage profit per cycle. This would complement the existing per-hour P&L without changing the underlying formula.

### Optimizer vs Dashboard Savings Baseline Mismatch

**Impact**: Medium | **Effort**: Medium | **Dependencies**: DP algorithm, models.py, daily_view_builder

**Description**: The optimizer and dashboard use different baselines for calculating savings, which causes confusing discrepancies between predicted and actual savings numbers.

**The Two Calculations**:

| | Optimizer (`dp_battery_algorithm.py:897-906`) | Dashboard (`models.py:231-242`) |
|---|---|---|
| **Baseline** | Grid-only: `consumption × buy_price` | Solar-only: `(consumption - solar) × buy_price - excess_solar × sell_price` |
| **Solar in baseline?** | No — set to zero (`solar_only_cost=total_base_cost, # Simplified`) | Yes — uses real solar production data |
| **Formula** | `total_base_cost - total_optimized_cost` | `solar_only_cost - hourly_cost` |
| **Used for** | Profitability gate decision (line 933) | Dashboard `total_savings` display |

**Why This Matters**:

The dashboard metric is correct — it answers "did the battery save money vs just having solar?" The optimizer's metric conflates solar savings with battery savings. When the optimizer reports +46 SEK, that includes value from solar production that you'd earn regardless of battery operation.

**Concrete Risk**: The profitability gate (`grid_to_battery_solar_savings < min_action_profit_threshold`) compares against the grid-only baseline. On sunny days with high solar production, this could approve battery schedules that appear profitable (because solar savings are included) but are actually unprofitable when measured by the dashboard's correct solar-only baseline.

In winter (low solar), the impact is negligible since both baselines converge. In summer (high solar), the optimizer could systematically overestimate battery profitability.

**Potential Fix**: Change the optimizer's `total_base_cost` to use the solar-only baseline:

```python
# Current (grid-only baseline):
total_base_cost = sum(home_consumption[i] * buy_price[i] for i in range(len(buy_price)))

# Proposed (solar-only baseline - matches dashboard):
total_base_cost = sum(
    max(0, home_consumption[i] - solar_production[i]) * buy_price[i]
    - max(0, solar_production[i] - home_consumption[i]) * sell_price[i]
    for i in range(len(buy_price))
)
```

This would make the profitability gate compare apples-to-apples with the dashboard savings, and prevent approving battery operations that lose money relative to the solar-only baseline.

---

## 🧪 **TEST FRAMEWORK IMPROVEMENTS**

### Unify and strengthen test infrastructure

**Impact**: Medium | **Effort**: Medium | **Dependencies**: `core/bess/tests/unit/`, `backend/tests/`

**Description**: The test suite has grown organically and would benefit from a coherent structure. Currently:

- **Scenario tests** (`test_scenarios.py`) use JSON data files and only assert on economic summary values (`base_cost`, `battery_solar_cost`, `savings`, `savings_pct`). They cannot express behavioral assertions like "the optimizer should choose SOLAR_STORAGE over IDLE."
- **Standalone tests** (`test_idle_solar_charging.py`, `test_terminal_value.py`) test behavioral properties but live outside the scenario framework, duplicating setup boilerplate.
- **Backend tests** (`backend/tests/`) cover API conversion, settings contracts, and settings store but are disconnected from core algorithm tests.

**What to improve**:

- Extend the scenario framework to support **behavioral assertions** (strategic intent distribution, constraint validation) alongside economic assertions — so new regression tests like issue #73 can be expressed as scenario JSON files with richer `expected_results`
- Add a shared fixture or helper for constructing `BatterySettings` + running `optimize_battery_schedule`, reducing boilerplate across standalone tests
- Consider supporting both hourly and quarterly resolution scenarios (currently all scenarios are hourly, but real optimization runs at 15-min resolution)
- Review whether backend integration tests should exercise the full optimization→API pipeline end-to-end

**Files**: `core/bess/tests/unit/test_scenarios.py`, `core/bess/tests/unit/data/*.json`, `core/bess/tests/conftest.py`, `backend/tests/`

---

### Does #450's hybrid PWL path still earn its keep at realistic terminal values?

**Impact**: Medium | **Effort**: Medium | **Dependencies**: `core/bess/tie_detection.py`, `core/bess/pwl_window_dp.py`, `core/bess/tests/synthetic/measure_tie_coverage.py`

**Description**: Surfaced by the fixture terminal-value retrofit. A nonzero terminal row adds a value gradient at the horizon that breaks the near-ties the hybrid detect/resolve/splice path exists to fix. Measured across the retrofitted corpus: only **four** of 38 fixtures still flag a tie window at all, and the largest hybrid advantage among them is **0.0043 SEK** (`realworld_2026_04_27_184643`) — against the +0.0600 SEK that `test_hybrid_resolution_improves_on_grid_dp` was written on, at `terminal_value_per_kwh = 0.0`.

Three test files now pin `terminal_value_per_kwh = 0.0` explicitly to keep exercising the mechanism (`test_issue_450_hybrid_resolution.py`, `test_measure_tie_coverage.py`, and the fixture choice in `test_tie_diagnostics_hook.py`). That is honest — the rig's subject is near-ties, so it must run where near-ties exist — but it means the hybrid path's *production* value is now measured by nothing.

**What to improve**: Decide whether the hybrid path is still worth its latency and complexity under production-realistic terminal values, or whether #512's finer grid plus a nonzero terminal row has already absorbed what it was built for. Note the question changes again once #602 lands, since that further raises terminal values.

**Files**: `core/bess/tests/unit/test_issue_450_hybrid_resolution.py`, `core/bess/tests/synthetic/test_measure_tie_coverage.py`, `core/bess/pwl_window_dp.py`

---

### Fixture re-pin scripts each reimplement the same glob/read/check/write loop

**Impact**: Low | **Effort**: Low | **Dependencies**: `scripts/`

**Description**: There are now four entry points that walk `core/bess/tests/unit/data/*.json`, re-derive a field and write it back — `capture_selector_goldens.py`, `capture_vpp_baseline.py`, `capture_scenario_terminal_values.py` and `capture_scenario_expected_results.py` — and the last two duplicate the loop skeleton (`--check` handling, `json.dumps(indent=2)` plus trailing newline, stale counting) verbatim. The repo already factors the *capture* half into `vpp_capture.py` and `golden_capture.py`; the driver half was not.

**What to improve**: Extract the shared walk/report/write into one helper the four scripts call. Raised in review of the terminal-value retrofit, with the observation that a PR whose thesis is "two copies of a formula is two objectives" should not leave four copies of its driver.

**Files**: `scripts/capture_scenario_terminal_values.py`, `scripts/capture_scenario_expected_results.py`, `scripts/capture_selector_goldens.py`, `scripts/capture_vpp_baseline.py`

---

## 🔧 **TECHNICAL DEBT**

### Decide the fate of `EnergySankeyChart.tsx`

**Impact**: Low | **Effort**: Low (decision only)

**Description**: `frontend/src/components/EnergySankeyChart.tsx` is imported by
nothing — an orphaned visualization like `DecisionFramework.tsx` and
`TableBatteryDecisionExplorer.tsx` were before their removal. Unlike those, it
is **energy-flow visualization, not decision explanation**, so it is a
separate question and is deliberately left in place for now: a Sankey of
solar → home / battery / grid may still earn a place on the Dashboard or
Insights page in a way the decision-narration components never could.

**Decide**: route it (Dashboard or Insights) or delete it. Do not let it drift
as a fourth orphan.

**Files**: `frontend/src/components/EnergySankeyChart.tsx`

---

### Consolidate HistoricalDataStore, PredictionSnapshotStore, and DailyViewStore

**Impact**: Low | **Effort**: Medium | **Dependencies**: `core/bess/historical_data_store.py`, `core/bess/prediction_snapshot.py`, `core/bess/daily_view_store.py`

**Description**: The Daily Savings History feature (issue #126, `docs/superpowers/specs/2026-07-09-daily-savings-history-design.md`) added a third `DailyView`/`PeriodData`-shaped store alongside the existing `HistoricalDataStore` (today-only, cleared nightly) and `PredictionSnapshotStore` (today-only, cleared nightly). All three persist overlapping period-level data with slightly different lifecycles. The new store deliberately kept its schema close to `DailyView`/`PeriodData` rather than inventing a divergent shape, specifically so this consolidation stays feasible later. No action taken now — noted for a future pass once the aggregate-savings feature has shipped and settled.

**Files**: `core/bess/historical_data_store.py`, `core/bess/prediction_snapshot.py`, `core/bess/daily_view_store.py`, `core/bess/battery_system_manager.py`

---

### SolaxController VPP behavior has fallen behind SolaxModbusGrowattController's VPP fixes

**Impact**: Medium | **Effort**: Medium | **Dependencies**: `core/bess/solax_controller.py`, `core/bess/solax_modbus_growatt_controller.py`

**Description**: `SolaxController` (native SolaX inverters) and `SolaxModbusGrowattController` in `control_mode="vpp"` (Growatt via solax_modbus) both drive hardware through the same conceptual VPP power + remote-control model, but two Growatt-specific hardware fixes were never ported to SolaX: (1) #355's SOLAR_EXPORT grid-first hold (`block_passive_charging` -- Growatt actively holds the battery so solar bypasses to grid; SolaX still calls `set_solax_vpp_disabled()`, which lets solar passively recharge the battery during SOLAR_EXPORT), and (2) #413's LOAD_SUPPORT remote-control release (Growatt releases control to the inverter's own load-following self-use; SolaX still forces a fixed discharge-rate watt target). `SolaxController`'s own docstring (`solax_controller.py:120-126`) already flags the SOLAR_EXPORT gap as known and unverified on real hardware. These two controllers should probably converge on identical VPP semantics, but doing so changes real SolaX hardware behavior and needs its own hardware validation -- out of scope for the issue #415 display-only fix (`docs/superpowers/specs/2026-07-29-control-model-display-design.md`), which instead surfaces this divergence transparently (each controller's displayed VPP power/remote-control state reflects its own actual, currently-different, behavior).

**Files**: `core/bess/solax_controller.py`, `core/bess/solax_modbus_growatt_controller.py`

---

### Reconsider whether the all-IDLE numerical safety net is still needed

**Impact**: Low | **Effort**: Low-Medium | **Dependencies**: `dp_battery_algorithm.py`, `docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md`

**Description**: After the "Bellman-optimality guardrail removal" refactor, `optimize_battery_schedule` still unconditionally computes a plain all-IDLE schedule and swaps it in if cheaper (`core/bess/dp_battery_algorithm.py:1514-1536`). Backward induction is optimal by construction — `IDLE` is always an available action at every period, so the DP's own schedule should never come out worse. The design doc's own investigation found this only guards a small residual (~0.16 SEK on one fixture, down from 0.27 SEK after an earlier partial fix) from SOE-grid discretization, "not provably zero without it." Worth revisiting whether finer discretization, the continuous-action reformulation mentioned as out-of-scope in that design doc, or another approach could close the residual gap fully, making this comparison genuinely removable rather than kept indefinitely as insurance.

**Files**: `core/bess/dp_battery_algorithm.py` (lines 1514-1536), `docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md`

---

### Move `charging_power_rate` out of `BatterySettings`

**Impact**: Low | **Effort**: Medium | **Dependencies**: `power_monitor.py`, `settings_store.py`, migration

**Description**: `charging_power_rate` is stored in `BatterySettings` but it is not a battery hardware characteristic — it is a live Growatt number entity (`battery_charge_power_limit`) that is read and written via HA at runtime. It ended up in `BatterySettings` only because `power_monitor.py` needs an initial value before HA is read. That is weak justification for treating it as a user-facing battery setting.

**What needs to change**:

- Remove `charging_power_rate` from `BatterySettings` dataclass (`core/bess/settings.py`)
- Update `power_monitor.py` to use a local constant or read the initial value from HA directly
- Update schema migration in `settings_store.py` (remove from battery section, or move to growatt section)
- Verify `_BATTERY_MODEL_ATTRS` in `api.py` updates automatically (it is derived from the dataclass, so it will)
- Update any tests that reference `battery_settings.charging_power_rate`

**Files**: `core/bess/settings.py`, `core/bess/power_monitor.py`, `backend/settings_store.py`

---



### FormattingContext Architecture

**Impact**: Low | **Effort**: Medium-High (originally estimated 45 min — see below) | **Dependencies**: None

**Status**: Parked deliberately. **Do not start until the trigger below fires.**

**Description**: Replace currency parameter passing with FormattingContext dataclass for better extensibility and i18n support.

**Current State**: Currency passed as string parameter through call chain

**Implementation**: Create frozen FormattingContext dataclass, update `create_formatted_value()` and dataclass `from_internal()` methods, modify API endpoints to create context from settings

**Benefits**: Type safety, extensibility for locale/timezone/precision without signature changes, future-proof for internationalization

**Trigger — do it when a second field actually exists**: i.e. when locale,
timezone, or configurable precision is genuinely requested. Until then the
context would carry exactly one field (currency), so its shape has to be
guessed, and guessing wrong means doing the migration twice.

**Why not now** (measured 2026-08-05): the "45 min" estimate is wrong — there
are ~163 `create_formatted_value()` call sites across `backend/` and `core/`,
5 `from_internal()` implementations, and ~120 currency references in
`api_dataclasses.py` alone. Every one of them feeds a number the dashboard
renders, so the best possible outcome is that nothing changes visibly: pure
regression risk for no user-facing payoff, and nothing that would earn a
CHANGELOG line. When the trigger fires, the refactor pays for itself
immediately and the context's shape is dictated by a real requirement.

**Files**: `backend/api_dataclasses.py`, `backend/api.py`

### Upstream PR: growatt_server should register services per device type

**Impact**: Medium | **Effort**: Low | **Dependencies**: HA core `homeassistant/components/growatt_server/services.py`

**Description**: The HA `growatt_server` integration unconditionally registers all 6 services (`update_time_segment`, `read_time_segments`, `write_ac_charge_times`, `read_ac_charge_times`, `write_ac_discharge_times`, `read_ac_discharge_times`) regardless of inverter type. At runtime the handlers check `device_type` and fail with "no devices configured" if the wrong type is called. This prevents external tools (like BESS) from using the service list to distinguish MIN from SPH.

**Proposed upstream fix**: Only register `update_time_segment`/`read_time_segments` when a MIN coordinator exists, and `write_ac_charge_times`/`read_ac_charge_times`/`write_ac_discharge_times`/`read_ac_discharge_times` when an SPH coordinator exists. This is a small change in `async_setup_services()`.

**After upstream fix lands**: Update our detection in `discover_ha_metadata()` to use services again (more robust than the current entity-registry `ac_charge` switch heuristic, which breaks if the user deletes the entity or if the HA integration changes entity creation).

**Current workaround**: We detect MIN vs SPH by checking if a `growatt_server` entity with unique_id ending in `-ac_charge` exists in the entity registry (MIN creates `switch.*_ac_charge`, SPH does not).

---

### Remove non-required derived sensors from discovery and config

**Impact**: Low | **Effort**: Low | **Dependencies**: `ha_api_controller.py`, `sensorDefinitions.ts`

**Description**: Several sensors are discovered and stored in `bess_settings.json` but are never consumed — they are always derived from the 5 core energy sensors by `EnergyFlowCalculator`:

- `lifetime_system_production` (mapped from `total_yield`) — derived as `solar_production` when missing
- `lifetime_self_consumption` — derived as `load - import` when missing
- `lifetime_load_consumption` — derived as `solar + import + discharged - charged - export` when missing (issue #528)

These sensors remain in the per-platform suffix maps (`GROWATT_MIN_SUFFIX_MAP`, `GROWATT_SPH_SUFFIX_MAP`, etc.), get discovered, appear in the wizard sensor list, and are saved to config, but nothing reads them at runtime. Remove them from the suffix maps and `sensorDefinitions.ts` to reduce wizard clutter and avoid confusion about which sensors actually matter.

**Files**: `core/bess/ha_api_controller.py` (per-platform suffix maps), `frontend/src/lib/sensorDefinitions.ts`

---

### Consolidate Growatt MIN/SPH detection into a single path

**Impact**: Low | **Effort**: Low | **Dependencies**: `ha_api_controller.py`

**Description**: There are two separate heuristics for distinguishing Growatt MIN vs SPH:
1. `_parse_ha_metadata()` (line ~2163): binary check for `-tlx_` in any unique_id
2. `discover_sensors_from_registry()` (line ~2725): runs both suffix maps and picks the one with more matches

Both are called sequentially from `run_setup_discovery()` in `api.py`. They serve different stages (platform identification vs sensor mapping), but having two heuristics for the same question is fragile — they could theoretically disagree. Consolidate by deriving the platform list from the suffix map match results instead of the separate `has_tlx` check.

**Files**: `core/bess/ha_api_controller.py` (`_parse_ha_metadata`, `discover_sensors_from_registry`), `backend/api.py` (`run_setup_discovery`)

### Other Technical Debt

- Refactor all API endpoints to use dataclass-based serialization (with robust mapping for all field variants) for consistent, type-safe, and future-proof API responses. Ensure all details and fields are preserved as in the original dict-based implementation.

**From #221 (spot_multiplier/export_spot_multiplier) code review — deferred cleanup, not bugs**:

- `backend/api.py`'s `_pricing_defaults_for_discovery()` duplicates the provider-priority chain (`octopus > entsoe > nordpool_official > nordpool_hacs`, gated on `not nordpool_found`) already computed independently in `frontend/src/pages/SetupWizardPage.tsx`'s `autoProvider` logic. The two can drift out of sync if the priority order changes in only one place. Consider deriving both from a single shared source (e.g. have the backend return the resolved provider and have the frontend just consume it, instead of recomputing it).
- `backend/settings_store.py`'s `_migrate_schema()` electricity_price migration block hardcodes `spot_multiplier`/`export_spot_multiplier`/`use_actual_price` by name instead of iterating `PRICE_STORE_TO_API` + `PriceSettings` defaults generically. Every future `PriceSettings` field will need a new hand-written migration block, and it's easy to forget (silent `ValueError` in `build_system_settings()` at startup for existing users' configs). Consider making the migration generic against `PRICE_STORE_TO_API`.

**TOU Segment Matching is Fragile**:
The current TOU comparison uses exact matching on start_time, end_time, batt_mode. If a segment shifts by 15 minutes (e.g., 00:00-00:59 → 00:15-01:14), it's seen as completely different, resulting in 2 hardware writes (disable old + add new) instead of 1 update. Consider:

- Overlap-based matching: If segments overlap significantly and have same mode, treat as "same"
- Smart merging: Detect when segments can be extended/shortened rather than replaced

**Remove Hourly Aggregation Legacy** (mostly done — residual only):
The controller-side hourly aggregation is gone: `_calculate_hourly_settings_with_strategic_intents()`, `get_hourly_settings()`, `_get_hourly_intent()` and the `hourly_settings` dict no longer exist, and `adjust_charging_power()` reads `get_period_settings(current_period)` directly. What remains is display-side:

- `backend/api.py`'s `_get_hourly_settings_from_periods()` — a compatibility shim that majority-votes the 4 quarterly intents of an hour for API endpoints that still return hourly rows. Removable once the schedule display table renders 15-min periods.
- `get_strategic_intent_summary()` (`core/bess/inverter_controller.py`) still summarises per hour rather than per period.

**Re-run optimization on energy prediction method change**:
When the user changes the consumption strategy (e.g. from `sensor` to `fixed`), the optimization should re-run immediately with the new prediction method rather than waiting for the next scheduled cycle. The prediction cache should be cleared and a fresh optimization triggered in the same request that saves the new strategy.

## From #215 health-recovery-banner code review (non-blocking, low severity)

**Concurrent health-check race could double-record a recovery**:
`BatterySystemManager._run_health_check` reads `_cached_health_results` as `previous_results`, then later overwrites it and calls `_update_health_recoveries(previous_results, health_results)` — none of this is lock-protected. If the 5-minute cron job and a manual "Recheck now" click ever overlap almost exactly, both could read the same stale `previous_results` and each record a recovery for the same real transition, leaving a duplicate entry in the banner until acknowledged. Narrow timing window, not observed in practice; would need the tracker's own lock extended around the read-modify-write in `_run_health_check` to close it.

**Component disappearing from health checks leaves a stale pending recovery**:
`_update_health_recoveries` (core/bess/battery_system_manager.py) only visits components present in the *new* checks list. If a component goes ERROR then becomes unconfigured/absent (e.g. an optional check dropped by a settings change) before recovering, `clear_for_component` never runs for it and any stale pending recovery for that name lingers until acknowledged or evicted by the 50-entry cap. Edge case, low impact.

**`/api/health-recoveries` uses camelCase (`convert_keys_to_camel_case`) while sibling `/api/runtime-failures` returns raw snake_case `__dict__`**:
Both are valid given each has its own matching frontend hook, but it's an inconsistent precedent for the next tracker-style endpoint someone adds. Worth standardizing next time either is touched.

## From #317 period-group intent reconciliation code review (non-blocking)

**`backend/api.py`'s new `today_reconciled_intents` build has two silent fallbacks** (`planned_intent` defaults to `"IDLE"` when `period_idx >= len(planned_intents)`, and out-of-range periods also append `planned_intent`) that follow the existing `INTENT_TO_MODE.get(intent, "load_first")` convention in `inverter_controller.py`, but technically fall under `docs/agents/rules.md`'s "Explicit failure over silent degradation" rule. Low risk since it's a display-only path, not a control path, and the pattern is already pervasive in this file — not filed as a blocker.

**Behavior change on cold start**: previously, if `schedule_manager.strategic_intents` was empty (e.g. right after startup, before the controller applies a schedule) but `schedule_store.get_latest_schedule()` already had a stored schedule, `get_detailed_period_groups()` returned `[]` outright (its `if not effective_intents: return []` early exit). Now the endpoint always builds a full per-period `today_reconciled_intents` list (defaulting missing planned entries to `"IDLE"`), so period_groups will render partial data (actual periods reconciled, future periods shown as `"IDLE"`) in that window instead of nothing. This looks like an improvement in line with the issue's intent (show what's real, not what's stale) but is a user-visible behavior change worth knowing about if it's ever reported as "showing IDLE for periods with no plan yet."

**Files**: `backend/api.py` (`get_growatt_detailed_schedule`, ~lines 1719-1758)

---

## From #387 runtime power gap-fill code review (non-blocking)

**`backend/app.py` constructs `BESSController()` and calls `start_in_background()` at module level**, which is what forces `backend/tests/test_scheduler_jobs.py` to patch two unrelated methods (`SettingsStore._write`, `HomeAssistantAPIController.get_ha_config`) just to import the module safely for testing.

**Do not "fix" this with `if __name__ == "__main__":`** — every launch path is `uvicorn app:app` (`backend/run.sh`, `backend/Dockerfile.dev`, `docker-compose.ci.yml`, `docker-compose.prod-test.yml`), so `__name__` is always `"app"` and the guarded block would never run. That would silently stop BESS from ever starting while leaving the web server up.

The real fix is to move construction into the FastAPI `lifespan` startup hook, which runs under uvicorn but not on bare import. That is a change to the application's entire startup path (and `api.py`'s `from app import bess_controller` would then see `None` until lifespan runs), so it needs the mock-HA E2E stack to verify — not a small cleanup.

---

## From #450 hybrid grid-DP + windowed exact-PWL investigation (found while building the alternative to PR #461's MILP)

**PR #461's MILP has a residual self-throttle export-credit bug beyond the one already fixed in that branch's `0df1d8bc`.** In that model `throttled[t]=1` means "not self-throttled, full credit allowed" and `throttled[t]=0` forces `credited_exp=0` (verified against the constraint block in `0df1d8bc`, not just its commit message). The commit added `throttled=1 ⟹ credited_exp == exp` (a genuine lower bound in the full-credit branch) and `throttled=0 ⟹ exp <= threshold` (restricting the zero-credit branch to genuinely small exports), but never added the **converse of the second**: nothing forces `throttled=0` when `exp <= threshold`. So `throttled` stays a free binary whenever `exp` is small — the solver can always choose `throttled=1` and claim full revenue credit for exports that should have been zero-credited. Measured on `regression_2026_08_02_043728.json`: 11 DISCHARGE periods export ≤ 0.01 kWh and are fully credited, worth exactly 0.031857 SEK — which is precisely the gap between the MILP's *reported* `battery_solar_cost` (-6.012542) and the MILP's *own* true DP-reward objective value for the same schedule (-5.980684), i.e. `-6.012542 = -5.980684 - 0.031857`. On the real objective the MILP's schedule (-5.980684) is in fact *worse* than the full-horizon exact PWL's (-5.984652); the headline -6.012542 is an artifact of the over-credit, not a better plan. This is separate from and additional to the four MILP bugs already documented in PR #461's own description (import/export exclusivity, AC-cap sentinel, the credited-exp lower-bound fix in `0df1d8bc`, and the shadow-price LP-dual non-uniqueness). Confirmed structurally impossible in the grid-DP/PWL approach, since self-throttle there is a deterministic formula (`if exp <= threshold: exp = 0`) with no LP slack variable to exploit — this bug class is intrinsic to the MILP's constraint-encoding paradigm, not something a future MILP fix could accidentally miss again in the same code path (it needs the converse constraint added).

**~~`_build_period_data`'s reported `battery_solar_cost` metric drifts from the actual DP-reward optimization objective~~ — FIXED by #497.** The drift existed because `_build_period_data` priced raw `_ac_flows` `grid_exported` without zeroing self-throttled export revenue, while `_compute_reward` did zero it (measured -0.0137 to -0.0319 SEK depending on schedule, so the *reported* cost systematically favoured whichever schedule had more never-delivered export). #497 removed the self-throttle correction entirely — the DP no longer proposes a discharge that would produce a sub-resolution export, so there is no never-delivered export for the two paths to disagree about. Verified: `reward_objective_cost == economic_summary.battery_solar_cost` exactly on all 33 fixtures. Fixture pinning can now use either metric; `test_issue_450_hybrid_resolution` asserts the two agree.

**Files**: `core/bess/milp_battery_algorithm.py` (PR #461 branch only — the converse self-throttle constraint). The `_build_period_data` reporting-vs-objective drift is fixed; the MILP note above is also moot in practice, since the self-throttle mechanism it describes no longer exists in the DP.

---

## From the #450 synthetic tie-coverage validation suite (found while building the reference-cost measurement for PR #467's own tie detector)

**RESOLVED.** The windowed PWL solver's backward induction
(`core/bess/pwl_window_dp.py`) could return a value worse than a feasible,
in-grid alternative — on `historical_2024_08_16_high_spread_no_solar` segment
(7,12) it returned 42.679610 SEK against a grid-DP path costing 42.648857.

Root cause: `_pwl_candidate_values_at`'s discharge-rate feasibility mask
compared the action against the affordable power *exactly*, while the replay's
`_discharge_candidates` floors the same bound onto the integer-percent
hardware lattice with a `+ 1e-9` slack. Breakpoint abscissae are built by
adding lattice energies to the previous row's breakpoints, so one mathematical
onset arrives as a cluster of ULP-separated floats and near-duplicate merging
keeps an arbitrary member; against a tolerance-free comparison that member
decided feasibility. The backward pass therefore evaluated V a hair below an
onset, dropped the discharge level the replay would have taken there, and
recorded a value 0.042 SEK below the truth — enough to flip the window's
decision. This broke the module's own stated invariant that both passes
enumerate one action set.

Fixed by mirroring `_discharge_candidates`' arithmetic exactly in the backward
mask (fold the AC headroom into the same bound, then percent-floor with the
same slack). The segment now returns 42.639365, i.e. the reference beats the
DP, and the value table's self-consistency improved from a 2.94 SEK worst-case
table-vs-recompute error to ≤1e-6 SEK. Pinned by
`test_backward_pass_admits_the_discharge_levels_the_replay_admits` and
`test_reference_does_not_undershoot_the_hybrid_on_the_regression_segment`.

Residual (not a defect, noted for future work): the true value function is
genuinely *discontinuous* at discharge-feasibility onsets, and a continuous PWL
representation cannot express a jump — the refinement loop brackets each jump
with breakpoints ~1e-8 kWh apart. Queries landing strictly inside such a
bracket still read an interpolated intermediate value. Decision-relevant states
sit on the lattice, so the fix removes the reachable failure mode, but the
near-duplicate merge in `_pwl_window_seed_points` /
`run_pwl_window_backward_induction` (first-wins, value-unaware) remains the
mechanism that would decide such a case arbitrarily. Making that merge
value-aware (keep the upper-semicontinuous representative) would harden it
further.

---

## From the E2E scenario fixture cleanup PR (non-blocking)

**`e2e/package-lock.json` has `@playwright/test` locked at 1.59.1 while 1.62.1 is current.** `package.json`'s `^1.59.1` range already permits the newer version — the lockfile just hasn't been refreshed since it was last committed. Bumping it (`npm update @playwright/test` + commit the lockfile) also changes the pinned Chromium revision that CI/local runs download, so it's worth doing deliberately in its own PR rather than as a drive-by here.

**`.github/workflows/ci.yml`'s E2E job runs all ~15 phases (normal-day, growatt-vpp, 13 wizard scenarios) sequentially in one job.** Each phase is independent (its own docker-compose stack, no shared state), so this is a good candidate for a `strategy: matrix` job split — one parallel job per scenario instead of one long sequential job. Would cut wall-clock from "sum of all phases" to roughly "the slowest single phase." Since the repo is public, GitHub Actions minutes are free/unlimited on standard runners, so this is purely a turnaround-time win, not a cost tradeoff. Worth its own PR — restructuring `ci.yml`'s step list into matrix `include:` entries (scenario, settings file, options file, step label) isn't a small tweak.

---

## From the power-monitoring sensor-gating fix (non-blocking)

**`core/bess/settings_store.py` has duplicate top-level `VALID_PLATFORMS` and `SHARED_SENSOR_KEYS` definitions.** Both constants are defined twice — once around lines 36-58, again around lines 67-89 — byte-identical in each pair. The second definition silently shadows the first; nothing currently breaks because they're kept in sync by coincidence, but the duplication is dead code and a drift risk if one copy is ever edited without the other. Pre-existing on `main`, unrelated to and not introduced by `docs/superpowers/plans/2026-08-07-power-monitoring-sensor-gating.md`. Fix: delete one copy of each.

---

## From the #497 flow-invariant suite (non-blocking)

**`test_scenarios.py::test_all_scenarios` and `test_plan_faithfulness.py::test_realized_matches_planned_across_all_fixtures` use two different definitions of "realized" (R).** The inline block at the end of `test_all_scenarios` builds commands via `derive_control_command(...)` without passing the gate authorization; `helpers.run_scenario_realized` — which the new corpus-wide gap pin uses — passes it. (As of #526 that argument is `intra_period_discharge_allowed`, taken from `pd.decision`; it was previously the `shadow_price`/`buy_price` pair.) So the two corpus-wide R-vs-P checks are not measuring the same R. Nothing is wrong today, but whoever fixes #497 and re-pins `PLAN_EXECUTION_GAP_SEK` will be re-pinning against one definition while the looser per-scenario check enforces the other. Fix: replace the inline block in `test_all_scenarios` with a `run_scenario_realized` call. Left out of the invariant-suite PR because it changes what an existing test asserts, which deserves its own diff rather than riding along with test-infrastructure additions.

---

## The bigger question: why does the DP need a dozen epsilons at all?

Raised while diagnosing #497. Worth its own investigation, not a drive-by fix.

The DP currently carries something like a dozen independently-chosen small
constants, each added to patch one symptom:

| Constant | Where | Purpose |
|---|---|---|
| ~~`self_throttle_export_threshold_kwh`~~ | *deleted by #497* | self-throttle export credit (#240) |
| `GRID_FLOW_RESOLUTION_KWH` (0.1) | `models.py` | one constant for counter resolution, shared by `models.py`'s fold and the DP's executability rule (#497) |
| ~~`BATTERY_EXPORT_THRESHOLD_KWH`~~ | *deleted by #497 review follow-up* | was intent classification boundary; the #466 tie-break round-up band that used it is dead under the exclusion |
| `0.01` battery_to_grid / grid_to_battery | `strategic_intent.py` | intent classification |
| `_POWER_THRESHOLD_KW` (0.1) | `strategic_intent.py` | intent noise filter |
| `POWER_TOLERANCE_KW` | `dp_battery_algorithm.py` | charge/discharge/idle branch selection |
| `POWER_CLASSIFICATION_THRESHOLD_KW` | `dp_battery_algorithm.py` | minimum discharge candidate |
| `SOE_STEP_KWH` (0.1) | `dp_constants.py` | DP state grid resolution |
| `rate_step` = max_discharge/100 | `dp_battery_algorithm.py` | hardware percent resolution |
| `epsilon` (tie detection) | `tie_detection.py` | value-function noise band |
| ~~`max_cover_p` half-step band~~ | *deleted by #497 review follow-up* | was #466 load-cover tie-break round-up; exact/under-cover only now |
| `validate_energy_balance` tolerance (0.2) | `models.py` | cross-sensor balance warning |
| `GRID_RESOLUTION_TOLERANCE` (0.10 SEK) | `test_plan_faithfulness.py` | plan-faithfulness slack |

**Partly answered by #497**, which is worth reading as a worked example before
attempting the rest. Framing 2 below turned out to be the productive one: the
self-throttle threshold existed only because the DP modelled *commanded*
rather than *executable* energy. Removing that premise deleted the constant,
its platform property, its whole parameter chain, and — as consequences, not
as separate fixes — the plan-vs-execution gap and the objective-vs-report
drift. Two constants collapsed into one shared `GRID_FLOW_RESOLUTION_KWH`.
The remaining rows above are still worth the same treatment.

Each is defensible in isolation. The failure mode is that they interact: any
two of them that describe *the same physical boundary* in different units, or
at different stages of the pipeline, can silently drift apart. #240 vs #350 is
one instance (#497); the design doc referenced at `strategic_intent.py:44`
records an earlier one. Both were found by a human reading a schedule by hand,
years apart, and both needed DP expertise to adjudicate — which does not scale
and is not something the maintainer can review.

The question is not "are these values right" but "why are there so many
independent ones". Candidate framings, none investigated:

1. **How many of these are really the same boundary expressed twice?** The
   self-throttle threshold, the fold floor and the intent classifier's
   `battery_to_grid` cut all try to answer one question: "is this export real?"
   Three constants, three call sites, three chances to disagree. If that is one
   concept, it should be one named thing with one owner.
2. **How many exist only because the DP models *commanded* energy rather than
   *executed* energy?** #497's fix removes one by making the plan describe what
   the hardware will actually do. `max_cover_p` (#466) may be the same shape.
   The inverter simulator already encodes the true execution semantics; the DP
   approximating them with epsilons is arguably the root pattern.
3. **How many are discretization artifacts that a continuous formulation would
   not need?** `SOE_STEP_KWH`, `rate_step`, the tie-detection `epsilon` and the
   half-step cover band all exist because the DP searches a grid. `pwl_window_dp`
   already explores a piecewise-linear alternative.

Concrete first step, cheap and non-destructive: enumerate every small constant
in `core/bess/`, and for each record the physical question it answers. Any
physical question answered by more than one constant is a latent #497. That
inventory is a day's work and would tell us whether this is a real structural
problem or a dozen unrelated coincidences — worth knowing before anyone
proposes a redesign.

---

## From #502 (curtailed periods overcharged in reported cost) fix

**`core/bess/simulation/inverter_simulator.py` has no concept of PV export-limit curtailment (#269).** `run_scenario_realized`'s `simulate()` only replays the DP's own charge/discharge commands via `derive_control_command` — it has no model of BSM's separate `apply_export_limit` hardware write, which is a second, independent control path issued alongside the DP-derived commands, not derived from them. #502 made the *reported* plan (`economic_summary.battery_solar_cost`) correctly exclude a curtailed period's cost, since BSM really will curtail it to zero at runtime — but the simulator's realized cost (R) still pays the full honest negative-price export for that period, since it has no way to know curtailment will fire. This opened a genuine, structural R-vs-P gap for any fixture with an actual curtailed period: `regression_2026_08_08_143843`'s pin moved from +0.0490 to +0.0693 SEK (re-pinned in #507; every other fixture in the corpus was unaffected — it's the only one with a real curtailed period). The gap is not the reported plan being newly dishonest — it is the simulator lacking fidelity for a feature it never modeled. Fix: teach `simulate()` to also apply export-limit curtailment (zero the solar-sourced export share, mirroring `apply_export_curtailment_to_period_data`'s logic) for periods where `export_curtailment_active` and the period's sell price is below the floor, closing the gap back toward zero. Left out of #507 since it's a simulator feature addition, not a reporting bug fix — the PR that fixes #502's reporting bug is not the place to also extend simulator fidelity.

---

## From #466 residual-cover review (out-of-scope CONFIRMED findings, main-branch code)

Code review of the #466 residual-cover branch surfaced these in code the branch
does not touch (curtailment/display work from #501/#502/#507/#508). Verified by
the reviewer with executed repros where noted; none are addressed in that PR.

1. **`decision.curtailed` predicate wider than the adjuster's** (`dp_battery_algorithm.py` ~791, executed repro): `should_curtail_export` checks total `grid_exported > 0` while `apply_export_curtailment_to_period_data` gates on `solar_to_grid > 0`, so a battery-sourced sub-floor export renders "Curtailed (No Export)" while actually exporting at negative revenue. Worse, `reward_sell_price` floors to 0 for ALL export in sub-floor periods, letting the DP plan battery exports at negative prices as if PV throttling neutralized them. Gate both the flag and the reward floor on the solar-sourced share.
2. **`daily_view_builder.py:96` `export_curtailment_active: bool = False` default** is a silent fallback used by zero production callers; a future caller omitting it silently reproduces #502's phantom-cost bug. Make it required; add the arg at the 14 test sites.
3. **`models.py:527` hand-lists all 9 `EnergyData` init fields** instead of `dataclasses.replace(energy, grid_exported=..., clipped_solar=...)`; any future init field silently reverts to default in the curtailment-adjusted copy.
4. **`SystemStatusCard.tsx:293` "Curtailed (No Export)" label** is wrong at hourly display resolution where `curtailed = any(quarter)` can cover an hour that mostly exports; soften the copy or derive from the current quarter.
5. **`backend/api.py:1326` (PLAUSIBLE, latent)**: tomorrow-schedule pd-is-None branch appends to `soc_values`/`curtailed` but not `intents`/`actions`; a future mid-anchored schedule would shift SOC/curtailed onto wrong rows. Cheap hardening: append symmetrically.

---

## From #542 (signed battery power) review — not addressed in that PR

1. **Existing installs only pick up a signed-sensor pairing when discovery is
   re-run.** `discover_sensors_from_registry` is reachable only from
   `POST /api/setup/discover` (`backend/api.py:2841`); nothing re-runs it at
   startup. So an install that already has `battery_charge_power` mapped and
   `battery_discharge_power` unmapped stays broken (health check ERROR, net
   battery power `None`) until the user re-runs the setup wizard. Same is true
   of the grid pairings shipped in #475/#438 — it is a property of the
   mechanism, not of #542. Deliberately not "fixed" by widening
   `_is_shared_signed_battery_power()` to also fire when the discharge key is
   merely absent: that predicate would silently paper over an unconfigured
   install rather than the platform fact it is supposed to encode. If we want
   upgrades to self-heal, the honest fix is a re-discovery pass at startup for
   platforms whose sensor set is fully integration-derived.
Items 2 and 3 below are **fixed** (PR for #542 follow-up). Kept here with the
correction, because item 2 as originally written was wrong about where the
value surfaced and that matters for how the next reader reads this list:

2. ~~**The health panel shows the raw signed value on both battery rows.**~~
   **Corrected and fixed.** The health panel was never wrong:
   `perform_health_check` calls the getter (`method()`) for `rawValue`/
   `displayValue`, so a native SolaX discharging at 800 W has always rendered
   `0 W` / `800 W` — verified by running it. What *was* wrong is
   `get_method_sensor_info`'s own `current_value` field, which reported the
   raw signed state on both rows; no consumer reads that field today, so this
   was latent, not user-visible. Now routed through `_signed_split_state()`,
   for the grid pairing as well as the battery one.
3. ~~**The battery split hardcodes its one legal polarity.**~~ **Fixed.**
   The split moved into `_split_signed_battery_power()`, which branches on
   `battery_power_polarity` and raises `ValueError` on anything other than
   `charge_positive`. The grid helper stays deliberately lax (anything that
   isn't `"import_positive"` is treated as `"export_positive"`).

## From #601 (defer running-window end rewrites) review — non-blocking

**`_assign_hardware_slots` does not know about the new `same_segment`
equivalence.** `core/bess/growatt_min_controller.py:440`, specifically the
`content_key`/`keep_keys` logic at lines 461-486, reserves a hardware slot for
a `current_tou` entry only on an exact `(start, end, mode, enabled)` match
against `planned_tou`. `same_segment` now treats a running segment as
unchanged even when its `end_time` differs (the change deferred beyond the
write horizon), so a deferred segment's real slot is not recognized as spoken
for and lands in `free_slots` — in principle it could be handed to another
segment written the same cycle, silently overwriting the deferred segment with
no disable or update recorded.

Not reachable today, and the reviewer and I both failed to build a repro:
`strategic_intents` partitions the day into non-overlapping segments, so
anything eligible for `to_update` this cycle starts within
`WRITE_HORIZON_MINUTES` of `effective_minute`, while a genuinely-deferred
segment's nearest boundary (per `same_segment`'s own `bites_at`) is by
definition further away than that. Correctness here therefore rests on an
invariant that is neither asserted nor referenced near the function, and the
`_assign_hardware_slots` docstring ("A slot counts as spoken for when it holds
anything in planned_tou") is now inaccurate for the deferred case. Fix by
making slot preservation `same_segment`-aware directly, before anything
relaxes the single-partition assumption (a multi-window-per-period or VPP
mode would).
