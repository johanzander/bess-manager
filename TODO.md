# Energy Management System Improvements - Prioritized Implementation Plan


## �🔴 **CRITICAL PRIORITY** (System Reliability)

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

### **Rename `strategic_intent` to `battery_intent` throughout the codebase**

**Impact**: Low | **Effort**: Low | **Dependencies**: `decision_intelligence.py`, `dp_battery_algorithm.py`, `sph_schedule.py`, `models.py`, frontend

**Description**: The term "strategic intent" has been replaced with "battery intent" in the software design document. Rename accordingly in code:

- `StrategicIntent` enum → `BatteryIntent` (`dp_battery_algorithm.py`)
- `strategic_intent` field → `battery_intent` in `DecisionData` (`models.py`)
- All assignments and references in `decision_intelligence.py`, `sph_schedule.py`, `battery_system_manager.py`, and any API serialization
- Frontend: any display label or type referencing `strategicIntent` / `strategic_intent`

### **Minor cleanup from issue #201 (stale health-check banner) fix**

**Impact**: Low | **Effort**: Low | **Dependencies**: `core/bess/influxdb_helper.py`, `backend/api.py`

**Description**: A few small, non-blocking cleanups identified during code review of the #201 fix:

- `get_sensor_data_batch` and `get_power_sensor_data_batch` (`core/bess/influxdb_helper.py`) each have their own copy of the `if not is_influxdb_configured(): ...` early-return guard — could be factored into a shared decorator/helper if a third call site appears.
- `GET /api/system-health` and `POST /api/system-health/recheck` (`backend/api.py`) share the same `_require_configured_system` + health-check + `convert_keys_to_camel_case` + `HTTPException(500)` shape, differing only in whether the result is cached. Worth revisiting if a third variant is ever needed.
- The new 5-minute health-check cron job (`backend/app.py`) also re-runs `test_influxdb_connection()` for the subset of users who *do* have InfluxDB configured (it correctly skips for everyone else). This is intentional — same cadence agreed for the dashboard banner — but worth knowing if InfluxDB load ever becomes a complaint.

### **Investigate redundant `power` gate in strategic intent detection**

**Impact**: Low | **Effort**: Low | **Dependencies**: `decision_intelligence.py`, `dp_battery_algorithm.py`

**Description**: In `create_decision_data` (`decision_intelligence.py`), strategic intent is determined by an outer `power < -0.1` / `power > 0.1` check followed by inner energy flow checks (`battery_to_grid`, `grid_to_battery`). The `power` check is likely redundant: the detailed flows in `EnergyData` are derived automatically via `_calculate_detailed_flows()` from `battery_charged`/`battery_discharged`, so if `power < -0.1` then `battery_discharged > 0` and the flow checks already handle the distinction. The inner flow thresholds (0.1 kWh) also provide the same noise filtering as the outer power threshold. Verify whether the outer `power` gate can be removed and intent determined solely from energy flows.



### ~~**Improve InfluxDB health check error messages in UI**~~ ✅ Completed (v8.2.1)

**Resolution**: HTTP 401/403/404 now show actionable messages; ConnectionError shows the URL that failed.

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

### 2. **Complete Decision Intelligence Implementation**

**Impact**: Medium-High | **Effort**: Medium | **Dependencies**: `decision_intelligence.py`, `sensor_collector.py`, `dp_battery_algorithm.py`

**Vision**: Transform the DP battery optimization from a "black box" into a transparent, educational system that helps users understand complex energy economics and multi-hour optimization strategies. Users should see real SEK values for each energy pathway and understand *why* the optimizer made each decision — not just what it decided.

**What is working** (future/predicted hours only):

- Advanced flow pattern recognition: `SOLAR_TO_HOME_AND_BATTERY`, `GRID_TO_HOME_PLUS_BATTERY_TO_GRID`, etc.
- Economic chain explanations: multi-hour strategy reasoning with real SEK values
- Future target hours: identifies when arbitrage opportunities occur
- Frontend `DecisionFramework.tsx` component is complete and consuming enhanced data

**Gap 1: Historical hours show fallback values**

Past periods (already executed) still show:

- `advanced_flow_pattern: "NO_PATTERN_DETECTED"`
- `detailed_flow_values: {}`
- `economic_chain: "Historical data - basic strategic intent"`

Root cause: the historical data pipeline (`SensorCollector` → `HistoricalDataStore`) does not run through `decision_intelligence.py`. Fix: apply `create_decision_data()` when recording historical periods, using actual energy flow data and prices from that period.

**Gap 2: Future economic values showing 0.00 SEK**

Future arbitrage calculations (the "expected arbitrage value" in economic chain explanations) show 0.00 SEK. Needs investigation in DP algorithm economic chain value computation and how future target hour values are propagated.

**Files**: `core/bess/decision_intelligence.py`, `core/bess/dp_battery_algorithm.py`, `core/bess/sensor_collector.py`, `frontend/src/components/DecisionFramework.tsx`

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

### 5. **Enhance Insights Page with Decision Detail**

**Impact**: Medium | **Effort**: High | **Dependencies**: Backend decision logging

**Current State**: `InsightsPage.tsx` renders `PredictionAnalysisView` but lacks decision reasoning, algorithm transparency, and confidence metrics

**Implementation**:

- **Add detailed decision analysis**: Why each battery action was chosen
- **Algorithm transparency**: DP optimization steps, price arbitrage reasoning
- **Alternative scenarios**: Options considered, confidence metrics

**Technical Tasks**:

- Extend backend to capture decision reasoning
- Create decision timeline component
- Add interactive decision trees
- Include confidence metrics display

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

## 📄 **DOCUMENTATION IMPROVEMENTS**

### Improve Consumption Forecast Documentation

**Impact**: Medium | **Effort**: Low | **Dependencies**: `docs/INSTALLATION.md`

**Current gap**: Step 3 explains *how* to create the 48h average sensor but not *why* it works or how to tune it for different households.

**What to add**:

- Explain what BESS does with the sensor: the DP optimizer uses the current sensor value as the predicted consumption for all future periods in the optimization horizon.
- Explain why the battery-active filter matters: without it, battery discharge power inflates the apparent home consumption, causing the optimizer to over-predict load and charge more aggressively than needed.
- Explain how to tune for your household:
  - The 48h window is a good default — it captures both weekday and weekend patterns.
  - If your consumption has strong seasonal variation (e.g. heat pump), consider a shorter window (12-24h) so the average adapts faster.
  - If you have large predictable loads (sauna, hot tub), the average smooths these out — the optimizer will not plan for a 3 kW sauna spike at 19:00 specifically.
  - EV charging: whether to include or exclude depends on whether BESS should see EV charging as "normal home load" (include → optimizer plans for it) or as a separate managed load (exclude → optimizer ignores it, relies on discharge inhibit sensor instead).

---

### Improve EV Charging / Discharge Inhibit Documentation

**Impact**: Medium | **Effort**: Low | **Dependencies**: `docs/INSTALLATION.md`

**Current gap**: Line 172 says "EV charging: Exclude if managed separately. Include if you want BESS to optimize around it." — too brief. The discharge inhibit sensor is not explained at all.

**What to add**:

BESS does not control EV charging — it is designed to work in parallel with it. Normally both the car and the battery charge when electricity is cheap, so there is no conflict.

The exception is **Tibber grid rewards** (and similar grid balancing programs). Grid rewards can start EV charging even when prices are not at their lowest, because Tibber compensates you separately for supporting grid balancing.

BESS auto-detects any `binary_sensor` whose entity ID ends with `_charging` or `_is_charging` (e.g. `binary_sensor.zap263668_charging`) and treats it as a **discharge inhibit** signal. When the sensor is `on`, BESS will not discharge the battery even if the schedule says to.

If BESS were to discharge the battery at the same time, that energy would flow to the car instead of from the grid — you would miss out on the grid reward income while also losing the battery support you would have had for the home.

The discharge inhibit only blocks discharging — it does not change the TOU schedule, trigger charging, or interfere with the EV charging session in any way.

---

## 🟢 **LOW PRIORITY** (Polish)

### 7. Add Prediction accuracy and history

### 8. Intent is not always correct for historical data

**Current State**: The inverter sometimes charges/discharges small amounts like 0.1kW. Or its a rounding error or inefficiencies losses when calculating flows. I don't think its a strategic intent, but it is interpreted as one.

### ~~9. Add multi day view~~ ✅ Completed (v7.2.0-v7.3.0, PRs #21-#22)

**Problem**: Today we only operate on 24h intervals.
But at noon every day we get tomorrows schedule. We could use this information to take better economic decisions. It would mean changing a lot of places where 24h is hard coded.

**Resolution**: The DP optimizer now considers up to 192 periods (2 days) when tomorrow's prices are available (PR #21). Dashboard charts (PR #22) and inverter schedule overview (PR #23) display the extended horizon. TOU deployment remains today-only due to Growatt hardware limitations.

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

### **Suppress retry warnings for expected Nordpool "tomorrow not available" responses**

**Impact**: Low | **Effort**: Low | **Dependencies**: `official_nordpool_source.py`, `ha_api_controller.py`

**Description**: The Nordpool integration returns HTTP 500 when tomorrow's prices aren't published yet (typically before ~13:00 CET). `_api_request` logs a WARNING on each retry attempt, producing misleading warnings every optimization cycle overnight (00:00–12:00). The retry eventually fails, but `get_combined_prices()` in `price_manager.py` handles this gracefully — it catches the exception and falls back to today-only prices with an INFO log. The warnings are harmless but noisy and can alarm users reading logs.

**Options**:
1. Have `official_nordpool_source.py` catch the 500 for tomorrow and raise a specific "not available yet" exception that `_api_request` doesn't retry
2. Add a `suppress_retry_warnings=True` param to `_api_request` for expected-failure calls
3. Accept the noise as-is (log-level only, no UI banners)

**Files**: `core/bess/official_nordpool_source.py`, `core/bess/ha_api_controller.py`, `core/bess/price_manager.py`

## 🔵 **ROBUSTNESS IMPROVEMENTS** (System Observability)

### **Retry discovery on startup when HA WebSocket is not ready**

**Impact**: High | **Effort**: Low | **Dependencies**: `ha_api_controller.py`, `battery_system_manager.py`

**Description**: BESS Manager starts as an HA add-on and can launch before HA's WebSocket API is fully ready. When the initial `discover_integrations()` WS connection fails during early boot, `nordpool_config_entry_id` stays None and the system enters degraded mode with no price data — even though HA becomes ready seconds later. Observed on Niklas's system (b18, 2026-05-26): WS failed at 05:08 (4 min after boot), but by 05:45 discovery worked fine.

**Fix**: Re-attempt discovery with short backoff (e.g. 5s, 10s, 20s) until `config_entry_id` is populated or a max number of retries is reached.

---

### ~~**Complete or Remove EV Energy Meter Integration**~~ ✅ Completed (v8.0.0)

**Resolution**: EV energy meter dead code removed entirely in v8.0.0 release.

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

**Description**: `reinitialize_tou_schedule()` is called directly inside the `async def patch_settings` handler, which blocks the event loop while performing up to 36 synchronous HTTP calls to Home Assistant (reading all 9 TOU slots × 4 entities each). Should be offloaded to a background thread or thread pool executor.

**File**: `backend/api.py` — `patch_settings` / `setup_complete`, `core/bess/ha_api_controller.py` — `read_tou_segments_from_entities`

---

### Startup Race: Concurrent `_initialize_tou_schedule_from_inverter` Calls

**Impact**: Low | **Effort**: Low

**Description**: `BatterySystemManager.start()` calls `_initialize_tou_schedule_from_inverter()` at startup, and the same underlying path is triggered again by `reinitialize_tou_schedule()` when switching demo→live. There is no threading lock protecting against concurrent calls. If both happen in rapid succession (fast live switch during startup), both threads may issue overlapping hardware writes.

**File**: `core/bess/battery_system_manager.py`

---

### Optional Components with ERROR Status Shown as Green in PreflightCheckDialog

**Impact**: Low | **Effort**: Low

**Description**: `PreflightCheckDialog.tsx` maps `required=false` checks unconditionally to `status: 'ok'` (green CheckCircle). An InfluxDB component in a genuine ERROR state (misconfigured, not just NOT_CONFIGURED) would appear green, masking the problem. Consider using a neutral/warning icon (e.g. `AlertCircle`) for optional components that are ERROR, reserving green for OK status only.

**File**: `frontend/src/components/PreflightCheckDialog.tsx` line 34

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

### Pinned scenario fixtures never exercise a realistic (nonzero) terminal value

**Impact**: Medium | **Effort**: Medium-High | **Dependencies**: `core/bess/tests/unit/test_scenarios.py`, `core/bess/dp_battery_algorithm.py`, `core/bess/battery_system_manager.py`

**Description**: `optimize_battery_schedule()` defaults `terminal_value_per_kwh=0.0`, and every one of the ~26 pinned scenarios in `test_scenarios.py` calls it without overriding that default — so the entire pinned-fixture regression suite always tests the DP with terminal value hardcoded to zero, regardless of what each scenario's horizon is meant to represent. In production, every real optimization run computes a nonzero terminal value via `_calculate_terminal_value()` (`battery_system_manager.py`). Found while investigating #345 (terminal-value zeroing at the extended horizon boundary): CI stayed green through that fix specifically because nothing in the pinned suite touches this code path at all, in either direction.

**What to improve**: Retrofit the pinned scenarios to compute their terminal value the same way production does (`_calculate_terminal_value`'s median-buy/sell-cap formula, applied to each scenario's own price data) instead of silently defaulting to zero, then re-pin each scenario's expected cost against the new baseline.

**Why not done as part of #345**: per the CHANGELOG history, changes to this exact mechanism have previously shifted "nearly every scenario's expected schedule" — retrofitting all 26 fixtures is a broad, independently risky change that conflates two different concerns ("is `_calculate_terminal_value`'s formula correct" vs. "does the DP correctly handle *some* nonzero terminal value") and shouldn't ride along with a narrow bug fix. #345/#347 instead added one new targeted pinned fixture for the extended-horizon mechanism specifically, without touching the other 26.

**Files**: `core/bess/tests/unit/test_scenarios.py`, `core/bess/dp_battery_algorithm.py:1313-1327` (`optimize_battery_schedule` signature/default), `core/bess/battery_system_manager.py` (`_calculate_terminal_value`)

---

## 🔧 **TECHNICAL DEBT**

### Consolidate HistoricalDataStore, PredictionSnapshotStore, and DailyViewStore

**Impact**: Low | **Effort**: Medium | **Dependencies**: `core/bess/historical_data_store.py`, `core/bess/prediction_snapshot.py`, `core/bess/daily_view_store.py`

**Description**: The Daily Savings History feature (issue #126, `docs/superpowers/specs/2026-07-09-daily-savings-history-design.md`) added a third `DailyView`/`PeriodData`-shaped store alongside the existing `HistoricalDataStore` (today-only, cleared nightly) and `PredictionSnapshotStore` (today-only, cleared nightly). All three persist overlapping period-level data with slightly different lifecycles. The new store deliberately kept its schema close to `DailyView`/`PeriodData` rather than inventing a divergent shape, specifically so this consolidation stays feasible later. No action taken now — noted for a future pass once the aggregate-savings feature has shipped and settled.

**Files**: `core/bess/historical_data_store.py`, `core/bess/prediction_snapshot.py`, `core/bess/daily_view_store.py`, `core/bess/battery_system_manager.py`

---

### Savings history: untested error paths and swallowed fetch failures

**Impact**: Low | **Effort**: Low | **Dependencies**: `backend/api.py`, `frontend/src/components/settings/SavingsHistorySection.tsx`

**Description**: Two related test/UX gaps from the Daily Savings History feature. First, none of the three new `/api/savings/*` routes in `backend/api.py` has a test exercising its failure path — all three share an identical try/except-to-500 wrapper with no coverage proving it actually returns a 500 on an underlying error. Second, `SavingsHistorySection` fetches disk usage with a bare `.catch(() => {})`, so a failed request silently renders a plausible-but-wrong "0 days recorded" instead of an error state, unlike `SavingsAggregateView`, which has proper loading/error handling for the same kind of fetch. Neither is architecturally significant, but both are cheap to close and worth picking up together.

**Files**: `backend/api.py`, `frontend/src/components/settings/SavingsHistorySection.tsx`

---


### Move inverter-specific logic out of BatterySystemManager

**Impact**: Low | **Effort**: Medium | **Dependencies**: `InverterController` base class

**Description**: `BatterySystemManager` contains platform-specific checks like `if self.inverter_platform == "solax": return` in `adjust_charging_power()`. This logic belongs in the inverter controller layer — each controller should implement (or no-op) methods via the `InverterController` interface, so `BatterySystemManager` never branches on platform strings.

**Examples**:

- `adjust_charging_power()` — no-op for SolaX, active for Growatt
- `grid_charge_enabled()` in `ha_api_controller.py` — not applicable to SolaX, logs a spurious WARNING

**Files**: `core/bess/battery_system_manager.py`, `core/bess/inverter_controller.py`, `core/bess/solax_controller.py`, `core/bess/ha_api_controller.py`

---


### Simplify Health Check Severity Model

**Impact**: Low | **Effort**: Low-Medium | **Dependencies**: `health_check.py`, `power_monitor.py`, all callers of `perform_health_check()`

**Description**: The current model has two independent knobs that are easy to misconfigure:

- `is_required` — marks the component as critical to the system (used only by the dashboard banner to set `has_critical_errors`)
- `required_methods` — controls whether a failing sensor inside the component shows ERROR vs WARNING on the component card

These concepts are orthogonal but interact in non-obvious ways. The correct mapping of `is_required` → severity was never enforced, which caused `Power Monitoring` (`is_required=False`) to show ERROR instead of WARNING because `required_methods=all_methods` was passed. Fixed by hand, but the underlying design is fragile.

**Proposed simplification**: Derive `required_methods` automatically from `is_required` instead of requiring callers to pass both:

- `is_required=True` → all methods are required → failure → ERROR
- `is_required=False` → no methods are required → failure → WARNING

This eliminates the `required_methods` parameter entirely and makes the policy self-consistent: optional components can never show ERROR, required components always show ERROR on failure.

**Files**: `core/bess/health_check.py`, `core/bess/power_monitor.py`, `core/bess/health_check.py` (all `perform_health_check()` call sites)

---

### Remove dead `min_action_profit_threshold` config

**Impact**: Low | **Effort**: Low | **Dependencies**: `settings.py`, `settings_store.py`

**Description**: `min_action_profit_threshold` was the configurable gate for the DP's old profit-threshold/all-IDLE-rejection mechanism. That mechanism was removed in the "Bellman-optimality guardrail removal" refactor (commit `ee24537f`/`f57d4fed`, `docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md`) — the current all-IDLE safety net (`core/bess/dp_battery_algorithm.py:1514-1536`) is a plain cost comparison that doesn't read this setting at all. The field is still declared in `core/bess/settings.py:127` and migrated in `backend/settings_store.py:389,480`, and likely still surfaced in the setup wizard/settings UI, but nothing consumes it anymore. Found while auditing `docs/agents/bess-knowledge.md` and `docs/SOFTWARE_DESIGN.md` for staleness (2026-07-19).

**What needs to change**:

- Remove `min_action_profit_threshold` from `BatterySettings` (`core/bess/settings.py`)
- Remove it from the settings-store schema/migration (`backend/settings_store.py`)
- Check the frontend (settings forms, setup wizard) for a corresponding field and remove it
- Verify no other code path reads it (grep before deleting)

**Files**: `core/bess/settings.py`, `backend/settings_store.py`, frontend settings components

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

**Impact**: Low | **Effort**: Low (45 min) | **Dependencies**: None

**Description**: Replace currency parameter passing with FormattingContext dataclass for better extensibility and i18n support.

**Current State**: Currency passed as string parameter through call chain

**Implementation**: Create frozen FormattingContext dataclass, update `create_formatted_value()` and dataclass `from_internal()` methods, modify API endpoints to create context from settings

**Benefits**: Type safety, extensibility for locale/timezone/precision without signature changes, future-proof for internationalization

**Files**: `backend/api_dataclasses.py`, `backend/api.py`

### ~~Hardcoded Fallback Values Violating CLAUDE.md~~ ✅ Completed (v8.2.1)

**Resolution**: All `hasattr` guards and hardcoded fallback values removed from `api.py`. System now accesses `battery_settings`, `controller`, `price_manager`, `_schedule_manager`, and `has_critical_sensor_failures` directly. Added `_get_intent_description()` to `SphScheduleManager` to eliminate polymorphism-related `hasattr`.

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
- `lifetime_load_consumption` — derived as `solar + import - export` when missing

These sensors remain in the per-platform suffix maps (`GROWATT_MIN_SUFFIX_MAP`, `GROWATT_SPH_SUFFIX_MAP`, etc.), get discovered, appear in the wizard sensor list, and are saved to config, but nothing reads them at runtime. Remove them from the suffix maps and `sensorDefinitions.ts` to reduce wizard clutter and avoid confusion about which sensors actually matter.

**Files**: `core/bess/ha_api_controller.py` (per-platform suffix maps), `frontend/src/lib/sensorDefinitions.ts`

---

### Clean up suffix map dead entries

**Impact**: Low | **Effort**: Low | **Dependencies**: `ha_api_controller.py`

**Description**: `GROWATT_MIN_SUFFIX_MAP` contains `battery_discharge_soc_limit_on_grid` which never matches any real `unique_id` suffix. The actual `growatt_server` unique_id for this entity uses the shorter suffix `soc_limit_on_grid` (added separately). Audit all per-platform suffix maps for other entries that exist only because they matched entity_id patterns but have no corresponding unique_id in any real integration. Discovery matches exclusively on `unique_id` via `_map_registry_entities`, so entity_id-shaped suffixes are dead code.

**Files**: `core/bess/ha_api_controller.py` (per-platform suffix maps)

---

### Consolidate Growatt MIN/SPH detection into a single path

**Impact**: Low | **Effort**: Low | **Dependencies**: `ha_api_controller.py`

**Description**: There are two separate heuristics for distinguishing Growatt MIN vs SPH:
1. `_parse_ha_metadata()` (line ~2163): binary check for `-tlx_` in any unique_id
2. `discover_sensors_from_registry()` (line ~2725): runs both suffix maps and picks the one with more matches

Both are called sequentially from `run_setup_discovery()` in `api.py`. They serve different stages (platform identification vs sensor mapping), but having two heuristics for the same question is fragile — they could theoretically disagree. Consolidate by deriving the platform list from the suffix map match results instead of the separate `has_tlx` check.

**Files**: `core/bess/ha_api_controller.py` (`_parse_ha_metadata`, `discover_sensors_from_registry`), `backend/api.py` (`run_setup_discovery`)

### Remove device_id discovery fallbacks and dead `device_sn` code

**Impact**: Low | **Effort**: Low | **Dependencies**: `ha_api_controller.py`, `api.py`, `sensorDefinitions.ts`

**Description**: Device ID discovery has two strategies: config_entry match (primary, always works) and identifiers/SN match (fallback). The fallback depends on `_extract_growatt_device_sn()`, which fragily parses SOC entity IDs to extract the serial number. Real HA devices always have `config_entries` on the device object, so the fallback is unnecessary.

Additionally, `device_sn` is extracted, returned in the API response as `deviceSn`, and declared in the frontend `DiscoveryResult` type — but nothing in the frontend or backend ever reads it. It's dead code end to end.

**What to remove**:
- `_extract_growatt_device_sn()` method
- Identifiers-based device_id fallback (strategy 2 in `_parse_ha_metadata`)
- `device_sn` from discovery result dict and API response
- `deviceSn` from frontend `DiscoveryResult` type

**Files**: `core/bess/ha_api_controller.py`, `backend/api.py`, `frontend/src/components/settings/SensorConfigSection.tsx`

---

### Other Technical Debt

- Refactor all API endpoints to use dataclass-based serialization (with robust mapping for all field variants) for consistent, type-safe, and future-proof API responses. Ensure all details and fields are preserved as in the original dict-based implementation.
- Check if all sensors in config.yaml are actually needed and used (lifetime e.g.)

**From #221 (spot_multiplier/export_spot_multiplier) code review — deferred cleanup, not bugs**:

- `backend/api.py`'s `_pricing_defaults_for_discovery()` duplicates the provider-priority chain (`octopus > entsoe > nordpool_official > nordpool_hacs`, gated on `not nordpool_found`) already computed independently in `frontend/src/pages/SetupWizardPage.tsx`'s `autoProvider` logic. The two can drift out of sync if the priority order changes in only one place. Consider deriving both from a single shared source (e.g. have the backend return the resolved provider and have the frontend just consume it, instead of recomputing it).
- `backend/api_conversion.py`'s `PRICE_STORE_TO_API` (startup/read path) and `backend/api.py`'s `_PRICE_MAP` in `setup_complete()` (wizard-write path) are two independently-maintained camelCase↔snake_case tables for the same `PriceSettings` fields. The new `TestPriceModelAttrsConsistency` contract test (added in #221) only guards `PRICE_STORE_TO_API` — `_PRICE_MAP` can still silently drift for a future field with no test to catch it. Consider consolidating to one table, or extending the contract test to also cover `_PRICE_MAP`.
- `backend/settings_store.py`'s `_migrate_schema()` electricity_price migration block hardcodes `spot_multiplier`/`export_spot_multiplier`/`use_actual_price` by name instead of iterating `PRICE_STORE_TO_API` + `PriceSettings` defaults generically. Every future `PriceSettings` field will need a new hand-written migration block, and it's easy to forget (silent `ValueError` in `build_system_settings()` at startup for existing users' configs). Consider making the migration generic against `PRICE_STORE_TO_API`.

**TOU Segment Matching is Fragile**:
The current TOU comparison uses exact matching on start_time, end_time, batt_mode. If a segment shifts by 15 minutes (e.g., 00:00-00:59 → 00:15-01:14), it's seen as completely different, resulting in 2 hardware writes (disable old + add new) instead of 1 update. Consider:

- Overlap-based matching: If segments overlap significantly and have same mode, treat as "same"
- Smart merging: Detect when segments can be extended/shortened rather than replaced

**Remove Hourly Aggregation Legacy**:
With 15-min TOU resolution implemented, the hourly aggregation code is now legacy. Power rates are already set per-period in `_apply_period_settings()`. The following should be refactored or removed:

- `_calculate_hourly_settings_with_strategic_intents()` - aggregates 15-min periods back to hourly
- `get_hourly_settings()` - returns hourly settings (used by power monitor and display)
- `_get_hourly_intent()` - majority voting for hourly intent (no longer needed for TOU)
- `hourly_settings` dict - stores the aggregated hourly data

To remove:

1. Update `adjust_charging_power()` in `battery_system_manager.py` to use period-based settings
2. Update schedule display table to show 15-min periods (or keep hourly summary for readability)
3. Update `get_strategic_intent_summary()` to work directly with periods
4. Remove the hourly aggregation methods listed above

**Re-run optimization on energy prediction method change**:
When the user changes the consumption strategy (e.g. from `sensor` to `fixed`), the optimization should re-run immediately with the new prediction method rather than waiting for the next scheduled cycle. The prediction cache should be cleared and a fresh optimization triggered in the same request that saves the new strategy.

**Sensor Collector InfluxDB Usage**:
Based on the code analysis: The function `_get_hour_readings` in SensorCollector is called by `collect_energy_data(hour)`. This is not called every hour automatically by the system; it is called when the system wants to collect and record data for a specific hour. The actual historical data for the dashboard is served from the HistoricalDataStore, which is an in-memory store populated by calls to `record_energy_data` (which uses the output of `collect_energy_data`).

## From #215 health-recovery-banner code review (non-blocking, low severity)

**Concurrent health-check race could double-record a recovery**:
`BatterySystemManager._run_health_check` reads `_cached_health_results` as `previous_results`, then later overwrites it and calls `_update_health_recoveries(previous_results, health_results)` — none of this is lock-protected. If the 5-minute cron job and a manual "Recheck now" click ever overlap almost exactly, both could read the same stale `previous_results` and each record a recovery for the same real transition, leaving a duplicate entry in the banner until acknowledged. Narrow timing window, not observed in practice; would need the tracker's own lock extended around the read-modify-write in `_run_health_check` to close it.

**Component disappearing from health checks leaves a stale pending recovery**:
`_update_health_recoveries` (core/bess/battery_system_manager.py) only visits components present in the *new* checks list. If a component goes ERROR then becomes unconfigured/absent (e.g. an optional check dropped by a settings change) before recovering, `clear_for_component` never runs for it and any stale pending recovery for that name lingers until acknowledged or evicted by the 50-entry cap. Edge case, low impact.

**`/api/health-recoveries` uses camelCase (`convert_keys_to_camel_case`) while sibling `/api/runtime-failures` returns raw snake_case `__dict__`**:
Both are valid given each has its own matching frontend hook, but it's an inconsistent precedent for the next tracker-style endpoint someone adds. Worth standardizing next time either is touched.

The `_get_hour_readings` (and thus the InfluxDB query) is called at startup (to reconstruct history) and whenever a new hour is completed and needs to be recorded. It is not called every hour by a scheduler, but it is called for each hour that needs to be reconstructed or recorded.

## From #271 charge-power-rate fix code review (non-blocking, nice-to-have)

**`InverterStatusDashboard.tsx`'s `batterySettings` state is now write-only**: after switching the "Charge Power Rate" tile to read `inverterStatus?.chargePowerRate` instead of `batterySettings?.chargingPowerRate`, nothing in the component reads `batterySettings` anymore — only `setBatterySettings` (from `fetchBatterySettings()`) is called. Left as-is deliberately to keep the fix minimal. Worth a follow-up to either remove the now-dead `fetchBatterySettings()` call/state or confirm another consumer still needs it.

**File**: `frontend/src/components/InverterStatusDashboard.tsx`

---

## From #249 net-grid-cost-savings-redesign whole-branch review (non-blocking, low severity)

**Stale comment in `BatteryActionsTable.tsx:91`**: `// Use backend-calculated summary data instead of frontend calculations` was the header of the now-deleted Summary Cards block; it now floats above the `finalHour` declaration with nothing to describe. Harmless, mildly misleading.

**`BatteryActionsTable.tsx` TOTAL footer row shows Actual Cost as the wear-inclusive total with no "of which wear" sub-line**, while every per-period row above it now carries that breakdown. Consistent with "table content otherwise unchanged" but the totals row is the one place the per-column wear breakdown silently drops. Purely cosmetic.

**`SavingsPage.test.tsx` doesn't assert DOM order** of `SavingsAggregateView` vs `DetailedSavingsAnalysis`, even though their reorder was the one functional change in that task. Cosmetic reorder, not a regression risk worth a merge block, but a `compareDocumentPosition` assertion would close the gap cheaply if this file is touched again.

**`today_view` is built unconditionally for `period=day`** in `backend/api.py` even when today is already persisted (post-rollover) or `count>1`, cases where `build_buckets` ignores it. One wasted `daily_view_builder.build_daily_view()` call per request; negligible cost.

---

## From #317 period-group intent reconciliation code review (non-blocking)

**`backend/api.py`'s new `today_reconciled_intents` build has two silent fallbacks** (`planned_intent` defaults to `"IDLE"` when `period_idx >= len(planned_intents)`, and out-of-range periods also append `planned_intent`) that follow the existing `INTENT_TO_MODE.get(intent, "load_first")` convention in `inverter_controller.py`, but technically fall under `docs/agents/rules.md`'s "Explicit failure over silent degradation" rule. Low risk since it's a display-only path, not a control path, and the pattern is already pervasive in this file — not filed as a blocker.

**Behavior change on cold start**: previously, if `schedule_manager.strategic_intents` was empty (e.g. right after startup, before the controller applies a schedule) but `schedule_store.get_latest_schedule()` already had a stored schedule, `get_detailed_period_groups()` returned `[]` outright (its `if not effective_intents: return []` early exit). Now the endpoint always builds a full per-period `today_reconciled_intents` list (defaulting missing planned entries to `"IDLE"`), so period_groups will render partial data (actual periods reconciled, future periods shown as `"IDLE"`) in that window instead of nothing. This looks like an improvement in line with the issue's intent (show what's real, not what's stale) but is a user-visible behavior change worth knowing about if it's ever reported as "showing IDLE for periods with no plan yet."

**Files**: `backend/api.py` (`get_growatt_detailed_schedule`, ~lines 1719-1758)

---

## From #233 SOE-floor-clamp fix code review (non-blocking, pre-existing)

**`_idle_battery_flows`'s below-floor guard now zeroes real energy, not just floor artefacts** — filed as [#295](https://github.com/johanzander/bess-manager/issues/295).

**`_interpolate_value`'s index clamp flattens continuation value below the SOE floor**: `V`'s grid (`soe_levels`) starts exactly at `min_soe_kwh`, so any `next_soe` below the floor clamps to `V_row[0]` regardless of how far below floor it is — candidates ending at different below-floor SoEs get identical continuation credit. Bounded in practice (discharge is already excluded below floor, and `next_soe` is monotonically non-decreasing once below floor) — not filed as an issue, just worth a comment in `_interpolate_value` noting the approximation if this file is touched again.

---

## From #353 immediate_value/future_value investigation (non-blocking)

**`DecisionData.immediate_value` duplicates the live `EconomicData.grid_cost`/dashboard "Net Grid Cost" metric and should probably be removed.** Traced while building the debug-log visualization skill: `immediate_value = export_revenue - import_cost - battery_wear_cost` (`decision_intelligence.py:413`) is exactly `-(grid_cost + battery_wear_cost)`, where `grid_cost = import_cost - export_revenue` (`core/bess/models.py:232`) is the same figure already surfaced live as `netGridCost` (`backend/api.py:776-782` → `SystemStatusCard.tsx`'s headline tile). The only difference is a sign flip and whether wear cost is netted in — and neither `immediate_value` nor `future_value` (nor the `economic_chain` narrative string, nor `/api/decision-intelligence`) is reachable anywhere in the live app: `frontend/src/components/DecisionFramework.tsx`, the only consumer that renders any of these fields, is never imported by any routed page in `App.tsx` — it's orphaned/dead code. `future_value` (fixed in #353 to no longer be always `0.0`) doesn't have this exact duplication problem — there's no live "value-to-go" KPI to compare against — but it's equally unreachable today.

**Suggestion**: remove `immediate_value` (and the `economic_chain` string's reliance on it) once a decision is made on `DecisionFramework.tsx`/`/api/decision-intelligence` — either wire it up to the real app using `grid_cost`/`netSavings` terminology instead of re-deriving a redundant metric, or delete the dead path entirely. Not filed as its own issue since it's a design/scope decision, not a bug.
