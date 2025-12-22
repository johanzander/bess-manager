# Quarterly-Simple Design - Final Architecture

**Status:** APPROVED - Ready for Implementation
**Branch:** `feature/quarterly-simple`
**Date:** 2025-11-15

---

## Important: Code Examples vs. Implementation

**This document contains two types of code:**

1. **ACTUAL Implementation** - marked clearly, uses existing methods, must be implemented exactly
   - Example: `get_available_prices()` in PriceManager (new method using existing `get_buy_prices()`)
2. **EXAMPLE/Conceptual** - marked clearly, illustrates patterns, exact method names TBD
   - Example: BatterySystemManager showing array slicing pattern

**During implementation:** Always check existing code for actual method names and signatures. Examples show the *pattern*, not necessarily the exact API.

---

## Core Data Types

### period_index
**Type:** `int`
**Represents:** The quarterly period index relative to today's 00:00.

**Range:**
- 0-95: Today (normal day)
- 0-91: Today (DST spring, 23 hours)
- 0-99: Today (DST fall, 25 hours)
- 96-191: Tomorrow (if available)

**Mapping:**
- 0 = today 00:00-00:15
- 56 = today 14:00-14:15
- 95 = today 23:45-00:00
- 96 = tomorrow 00:00-00:15
- 191 = tomorrow 23:45-00:00

**Key Principle: All Arrays Start at Index 0 = Today 00:00**

This is the fundamental design principle:
- Prices array: `prices[0]` = today 00:00, `prices[96]` = tomorrow 00:00
- Solar array: `solar[0]` = today 00:00, `solar[96]` = tomorrow 00:00
- Consumption array: `consumption[0]` = today 00:00
- Storage: `store.record_period(56, data)` = today 14:00

**Slicing:** When optimizing at 14:00 (period 56):
- Current period: `current = get_current_period_index()` = 56
- Slice all arrays: `prices[current:]`, `solar[current:]`, etc.
- Optimize from current period onward
- Store results: `record_period(current + i, result[i])`

### timestamp
**Type:** `datetime.datetime` (timezone-aware)
**Represents:** A specific point in time with date, time, and timezone.
**Example:** `datetime(2025, 11, 15, 14, 30, tzinfo=ZoneInfo('Europe/Stockholm'))`
**Usage:** External boundaries only (sensor input, API output)

**Conversion:**
- Input: `timestamp_to_period_index(dt)` → continuous int from today 00:00
- Output: `period_index_to_timestamp(index)` → timestamp for debugging

---

## Core Principles

### 1. Quarterly-First, No Exceptions

**Internal resolution is ALWAYS quarterly (15-minute intervals). Not configurable.**

- Storage: Always 96 periods/day (92-100 for DST)
- Optimization: Always runs on quarterly data
- Calculations: All arrays are quarterly
- No "resolution" parameter anywhere internal

### 2. Arrays Over Timestamps

**Core components work with arrays indexed from today's 00:00.**

- **All arrays start at index 0 = today 00:00**: Prices, solar, consumption, storage
- **Consistent slicing**: At 14:00, slice all arrays from `current_period:` (e.g., `[56:]`)
- **Simple storage**: `record_period(index, data)` where index is continuous from 00:00
- **Timestamps**: Only at boundaries (sensor input, API output)
  - Input: `timestamp_to_period_index()` → continuous index from 00:00
  - Output: `period_index_to_timestamp()` → timestamp for display
  - Internal: Pure integer array indices

### 3. No Metadata, Just Indices

**Period indices are self-sufficient. No metadata needed.**

- NOT full timestamp generation
- NOT date tracking in storage
- JUST simple integer indices: 0-95 = today, 96+ = tomorrow

### 4. Clean Separation of Concerns

**Each layer has a single, clear responsibility.**

```
Input Layer:    Upsample hourly → quarterly
                ↓
Core Layer:     Pure array operations (quarterly)
                ↓
Storage Layer:  Array indices ↔ (date, period_index)
                ↓
Output Layer:   Aggregate quarterly → hourly (if requested)
```

---

## Architecture Components

### Component 1: Time Utilities (New)

**File:** `core/bess/time_utils.py` (~80 lines)

**Purpose:** Convert between timestamps and quarterly period indices. Handle DST.

**Interface:**
```python
# Constants
TIMEZONE = ZoneInfo("Europe/Stockholm")
INTERVAL_MINUTES = 15  # Hardcoded quarterly

# Functions
def get_period_count(target_date: date) -> int:
    """Number of quarterly periods in a day (92-100 for DST)."""

def timestamp_to_period_index(dt: datetime) -> int:
    """Convert timestamp to continuous period index from today's 00:00.

    Returns:
        Continuous index where:
        - Today 00:00 → 0
        - Today 14:00 → 56
        - Today 23:45 → 95
        - Tomorrow 00:00 → 96
        - Tomorrow 14:00 → 152

    Handles any timestamp (today or future days).
    """

def period_index_to_timestamp(period_index: int) -> datetime:
    """Convert period index to timestamp for debugging/display.

    Args:
        period_index: Continuous index from today 00:00

    Returns:
        Timestamp for this period

    Example:
        0 → today 00:00
        56 → today 14:00
        96 → tomorrow 00:00
    """

def get_current_period_index() -> int:
    """Get current period index.

    Returns:
        Current period as continuous index from today 00:00
        (typically 0-95 for current day)
    """
```

**Responsibilities:**
- ✅ DST-aware period counting
- ✅ Timestamp ↔ period_index conversion
- ✅ Current period detection
- ✅ Period index → timestamp for display/debugging
- ❌ NO date tracking in storage
- ❌ NO complex metadata

**Data Type Conversions:**
```
timestamp (datetime) ──→ period_index (int) ──→ timestamp (datetime)
                     ↑                        ↓
            Input boundary            Output boundary
```

---

### Component 2: HistoricalDataStore (Simplified)

**File:** `core/bess/historical_data_store.py` (300 lines → ~100 lines)

**Purpose:** Store actual sensor data (only).

**Interface:**
```python
class HistoricalDataStore:
    """Stores actual sensor data at quarterly resolution.

    Uses simple integer indices: 0 = today 00:00, 96 = tomorrow 00:00.
    """

    def __init__(self, battery_capacity_kwh: float):
        self._records: dict[int, PeriodData] = {}  # period_index → data
        self.total_capacity = battery_capacity_kwh

    def record_period(self, period_index: int, period_data: PeriodData) -> None:
        """Record actual sensor data.

        Args:
            period_index: Continuous index from today 00:00
            period_data: Sensor data with data_source="actual"
        """
        self._records[period_index] = period_data

    def get_period(self, period_index: int) -> PeriodData | None:
        """Get data for a specific period."""
        return self._records.get(period_index)

    def get_today_periods(self) -> list[PeriodData | None]:
        """Get all periods for today (0-95, accounting for DST)."""
        today = datetime.now(tz=TIMEZONE).date()
        num_periods = get_period_count(today)
        return [self._records.get(i) for i in range(num_periods)]
```

**Key Changes:**
- ✅ Simplified: `int → PeriodData` (no date in key)
- ✅ Only stores actual sensor data
- ✅ ~100 lines (from 300)

---

### Component 3: ScheduleStore (Keep Existing)

**File:** `core/bess/schedule_store.py` (keep as-is)

**Purpose:** Store optimization predictions.

**No changes needed** - already simple enough.
- Stores optimization results
- ViewBuilder retrieves latest schedule

---

### Component 4: SensorCollector (No Changes Needed)

**File:** `core/bess/sensor_collector.py`

**Status:** ✅ Keep existing implementation - no changes required

**Rationale:**

- SensorCollector already has methods like `collect_interval_data()` that work
- The caller (BatterySystemManager) can calculate `period_index` using `get_current_period_index()`
- Then store the result: `historical_store.record_period(period_index, period_data)`
- **Minimal changes = better!**

**Usage Pattern (EXAMPLE - exact method names TBD during implementation):**

```python
# In BatterySystemManager
from .time_utils import get_current_period_index

# Calculate period index
period_index = get_current_period_index()

# Use existing sensor collector method (exact name TBD - might be collect_interval_data or similar)
period_data = self.sensor_collector.<existing_collect_method>(...)

# Store with continuous period index
self.historical_store.record_period(period_index, period_data)
```

**Note:** Exact method names and signatures will be determined during implementation by examining existing SensorCollector code.

---

### Component 5: PriceManager (Simplified + Smart)

**File:** `core/bess/price_manager.py` (current: 753 lines)

**Purpose:** Add ONE new method that concatenates today + tomorrow prices.

**New Method (ACTUAL - uses existing get_buy_prices/get_sell_prices):**

```python
class PriceManager:
    """Manages electricity prices - always returns quarterly."""

    def get_available_prices(self) -> tuple[list[float], list[float]]:
        """Get all available prices starting at today 00:00.

        Uses existing get_buy_prices() and get_sell_prices() methods.
        Returns full arrays - caller slices as needed.
        Automatically tries tomorrow, falls back to today only.

        Returns:
            (buy_prices, sell_prices)
            - Index 0 = today 00:00
            - Index 96 = tomorrow 00:00 (if available)
            - Length: 96 (today only) or 192 (today + tomorrow)

        Example at 14:00:
            - Returns 192 prices (96 today + 96 tomorrow)
            - prices[0] = today 00:00
            - prices[56] = today 14:00 (current)
            - prices[96] = tomorrow 00:00
            - Caller slices: prices[56:] for optimization
        """
        today = datetime.now(tz=TIMEZONE).date()
        tomorrow = today + timedelta(days=1)

        # Get today (full day from 00:00) - uses existing methods
        buy_prices = self.get_buy_prices(target_date=today)
        sell_prices = self.get_sell_prices(target_date=today)

        # Try tomorrow (full day from 00:00)
        try:
            tomorrow_buy = self.get_buy_prices(target_date=tomorrow)
            tomorrow_sell = self.get_sell_prices(target_date=tomorrow)

            # Concatenate if tomorrow available
            buy_prices = buy_prices + tomorrow_buy
            sell_prices = sell_prices + tomorrow_sell
        except (PriceDataUnavailableError, Exception):
            # Just today (96 values)
            logger.info("Tomorrow prices not available, using today only")
            pass

        return (buy_prices, sell_prices)
```

**Key Changes:**
- ✅ Add new `get_available_prices()` method only
- ✅ Uses existing `get_buy_prices()` and `get_sell_prices()` methods
- ✅ Returns FULL arrays starting at 00:00 (caller slices as needed)
- ✅ Consistent with all other arrays (solar, consumption)
- ❌ No other changes to PriceManager

**Design Principle:**
All data providers return full arrays from 00:00. Caller slices from current period.

---

### Component 6: ViewBuilder (Drastically Simplified)

**File:** `core/bess/daily_view_builder.py` (1,474 lines → ~100 lines)

**Purpose:** Merge actual (historical) + predicted (schedule) data for today.

**Interface:**
```python
class DailyViewBuilder:
    """Builds daily views by merging actual + predicted data."""

    def __init__(
        self,
        historical_store: HistoricalDataStore,
        schedule_store: ScheduleStore,
        battery_settings: BatterySettings,
    ):
        self.historical_store = historical_store
        self.schedule_store = schedule_store
        self.battery_settings = battery_settings

    def build_view(self) -> DailyView:
        """Build view for today.

        Merges:
        - Actual data (from sensors) for past periods
        - Predicted data (from optimization) for future periods

        Returns DailyView with quarterly periods (92-100 depending on DST).
        """
        today = datetime.now(tz=TIMEZONE).date()
        current_period = get_current_period_index()

        # Get data sources
        historical_periods = self.historical_store.get_today_periods()
        predicted_schedule = self.schedule_store.get_latest_schedule()

        # Merge: past = actual, future = predicted
        periods = []
        num_periods = get_period_count(today)

        for i in range(num_periods):
            if i < current_period and historical_periods[i] is not None:
                # Past: use actual
                periods.append(historical_periods[i])
            else:
                # Future: use predicted
                periods.append(predicted_schedule.periods[i])

        # Calculate summary
        total_savings = sum(
            p.economic.hourly_savings for p in periods
            if p and p.economic
        )

        return DailyView(
            date=today,
            periods=periods,
            total_savings=total_savings
        )
```

**Simplified but keeps separation:**
- HistoricalDataStore: Actual sensor data only
- ScheduleStore: Predictions only
- ViewBuilder: Simple merge based on current_period

**Deleted:**
- All complex aggregation methods
- All enrichment methods
- Metadata handling

---

### Component 7: BatterySystemManager (Simplified)

**File:** `core/bess/battery_system_manager.py` (2,120 lines → 1,200 lines)

**Purpose:** Orchestrate optimization and schedule updates.

**Key Method (EXAMPLE - illustrates the array-based pattern):**

```python
def update_battery_schedule(self):
    """Run optimization for all available periods."""

    # 1. Get current period
    current_period = get_current_period_index()  # e.g., 56 at 14:00

    # 2. Get all data arrays (all start at index 0 = today 00:00)
    buy_prices, sell_prices = self.price_manager.get_available_prices()
    solar = self._get_solar_forecast()        # 96 or 192 values from 00:00
    consumption = self._get_consumption_forecast()  # 96 or 192 values from 00:00

    logger.info(
        f"Optimizing {len(buy_prices)} periods from period {current_period}"
    )

    # 3. Slice all arrays from current period onward
    result = optimize_battery_schedule(
        buy_price=buy_prices[current_period:],
        sell_price=sell_prices[current_period:],
        home_consumption=consumption[current_period:],
        solar_production=solar[current_period:],
        battery_settings=self.battery_settings,
        initial_soe=self._get_current_soe()
    )  # Returns list[PeriodData] for periods from current onward

    # 4. Store predictions (continuous indices from current_period)
    for i, period_data in enumerate(result):
        self.schedule_store.record_period(current_period + i, period_data)

    # 5. Deploy to hardware (existing _apply_schedule method handles this)
    # Note: This uses existing GrowattScheduleManager and TOU interval logic
    # No changes needed to deployment - it already works with quarterly data

    logger.info(f"Stored {len(result)} period predictions")
```

**Important:** The code above is a **conceptual example** showing the array-based pattern. During implementation:
- Use existing `_get_solar_forecast()`, `_get_consumption_forecast()` methods if they exist
- Check actual method signatures for `optimize_battery_schedule()`
- Verify deployment logic matches existing `_apply_schedule()` flow
- Method names like `_get_current_soe()` may differ from actual implementation

**Key Design Principles:**

1. **All arrays start at index 0 = today 00:00**
   - Prices, solar, consumption all aligned
   - Consistent slicing: `array[current_period:]`

2. **Simple storage**
   - Just continuous indices: `current_period + i`
   - No date tracking needed

3. **PriceManager encapsulates complexity**
   - Handles today/tomorrow logic internally
   - Returns full arrays for consistency

**Key Changes:**

- ✅ Pure array operations
- ❌ Remove `IntervalMetadata` usage
- ❌ Remove period-to-hour conversion hacks

---

### Component 8: API Layer (Presentation)

**File:** `backend/api.py`

**Purpose:** Return data to frontend with optional aggregation.

```python
@app.get("/api/dashboard")
def get_dashboard(display_resolution: str = "quarterly"):
    """Get dashboard data.

    Args:
        display_resolution: "quarterly" or "hourly" (presentation only)
    """
    # Build view - always quarterly internally
    view = view_builder.build_view()  # Returns 96 quarterly periods for today

    # Convert to API response
    response = {
        "date": view.date.isoformat(),
        "resolution": "quarterly",
        "periods": [
            {
                "timestamp": period_index_to_timestamp(i).isoformat(),
                "energy": period.energy.to_dict(),
                "economic": period.economic.to_dict(),
                "decision": period.decision.to_dict(),
                "dataSource": period.data_source
            }
            for i, period in enumerate(view.periods)
        ],
        "totalSavings": view.total_savings
    }

    # Aggregate if user wants hourly display
    if display_resolution == "hourly":
        response = aggregate_response_to_hourly(response)  # 96 → 24

    return response
```

**Key Changes:**

- ✅ Timestamps generated from period index (not stored)
- ✅ Aggregation is presentation-only
- ❌ Remove `intervals` and `metadata` from response

---

## Data Models

### Keep: PeriodData (Rename from HourlyData)

```python
@dataclass
class PeriodData:
    """Data for a single quarterly period (15 minutes)."""
    hour: int  # For backward compatibility (hour = period_index // 4)
    energy: EnergyData
    economic: EconomicData
    decision: DecisionData
    timestamp: datetime | None = None
    data_source: str = "predicted"  # "actual" or "predicted"
```

**Changes:**

- ✅ Keep this as primary data model
- ✅ `hour` field kept for backward compatibility
- ❌ No `period_index` field (indices managed externally in storage)

### Delete: IntervalData

**Not needed - `PeriodData` serves same purpose.**

### Delete: IntervalMetadata

**No metadata needed - replaced by simple `period_index` integers.**

### Keep: DailyView

```python
@dataclass
class DailyView:
    """Daily view with quarterly periods."""
    date: date
    periods: list[PeriodData]  # 92-100 periods depending on DST
    total_savings: float
```

**Changes:**

- ❌ Remove `View` class (metadata-based complexity)
- ✅ Keep `DailyView` (simple, clear)

---

## What Gets Deleted

### Files to Delete

1. `core/bess/interval_metadata.py` (242 lines) - No metadata needed
2. `core/bess/models.py:IntervalData` (partial delete) - Replaced by PeriodData
3. `core/bess/models.py:View` (partial delete) - Replaced by simpler DailyView

### Methods to Delete from ViewBuilder

- `build_view(metadata, ...)` - metadata-based complexity
- `_aggregate_intervals_to_hourly()` - aggregation helper
- `_aggregate_periods_to_hourly()` - aggregation helper
- `_convert_periods_to_intervals()` - conversion helper
- `_enrich_interval_with_economic_data()` - enrichment
- `_enrich_period_with_economic_data()` - enrichment
- All complex aggregation and enrichment methods

### Concepts to Delete

- `(date, period_index)` tuple keys - replaced by continuous `period_index` integers
- `OptimizationWindow` class - not needed with array-based approach
- Resolution as parameter - always quarterly internally
- Metadata threading through function calls

**Total deletion: ~1,000+ lines**

---

## Success Criteria

### Must Have

1. ✅ Quarterly resolution works (96 periods/day)
2. ✅ DST handling works (92-100 periods on transition days)
3. ✅ Multi-day optimization works (when tomorrow prices available)
4. ✅ All tests pass
5. ✅ Frontend displays quarterly data correctly
6. ✅ Code is <70% of current branch size
7. ✅ All arrays start at index 0 = today 00:00 (prices, solar, consumption)

### Must NOT Have

1. ❌ Resolution as configuration
2. ❌ Hourly internal operations
3. ❌ IntervalMetadata threading
4. ❌ Triple data models
5. ❌ >200 lines in ViewBuilder
6. ❌ Date tracking in storage (just continuous period_index)
7. ❌ Complex metadata or OptimizationWindow classes

---

## Migration Strategy

### New Branch from Main

```bash
git checkout main
git checkout -b feature/quarterly-simple
```

### Cherry-Pick from Current Branch

- DP algorithm (if unchanged)
- Test data files
- Any bug fixes to main

### Do NOT Port

- IntervalMetadata
- Complex ViewBuilder methods
- Resolution conversion logic
- OptimizationWindow class
- Date-based storage keys

---

## Timeline Estimate

**Total: 4-5 days**

- Day 1: Core utilities (time_utils with multi-day mapping function)
- Day 2: Storage layer (HistoricalDataStore, SensorCollector)
- Day 3: ViewBuilder + BatterySystemManager
- Day 4: API + Frontend updates
- Day 5: Testing + bug fixes

---

## Risk Mitigation

1. **Keep current branch** - can revert if needed
2. **Incremental testing** - test each component as built
3. **Reference main** - verify behavior matches production
4. **Clear rollback** - new branch can be deleted

---

## Questions to Answer Before Starting

1. ✅ Should we always store economic data with actual data?
   - YES - calculate at collection time
2. ✅ What if Nordpool gives hourly in production?
   - UPSAMPLE to quarterly transparently
3. ✅ How to handle partial hours when collecting?
   - Collect at quarter boundaries only (00, 15, 30, 45)
4. ✅ How to handle multi-day optimization without dates?
   - Use continuous period indices (0-95 today, 96+ tomorrow)
5. ✅ Should PriceManager return sliced arrays?
   - NO - return full arrays from 00:00, caller slices as needed

---

## Core Design Principle: All Arrays Start at Index 0 = Today 00:00

This is the fundamental principle that makes the entire system simple and consistent.

### The Principle

**All data arrays align at index 0 = today 00:00:**

- `prices[0]` = today 00:00
- `prices[56]` = today 14:00 (current period at 14:00)
- `prices[96]` = tomorrow 00:00
- `solar[0]` = today 00:00
- `consumption[0]` = today 00:00
- `store.record_period(56, data)` = today 14:00

### Why This Works

1. **Consistent Indexing**: All arrays use the same index for the same time
2. **Simple Slicing**: At 14:00, slice all arrays from `current_period:` (e.g., `[56:]`)
3. **No Metadata**: Period index IS the timestamp (can convert for display)
4. **Clean Storage**: `record_period(index, data)` where index is continuous from 00:00

### Example at 14:00 (period 56)

```python
# 1. Get current period
current_period = get_current_period_index()  # Returns 56

# 2. Get all data arrays (all start at index 0 = today 00:00)
buy_prices, sell_prices = price_manager.get_available_prices()  # 192 values
solar = get_solar_forecast()  # 192 values
consumption = get_consumption_forecast()  # 192 values

# At this point:
# - buy_prices[0] = today 00:00
# - buy_prices[56] = today 14:00 (current)
# - buy_prices[96] = tomorrow 00:00
# - solar[0] = today 00:00
# - solar[56] = today 14:00 (current)

# 3. Slice all arrays from current period onward
result = optimize(
    buy_price=buy_prices[56:],      # From 14:00 onward
    sell_price=sell_prices[56:],    # From 14:00 onward
    solar=solar[56:],               # From 14:00 onward
    consumption=consumption[56:],   # From 14:00 onward
)

# 4. Store results with continuous indices
for i, period_data in enumerate(result):
    schedule_store.record_period(56 + i, period_data)
    # 56 + 0 = today 14:00
    # 56 + 1 = today 14:15
    # ...
    # 56 + 40 = today 14:00 + 40*15min = tomorrow 00:00
```

### Benefits

- **No date tracking**: Period index is relative to today's 00:00
- **No metadata**: Index IS the timestamp
- **Consistent API**: All data providers follow same pattern
- **Simple merging**: HistoricalDataStore and ScheduleStore both use same indices
- **Easy debugging**: `period_index_to_timestamp(56)` → "2025-11-16 14:00"

### What This Replaces

- ❌ `(date, period_index)` tuple keys
- ❌ `IntervalMetadata` class
- ❌ `OptimizationWindow` class
- ❌ Timestamp generation in core logic
- ❌ Resolution parameters and conversions

---

## Future Enhancements (Not in Initial Implementation)

### Prediction Accuracy Tracking

**Goal:** Track how optimization predictions evolve throughout the day to measure forecast accuracy.

**Use Case:** At 10:00 we predict period 80 (20:00) will have X savings. At 11:00 we predict Y savings. At 20:00 actual is Z. Compare accuracy.

**Simple Solution:** Snapshot entire DailyView to JSON after each optimization run.

**Implementation:**

- New file: `core/bess/optimization_history.py` (~100 lines)
- Class: `OptimizationHistory` with methods:
  - `save_snapshot(run_time, view)` - Save DailyView to JSON
  - `get_snapshots_for_date(date)` - Get all snapshots for a day
  - `analyze_period_accuracy(date, period_index, actual)` - Compare predictions vs actual
- Storage: JSON files in `optimization_history/` directory (~5MB/day)
- Usage: Call `save_snapshot()` after each optimization in `BatterySystemManager`

**Analysis Capabilities:**

- Compare predictions vs actuals for any period
- Track prediction accuracy by hours-ahead
- Visualize how predictions evolved throughout day
- Identify forecast improvement patterns

**Effort:** 2-3 hours to implement, minimal storage overhead

**Priority:** Nice-to-have, implement after core quarterly refactor is stable

---

**This design is FINAL. Implementation follows this exactly, no deviations.**
