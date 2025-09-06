# Energy Management System Improvements - Prioritized Implementation Plan

## 🔴 **CRITICAL PRIORITY** (System Reliability)

### 0. **Proper Exception Class Hierarchy**

**Impact**: High | **Effort**: Low | **Dependencies**: Core error handling patterns

**Description**: Replace string-based error catching with proper exception classes. Current error handling uses fragile ValueError string matching which breaks when error messages change.

**Implementation Steps**:

- Create `PriceDataUnavailableError`, `ScheduleNotFoundError`, `SystemConfigurationError` exception classes
- Update price manager and battery system manager to raise specific exceptions
- Update API layer to catch specific exception types instead of string matching
- Follow existing codebase patterns for exception handling

**Files to modify**:

- `core/bess/exceptions.py` (new file)
- `core/bess/price_manager.py`
- `core/bess/battery_system_manager.py`  
- `backend/api.py`

### 1. **Extended Horizon Optimization**

**Impact**: High | **Effort**: Medium | **Dependencies**: Price manager, DP algorithm

**Description**: Use tomorrow's electricity prices to extend optimization beyond 24 hours, enabling better arbitrage decisions across day boundaries.

**Implementation**:

- Modify OptimizationManager to fetch tomorrow's prices when available (usually after 13:00)
- Extend DP algorithm input to handle 48+ hour horizons
- Update ViewBuilder to display extended optimization results
- Add multi-day TOU schedule management

**Economic Impact**: Significant - enables optimal charging/discharging decisions that span multiple days

### 2. **Ensure No Code Uses Sensor Names Directly**

**Impact**: High | **Effort**: Medium | **Dependencies**: Core system reliability

**Why Second**: Critical technical debt - direct sensor usage creates fragile coupling, hard to maintain

**Current State**: Code may reference HA sensor entity IDs directly instead of abstraction layer

- Risk of system breakage when sensors change
- Hard to reconfigure without code changes

**Technical Tasks**:

- Audit all `.py` files for direct sensor name references (search for `sensor.` patterns)
- Ensure all access uses `ha_api_controller.get_sensor_value(sensor_name)`
- Update hardcoded entity IDs to use sensor configuration
- Add sensor validation and error handling
- Document sensor abstraction patterns

---

## 🟡 **HIGH PRIORITY** (Core Functionality)

### 4. **Fix System Health Page**

**Impact**: Medium-High | **Effort**: Medium | **Dependencies**: System monitoring

Review which should be required and optional
test that missing sensors actually works

---

### 5. **Improve Battery SOC and Actions Component**

**Impact**: Medium-High | **Effort**: High | **Dependencies**: Backend cost calculations

**Why Fifth**: Core feature enhancement showing detailed battery optimization reasoning

**Current State**: `BatteryLevelChart` shows basic SOC but lacks prediction breakdown

**Implementation**:

- **Add actual/predicted timeline split** with visual distinction
- **Add detailed cost breakdown table**:

```text
  Base case cost:     65.69 SEK (Actual: 27.06 + Predicted: 38.63)
  Grid cost:         -14.90 SEK (Actual: 28.13 + Predicted: -43.03)
  Battery wear cost:   9.89 SEK (Actual: 2.60 + Predicted: 7.29)
  Total savings:      80.59 SEK (Actual: -1.07 + Predicted: 81.67)
```text

**Technical Tasks**:

- Update `BatteryLevelChart.tsx` for actual/predicted split
- Create cost breakdown table component
- Add hover tooltips with detailed calculations
- Integrate with backend hourly cost data

---

### 7. **Move Relevant Parts of Daily Summary to Dashboard**

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

### 8. **Fix Inverter Page Visual Style**

**Impact**: Medium | **Effort**: Medium | **Dependencies**: UI consistency

**Current State**: InverterPage doesn't match dashboard visual design

**Technical Tasks**:

- Apply dashboard-style card layouts
- Use consistent color scheme and spacing
- Fix mobile responsiveness
- Match typography patterns

---

### 9. **Enhance Insights Page with Decision Detail**

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

## 🟢 **LOW PRIORITY** (Polish)

### 11. **Move and consolidate all types and data fetching in frontend**

**Current State**: Each component fetches it's own data, while there is basically only one endpoint (/api/dashboard). Could we centralize this to make cleaner code. Also there is an energy endpoint we've removed where we are still recreating the old data structures - this could be removed.

### 12. Add Prediction accuracy and history

### 13. Intent is not always correct for historical data

**Current State**: The inverter sometimes charges/discharges small amounts like 0.1kW. Or its a rounding error or inefficiencies losses when calculating flows. I don't think its a strategic intent, but it is interpreted as one.

### 14. Add multi day view

**Problem**: Today we only operate on 24h intervals.
But at noon every day we get tomorrows schedule. We could use this information to take better economic decisions. It would mean changing a lot of places where 24h is hard coded.

### 15. **Error/Warning Banner in Frontend**

**Impact**: Medium | **Effort**: Medium | **Dependencies**: Backend logging, Frontend UI

**Description**: Display recent system errors and warnings from logs as a banner in the frontend UI for better debugging visibility.

**Implementation**:

- Create `/api/system-status` endpoint that returns recent errors/warnings from logs
- Add log parsing to extract ERROR and WARNING level messages with timestamps
- Create dismissible banner component in frontend (similar to alert banners)
- Show critical issues like:
  - TOU interval ordering problems
  - Sensor communication failures  
  - Optimization errors
  - Hardware communication issues
- Auto-refresh banner every 30 seconds
- Allow manual refresh and dismissal
- Limit to last 10 errors/warnings from past 24 hours

**Benefits**: Users can immediately see system issues without checking HA logs, better debugging experience, proactive issue detection

## 🔄 **ARCHITECTURAL IMPROVEMENTS** (From Historical Design Analysis)

### 16. **Machine Learning Predictions**

**Impact**: Medium | **Effort**: High | **Dependencies**: Historical data, ML framework

**Description**: ML-based consumption and solar predictions to improve optimization accuracy beyond current HA sensor forecasts.

**Implementation**:

- Integrate with existing PredictionProvider framework
- Historical data analysis for pattern recognition (weather, season, usage patterns)
- Adaptive prediction models with confidence scoring
- Accuracy tracking and model performance metrics

### 17. **Grid Export Optimization**

**Impact**: Medium | **Effort**: Medium | **Dependencies**: DP algorithm extension

**Description**: Optimize battery discharge for grid export during high-price periods, not just home consumption.

**Implementation**:

- Extend DP algorithm to consider export revenues in addition to consumption savings
- Dynamic export/local consumption decision making
- Integration with grid feed-in tariff structures
- Export power limit and grid connection constraints

### 18. **Advanced Economic Modeling**

**Impact**: Low-Medium | **Effort**: High | **Dependencies**: Battery degradation data

**Description**: More sophisticated economic models including battery degradation curves and efficiency modeling.

**Implementation**:

- Battery degradation modeling based on usage patterns (cycle depth, temperature, age)
- Efficiency curve modeling for charge/discharge losses at different power levels
- Time-of-use optimization for battery longevity vs immediate profit
- Long-term ROI calculations including replacement costs

### 19. **Performance Monitoring and Metrics**

**Impact**: Medium | **Effort**: Medium | **Dependencies**: Analytics framework

**Description**: Comprehensive performance tracking for optimization effectiveness and system reliability.

**Implementation**:

- Optimization accuracy tracking (predicted vs actual savings)
- Battery performance degradation monitoring
- Energy balance validation metrics and alerts
- Component timing and performance metrics collection
- Automated reporting and alerting for anomalies

### 20. **Advanced Input Validation**

**Impact**: Medium | **Effort**: Low-Medium | **Dependencies**: Settings framework

**Description**: Comprehensive validation for all user settings preventing invalid configurations.

**Implementation**:

- Enhanced settings.py validation methods with clear error messages
- Real-time validation feedback in UI with specific guidance
- Configuration export/import with validation
- Dependency validation (e.g., min_soc < max_soc, power limits realistic)

### 21. **Data Export and Analysis Tools**

**Impact**: Low | **Effort**: Medium | **Dependencies**: Data stores

**Description**: Export capabilities for external analysis and system backup.

**Implementation**:

- JSON/CSV export of historical energy data and optimization decisions
- Configuration backup/restore functionality
- Optimization decision logs with reasoning export
- Integration with external analytics tools (Grafana, etc.)

### 15. Consolidate HourlyData and HourlyEvent

Why cant they be the same?

---

## 🔧 **TECHNICAL DEBT**

### Consolidate Energy Flow Calculation Implementations

**Impact**: Medium | **Effort**: Medium | **Dependencies**: Core energy calculations

**Current Problem**: Multiple duplicate energy flow calculation implementations scattered across codebase:
- `EnergyFlowCalculator` - Sensor-based historical flows from cumulative readings  
- `dp_battery_algorithm.calculate_energy_flows()` - Power-based flows for optimization
- `models.EnergyData.__post_init__()` - Auto-calculation of detailed flows
- Unused `EnergyFlowCalculator` instance in `battery_system_manager.py`

**Proposed Solution**: Single unified architecture with:
- `EnergyFlowCore` - Pure calculation functions (testable, no dependencies)
- `HistoricalFlowCalculator` - Adapter for sensor-based calculations
- `OptimizationFlowCalculator` - Adapter for power-based calculations  
- Shared validation and derivation logic
- Clear separation of concerns

**Benefits**: Single source of truth, easier testing, consistent validation, reduced maintenance

**Technical Tasks**:
- Create `EnergyFlowCore` with pure calculation functions
- Refactor `SensorCollector` to use `HistoricalFlowCalculator`  
- Replace `dp_battery_algorithm.calculate_energy_flows()` with `OptimizationFlowCalculator`
- Simplify `EnergyData.__post_init__()` to use core
- Remove unused instances and dead code

---

### Other Technical Debt

- Refactor all API endpoints to use dataclass-based serialization (with robust mapping for all field variants) for consistent, type-safe, and future-proof API responses. Ensure all details and fields are preserved as in the original dict-based implementation.
- Add power monitoring sensors to health check.
- Check if all sensors in config.yaml are actually needed and used (lifetime e.g.)
- Fix dark mode button

## 📝 **IMPLEMENTATION NOTES**

**Sensor Collector InfluxDB Usage**:
Based on the code analysis: The function `_get_hour_readings` in SensorCollector is called by `collect_energy_data(hour)`. This is not called every hour automatically by the system; it is called when the system wants to collect and record data for a specific hour. The actual historical data for the dashboard is served from the HistoricalDataStore, which is an in-memory store populated by calls to `record_energy_data` (which uses the output of `collect_energy_data`).

The `_get_hour_readings` (and thus the InfluxDB query) is called at startup (to reconstruct history) and whenever a new hour is completed and needs to be recorded. It is not called every hour by a scheduler, but it is called for each hour that needs to be reconstructed or recorded.
