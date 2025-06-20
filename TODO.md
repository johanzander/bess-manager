# Energy Management System Improvements - Prioritized Implementation Plan



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

**Why Fourth**: Essential for system monitoring and debugging, affects operational reliability

**Current State**: SystemHealthPage has rendering/functionality issues (needs investigation)

**Technical Tasks**:
- Debug SystemHealthPage component errors
- Fix data fetching and error handling
- Update health status indicators  
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

### 13 Intent is not always correct for historical data. 

**Current State**: The inverter sometimes charges/discharges small amounts like 0.1kW. Or its a rounding error or inefficiencies losses when calculating flows. I don't think its a strategic intent, but it is interpreted as one.

### 14 Add multi day view.

*** Problem ***: Today we only operate on 24h intervals.
But at noon every day we get tomorrows schedule. We could use this information to take better economic decisions. It would mean changing a lot of places where 24h is hard coded.


### 15 Consolidate HourlyData and HourlyEvent

Why cant they be the same?

