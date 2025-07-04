# Battery Energy Storage System (BESS) - Updated Design

## 1. System Overview

The updated Battery Energy Storage System manages a home battery installation with a simplified, event-driven architecture that eliminates temporal state management complexity. The system provides optimal battery scheduling while maintaining clear separation between historical facts and future predictions.

**Key Design Principles:**

- **Event Sourcing**: Historical data is immutable
- **Pure Functions**: Optimization has no side effects
- **Clear Separation**: What happened vs what should happen
- **Simple API**: Three methods for three scenarios

## 2. Updated System Architecture

```text
┌───────────────────────────────────────────────────────────────┐
│                    SimpleBatterySystemManager                 │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐  │
│  │create_tomorrows │ │update_hourly    │ │restart_and      │  │
│  │_schedule()      │ │_schedule()      │ │_reconstruct()   │  │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘  │
└───────────────────────────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Historical    │    │ ScheduleStore   │    │ DailyView       │
│ DataStore     │    │                 │    │ Builder         │
│               │    │ - Stores every  │    │                 │
│ - Immutable   │    │   optimization  │    │ - Combines      │
│   hourly      │    │   result        │    │   actuals +     │
│   events      │    │ - Raw algorithm │    │   predictions   │
│ - What really │    │   outputs       │    │ - Recalculates  │
│   happened    │    │ - Timestamped   │    │   total savings │
└───────────────┘    └─────────────────┘    └─────────────────┘
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                │
                                ▼
                    ┌─────────────────┐
                    │ Optimization    │
                    │ Engine          │
                    │                 │
                    │ - Pure function │
                    │ - Uses existing │
                    │   DP algorithm  │
                    │ - No side       │
                    │   effects       │
                    └─────────────────┘
                                │
                                ▼
                    ┌─────────────────┐
                    │ Home Assistant  │
                    │ Controller      │
                    │                 │
                    │ - Hardware      │
                    │   interface     │
                    │ - Real-time     │
                    │   readings      │
                    └─────────────────┘
```markdown

## 3. Core Components

### 3.1 SimpleBatterySystemManager

**Purpose:** Main facade with three simple methods for three scenarios.

**Key Methods:**

```python
def create_tomorrows_schedule() -> OptimizationResult
def update_hourly_schedule(completed_hour: int) -> OptimizationResult
def restart_and_reconstruct(current_hour: int) -> OptimizationResult
```

**Responsibilities:**

- Coordinate the three main scenarios
- Apply schedules to hardware
- Maintain current active schedule

### 3.2 HistoricalDataStore

**Purpose:** Immutable storage of what actually happened.

**Key Data Structure:**

```python
@dataclass(frozen=True)
class HourlyEvent:
    hour: int
    timestamp: datetime
    battery_soc_start: float
    battery_soc_end: float
    solar_generated: float
    home_consumed: float
    grid_imported: float
    grid_exported: float
    battery_charged: float
    battery_discharged: float
```

**Key Methods:**

```python
def get_completed_hours() -> List[int]
def get_hour_event(hour: int) -> Optional[HourlyEvent]
```

### 3.3 ScheduleStore

**Purpose:** Store every optimization result throughout the day.

**Storage Format:**

```python
@dataclass
class StoredSchedule:
    timestamp: datetime
    optimization_hour: int  # Hour optimization started from
    algorithm_result: dict  # Raw result from optimize_battery_schedule()
    created_for_scenario: str  # "tomorrow", "hourly", "restart"
```

**Key Methods:**

```python
def store_schedule(schedule: StoredSchedule) -> None
def get_latest_schedule() -> Optional[StoredSchedule]
def get_schedule_at_time(timestamp: datetime) -> Optional[StoredSchedule]
def get_all_schedules_today() -> List[StoredSchedule]
```

### 3.4 DailyViewBuilder

**Purpose:** Always provide complete 00-23 view combining actuals + predictions.

**Key Method:**

```python
def build_daily_view(current_hour: int) -> DailyView
```

**Output Format:**

```python
@dataclass
class DailyView:
    hourly_data: List[HourlyData]  # 24 hours always
    total_savings: float           # Recalculated from combined data
    actual_hours: int              # How many hours are actual vs predicted
    data_sources: List[str]        # ["actual", "actual", "predicted", ...]
```

### 3.5 OptimizationEngine

**Purpose:** Pure wrapper around existing DP algorithm.

**Key Method:**

```python
def optimize(inputs: OptimizationInput) -> OptimizationResult
```

## 4. Replaced/Simplified Components

### 4.1 EnergyManager (Significantly Simplified)

**Old Responsibilities:**

- ❌ Historical data management (moved to HistoricalDataStore)
- ❌ Complex state tracking (eliminated)
- ❌ Data reconstruction (simplified)
- ❌ Energy balance validation (simplified)

**New Responsibilities:**

- ✅ Collect real-time sensor data
- ✅ Provide consumption/solar predictions
- ✅ Simple data fetching interface

### 4.2 Schedule Classes (Eliminated)

- **DPSchedule**: Replaced by raw algorithm results in ScheduleStore
- **Complex merging logic**: Replaced by DailyViewBuilder

### 4.3 BatterySystemManager (Dramatically Simplified)

**Old:** 200+ line methods with complex state management
**New:** Simple coordination between components

## 5. Data Flow for Three Scenarios

### 5.1 Scenario 1: Create Tomorrow's Schedule (23:55)

```bash
1. Get tomorrow's price/consumption/solar predictions
2. Assume battery at min SOC
3. Optimize full day (0-23)
4. Store result in ScheduleStore
5. Apply to hardware (TOU intervals)
```

### 5.2 Scenario 2: Hourly Updates (Every hour)

```bash
1. Record completed hour → HistoricalDataStore
2. Get current battery state (real-time reading)
3. Optimize remaining hours (current_hour to 23)
4. Store result in ScheduleStore
5. Apply current hour settings to hardware
```

### 5.3 Scenario 3: System Restart (Anytime)

```bash
1. Reconstruct historical events from available data
2. Get current battery state (real-time reading)
3. Optimize remaining hours
4. Store result in ScheduleStore
5. Apply to hardware
```

## 6. Daily View Generation (For UI/API)

```bash
DailyViewBuilder.build_daily_view(current_hour=15):
1. Get hours 0-14 actual data from HistoricalDataStore
2. Get hours 15-23 predicted data from latest ScheduleStore entry
3. Combine into 24-hour view
4. Recalculate total daily savings from combined hourly data
5. Mark each hour as "actual" or "predicted"
6. Return complete DailyView
```

## 7. Key Benefits

### 7.1 Eliminated Complexity

- **No more temporal state merging**
- **No more complex reconstruction logic**
- **No more schedule versioning complexity**

### 7.2 Clear Responsibilities

- **HistoricalDataStore**: What happened (immutable)
- **ScheduleStore**: What was planned (versioned)
- **DailyViewBuilder**: Current complete view (derived)

### 7.3 Simple Testing

- Each component can be unit tested independently
- Pure functions with predictable inputs/outputs
- No complex interdependencies

### 7.4 UI/API Friendly

- DailyViewBuilder always returns complete 00-23 data
- Clear marking of actual vs predicted hours
- Total savings properly calculated from combined data

## 8. Implementation Plan

### Phase 1: Create New Components

1. `HistoricalDataStore` - immutable event storage
2. `ScheduleStore` - optimization result storage
3. `DailyViewBuilder` - hybrid view generation
4. `SimpleBatterySystemManager` - main coordinator

### Phase 2: Simplify Existing Components

1. Reduce `EnergyManager` to simple data fetching
2. Remove complex merging logic from `BatterySystemManager`
3. Replace schedule classes with raw algorithm results

### Phase 3: Integration & Migration

1. Run new system in parallel with old system
2. Validate results match
3. Switch over and remove old code

This design eliminates the fundamental complexity while providing all required functionality for daily savings reports and UI integration.
