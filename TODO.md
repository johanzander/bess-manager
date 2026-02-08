# Energy Management System Improvements - Prioritized Implementation Plan

## 🔴 **CRITICAL PRIORITY** (System Reliability)

### 0. **Fix Battery Discharge Power Control Bug**

**Impact**: High | **Effort**: Medium | **Dependencies**: Growatt inverter control

**Description**: Discharge power seems to always be 100% leading to higher export than intended during EXPORT_ARBITRAGE operations.

### 1. **Extended Horizon Optimization**

**Impact**: High | **Effort**: Medium | **Dependencies**: Price manager, DP algorithm

**Description**: Use tomorrow's electricity prices to extend optimization beyond 24 hours, enabling better arbitrage decisions across day boundaries.

**Implementation**:

- Modify OptimizationManager to fetch tomorrow's prices when available (usually after 13:00)
- Extend DP algorithm input to handle 48+ hour horizons
- Update ViewBuilder to display extended optimization results
- Add multi-day TOU schedule management

**Economic Impact**: Significant - enables optimal charging/discharging decisions that span multiple days

## 🟡 **HIGH PRIORITY** (Core Functionality)

### 1. **Improve Battery SOC and Actions Component**

**Impact**: Medium-High | **Effort**: High | **Dependencies**: Backend cost calculations

**Description**: Core feature enhancement showing detailed battery optimization reasoning

**Current State**: `BatteryLevelChart` shows basic SOC but lacks prediction breakdown

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

### 5. **Enhance Insights Page with Decision Detail**

**Impact**: Medium | **Effort**: High | **Dependencies**: Backend decision logging

**Current State**: Only shows high-level intent, lacks decision reasoning

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

### 9. Add multi day view

**Problem**: Today we only operate on 24h intervals.
But at noon every day we get tomorrows schedule. We could use this information to take better economic decisions. It would mean changing a lot of places where 24h is hard coded.

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

## 🔧 **TECHNICAL DEBT**

### FormattingContext Architecture

**Impact**: Low | **Effort**: Low (45 min) | **Dependencies**: None

**Description**: Replace currency parameter passing with FormattingContext dataclass for better extensibility and i18n support.

**Current State**: Currency passed as string parameter through call chain

**Implementation**: Create frozen FormattingContext dataclass, update `create_formatted_value()` and dataclass `from_internal()` methods, modify API endpoints to create context from settings

**Benefits**: Type safety, extensibility for locale/timezone/precision without signature changes, future-proof for internationalization

**Files**: `backend/api_dataclasses.py`, `backend/api.py`

### Other Technical Debt

- Refactor all API endpoints to use dataclass-based serialization (with robust mapping for all field variants) for consistent, type-safe, and future-proof API responses. Ensure all details and fields are preserved as in the original dict-based implementation.
- Add power monitoring sensors to health check.
- Check if all sensors in config.yaml are actually needed and used (lifetime e.g.)
- Fix dark mode button

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

**Sensor Collector InfluxDB Usage**:
Based on the code analysis: The function `_get_hour_readings` in SensorCollector is called by `collect_energy_data(hour)`. This is not called every hour automatically by the system; it is called when the system wants to collect and record data for a specific hour. The actual historical data for the dashboard is served from the HistoricalDataStore, which is an in-memory store populated by calls to `record_energy_data` (which uses the output of `collect_energy_data`).

The `_get_hour_readings` (and thus the InfluxDB query) is called at startup (to reconstruct history) and whenever a new hour is completed and needs to be recorded. It is not called every hour by a scheduler, but it is called for each hour that needs to be reconstructed or recorded.
