# Energy Management System Improvements - Prioritized Implementation Plan

## 🔴 **CRITICAL PRIORITY** (Foundation & Reliability)

### 1. **Remove duplicate and legacy keys in API endpoints** 
**Impact**: High | **Effort**: Medium | **Dependencies**: Affects all frontend components

**Current State**: legacy keys are used, duplicate, camelCase and snake_case mixed

**Technical Tasks**: Use canonical form for each key

---

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

### 3. **Restructure ConsolidatedEnergyCards to Pure Energy Flow Cards**
**Impact**: High | **Effort**: High | **Dependencies**: Dashboard UX foundation

**Why Third**: Major UX improvement affecting primary user interface, enables better data organization

**Current State**: Single component mixing energy flows with status information, inconsistent direction indicators

**Implementation**:
- **Split into 2 components**:
  - `EnergyFlowCards.tsx` (5 cards): Solar, Consumption, Grid, Battery, Balance
  - `SystemStatusCard.tsx`: Cost savings, Battery status, System health
- **Standardize direction indicators**: All cards use consistent "To/From" format
- **Pure energy focus**: Remove cost/status data from energy cards
- **Fix endpoints**: Battery Card does not show SOC as this is not present in dashboard endpoint, but inverter_status. SystemStatusCard shall use /api/inverter_status, energyFlowCards shall not.

**Technical Tasks**:
- Extract energy flow logic into separate component
- Create new status card component
- Update `DashboardPage.tsx` layout
- Ensure consistent "To/From" labeling and icons

---

## 🟡 **HIGH PRIORITY** (Core Functionality)

### 4. **Fix System Health Page**
**Impact**: Medium-High | **Effort**: Medium | **Dependencies**: System monitoring

**Why Fourth**: Essential for system monitoring and debugging, affects operational reliability

**Current State**: SystemHealthPage has rendering/functionality issues (needs investigation)

**Technical Tasks**:
- Debug SystemHealthPage component errors
- Fix data fetching and error handling
- Update health status indicators  
- Ensure dark mode compatibility
- Test all monitoring features

---

### 5. **Improve Battery SOC and Actions Component**
**Impact**: Medium-High | **Effort**: High | **Dependencies**: Backend cost calculations

**Why Fifth**: Core feature enhancement showing detailed battery optimization reasoning

**Current State**: `BatteryLevelChart` shows basic SOC but lacks prediction breakdown

**Implementation**:
- **Add actual/predicted timeline split** with visual distinction
- **Add detailed cost breakdown table**:
  ```
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

## 🟠 **MEDIUM PRIORITY** (User Experience)

### 6. **Make Dark Mode Work in All Views**
**Impact**: Medium | **Effort**: Medium | **Dependencies**: UI consistency

**Current State**: Dark mode works in main areas but inconsistencies exist

**Technical Tasks**:
- Audit all components for missing `dark:` classes
- Update chart color schemes (EnergyFlowChart, BatteryLevelChart)
- Fix SystemHealthPage, InverterPage, InsightsPage dark mode
- Test all interactive elements in dark theme

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
- Implement proper dark mode support
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

### 10. **Fix DetailedSavingsAnalysis Yellow Card**
**Impact**: Low | **Effort**: Low | **Dependencies**: None

**Current State**: Yellow card shows "Solar energy" instead of cost/savings to align with other cards

**Technical Tasks**:
- Change from "Solar Energy Generated" to "Solar Savings & Costs"
- Update metrics from energy (kWh) to financial (SEK)
- Include: Self-consumption savings, Export earnings, Solar ROI

---

### 11. **Move and consolidate all types and data fetching in frontend**

**Current State**: Each component fetches it's own data, while there is basically only one endpoint (/api/dashboard). Could we centralize this to make cleaner code. Also there is an energy endpoint we've removed where we are still recreating the old data structures - this could be removed. 

### 12. Add Prediction accuracy and history

### 13 Intent is not always correct for historical data. 

**Current State**: The inverter sometimes charges/discharges small amounts like 0.1kW. Or its a rounding error or inefficiencies losses when calculating flows. I don't think its a strategic intent, but it is interpreted as one.

