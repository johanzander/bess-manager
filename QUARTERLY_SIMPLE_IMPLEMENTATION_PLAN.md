# Quarterly-Simple Implementation Plan

**Design:** See `QUARTERLY_SIMPLE_DESIGN.md`
**Branch:** `feature/quarterly-simple`
**Start Date:** 2025-11-15
**Estimated Duration:** 4-5 days

---

## Important: Code Examples in This Plan

**All code in this plan is EXAMPLE/TEMPLATE code showing the intended pattern.**

- Function names, signatures, and exact implementations must be verified against existing code
- During implementation, check what methods already exist and use them
- **Minimal changes principle:** Use existing methods wherever possible
- Only the core pattern (array-based, continuous period indices) is fixed

**Key things to verify during implementation:**
- Actual method names in SensorCollector (use existing methods)
- Actual signatures for forecast methods in BatterySystemManager
- Existing deployment/schedule application logic
- Whether helper methods already exist before creating new ones

---

## Phase 0: Setup (30 minutes)

### Step 0.1: Create New Branch
```bash
# Archive current branch
git branch feature/interval-data-refactor-archive

# Create fresh branch from main
git checkout main
git pull origin main
git checkout -b feature/quarterly-simple
```

**Validation:**
```bash
git status  # Should show "On branch feature/quarterly-simple"
git log -1  # Should show latest main commit
```

### Step 0.2: Create Tracking Document
Create `IMPLEMENTATION_LOG.md` to track progress:

```markdown
# Implementation Log

## Day 1: Core Utilities

- [ ] time_utils.py created
- [ ] Tests passing

## Day 2: Storage Layer

...
```

**Checkpoint:** New branch created, ready to code

---

## Phase 1: Core Utilities (Day 1 - 2 hours)

### Step 1.1: Create time_utils.py (1.5 hours)

**File:** `core/bess/time_utils.py`

**Implementation:**

```python
"""Time utilities for quarterly period handling.

KEY PRINCIPLE: All arrays start at index 0 = today 00:00.
Period indices are continuous integers from today's 00:00.
"""

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Constants - NOT configurable
TIMEZONE = ZoneInfo("Europe/Stockholm")
INTERVAL_MINUTES = 15  # Quarterly resolution
PERIODS_PER_HOUR = 4
PERIODS_PER_DAY_NORMAL = 96

def get_period_count(target_date: date) -> int:
    """Get number of quarterly periods in a day.

    Handles DST transitions:
    - Normal day: 96 periods (24 hours * 4)
    - DST spring: 92 periods (23 hours * 4)
    - DST fall: 100 periods (25 hours * 4)

    Args:
        target_date: The calendar date

    Returns:
        Number of quarterly periods in this day
    """
    start = datetime.combine(target_date, time(0, 0), tzinfo=TIMEZONE)
    next_day = start + timedelta(days=1)

    # Calculate actual hours (DST-aware)
    elapsed_hours = (next_day - start).total_seconds() / 3600

    return int(elapsed_hours * PERIODS_PER_HOUR)

def timestamp_to_period_index(dt: datetime) -> int:
    """Convert timestamp to continuous period index from today's 00:00.

    Args:
        dt: Timestamp to convert

    Returns:
        Continuous index where:
        - Today 00:00 → 0
        - Today 14:00 → 56
        - Today 23:45 → 95
        - Tomorrow 00:00 → 96
        - Tomorrow 14:00 → 152

    Example:
        >>> dt = datetime(2025, 11, 15, 14, 30, tzinfo=TIMEZONE)
        >>> timestamp_to_period_index(dt)
        58  # (14 * 4) + 2 = 58
    """
    today = datetime.now(tz=TIMEZONE).date()
    target_date = dt.date()

    # Calculate days from today
    days_from_today = (target_date - today).days

    # Get periods elapsed within the target day
    day_start = datetime.combine(target_date, time(0, 0), tzinfo=dt.tzinfo)
    elapsed_minutes = (dt - day_start).total_seconds() / 60
    period_within_day = int(elapsed_minutes / INTERVAL_MINUTES)

    if days_from_today == 0:
        # Today
        return period_within_day
    elif days_from_today == 1:
        # Tomorrow - offset by today's period count
        today_periods = get_period_count(today)
        return today_periods + period_within_day
    else:
        # Future days (general case)
        total_periods = 0
        current_date = today
        while current_date < target_date:
            total_periods += get_period_count(current_date)
            current_date += timedelta(days=1)
        return total_periods + period_within_day

def period_index_to_timestamp(period_index: int) -> datetime:
    """Convert period index to timestamp for debugging/display.

    Args:
        period_index: Continuous index from today 00:00

    Returns:
        Timestamp for this period

    Example:
        >>> period_index_to_timestamp(0)
        datetime(2025, 11, 15, 0, 0, tzinfo=ZoneInfo('Europe/Stockholm'))
        >>> period_index_to_timestamp(56)
        datetime(2025, 11, 15, 14, 0, tzinfo=ZoneInfo('Europe/Stockholm'))
        >>> period_index_to_timestamp(96)
        datetime(2025, 11, 16, 0, 0, tzinfo=ZoneInfo('Europe/Stockholm'))
    """
    today = datetime.now(tz=TIMEZONE).date()
    today_periods = get_period_count(today)

    if period_index < today_periods:
        # Today
        day_start = datetime.combine(today, time(0, 0), tzinfo=TIMEZONE)
        delta = timedelta(minutes=period_index * INTERVAL_MINUTES)
        return day_start + delta
    else:
        # Tomorrow or later
        remaining_periods = period_index - today_periods
        tomorrow = today + timedelta(days=1)
        tomorrow_periods = get_period_count(tomorrow)

        if remaining_periods < tomorrow_periods:
            # Tomorrow
            day_start = datetime.combine(tomorrow, time(0, 0), tzinfo=TIMEZONE)
            delta = timedelta(minutes=remaining_periods * INTERVAL_MINUTES)
            return day_start + delta
        else:
            # Future days (general case - walk through days)
            current_date = today
            periods_to_skip = period_index

            while periods_to_skip >= get_period_count(current_date):
                periods_to_skip -= get_period_count(current_date)
                current_date += timedelta(days=1)

            day_start = datetime.combine(current_date, time(0, 0), tzinfo=TIMEZONE)
            delta = timedelta(minutes=periods_to_skip * INTERVAL_MINUTES)
            return day_start + delta

def get_current_period_index() -> int:
    """Get current period index.

    Returns:
        Current period as continuous index from today 00:00
        (typically 0-95 for current day)

    Example:
        At 14:30 → returns 58
    """
    now = datetime.now(tz=TIMEZONE)
    return timestamp_to_period_index(now)
```

**Test file:** `core/bess/tests/unit/test_time_utils.py`

```python
"""Tests for time_utils."""

import pytest
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from unittest.mock import patch

from core.bess.time_utils import (
    TIMEZONE,
    get_period_count,
    timestamp_to_period_index,
    period_index_to_timestamp,
    get_current_period_index,
)

def test_normal_day_has_96_periods():
    """Normal day should have 96 quarterly periods."""
    normal_day = date(2025, 11, 15)  # Not a DST transition
    assert get_period_count(normal_day) == 96

@patch('core.bess.time_utils.datetime')
def test_timestamp_to_period_index_today(mock_datetime):
    """Should convert today's timestamp to period index."""
    # Mock "today" as 2025-11-15
    mock_datetime.now.return_value = datetime(2025, 11, 15, 12, 0, tzinfo=TIMEZONE)

    # Test various times today
    dt_morning = datetime(2025, 11, 15, 0, 0, tzinfo=TIMEZONE)
    assert timestamp_to_period_index(dt_morning) == 0  # Midnight

    dt_afternoon = datetime(2025, 11, 15, 14, 30, tzinfo=TIMEZONE)
    assert timestamp_to_period_index(dt_afternoon) == 58  # 14 * 4 + 2

    dt_evening = datetime(2025, 11, 15, 23, 45, tzinfo=TIMEZONE)
    assert timestamp_to_period_index(dt_evening) == 95  # Last period

@patch('core.bess.time_utils.datetime')
def test_timestamp_to_period_index_tomorrow(mock_datetime):
    """Should convert tomorrow's timestamp to period index."""
    # Mock "today" as 2025-11-15
    mock_datetime.now.return_value = datetime(2025, 11, 15, 12, 0, tzinfo=TIMEZONE)

    # Test tomorrow
    dt_tomorrow_midnight = datetime(2025, 11, 16, 0, 0, tzinfo=TIMEZONE)
    assert timestamp_to_period_index(dt_tomorrow_midnight) == 96  # Tomorrow 00:00

    dt_tomorrow_afternoon = datetime(2025, 11, 16, 14, 0, tzinfo=TIMEZONE)
    assert timestamp_to_period_index(dt_tomorrow_afternoon) == 152  # 96 + 56

@patch('core.bess.time_utils.datetime')
def test_period_index_to_timestamp(mock_datetime):
    """Should convert period index to timestamp."""
    # Mock "today" as 2025-11-15
    mock_datetime.now.return_value = datetime(2025, 11, 15, 12, 0, tzinfo=TIMEZONE)

    # Today
    dt = period_index_to_timestamp(0)
    assert dt.date() == date(2025, 11, 15)
    assert dt.hour == 0
    assert dt.minute == 0

    dt = period_index_to_timestamp(58)
    assert dt.date() == date(2025, 11, 15)
    assert dt.hour == 14
    assert dt.minute == 30

    # Tomorrow
    dt = period_index_to_timestamp(96)
    assert dt.date() == date(2025, 11, 16)
    assert dt.hour == 0
    assert dt.minute == 0

@patch('core.bess.time_utils.datetime')
def test_roundtrip_conversion(mock_datetime):
    """period_index → timestamp → period_index should roundtrip."""
    # Mock "today" as 2025-11-15
    mock_datetime.now.return_value = datetime(2025, 11, 15, 12, 0, tzinfo=TIMEZONE)

    for period_idx in [0, 56, 95, 96, 152]:
        timestamp = period_index_to_timestamp(period_idx)
        recovered_idx = timestamp_to_period_index(timestamp)
        assert recovered_idx == period_idx

@patch('core.bess.time_utils.datetime')
def test_get_current_period_index(mock_datetime):
    """Should return current period index."""
    # Mock current time as 2025-11-15 14:30
    now_time = datetime(2025, 11, 15, 14, 30, tzinfo=TIMEZONE)
    mock_datetime.now.return_value = now_time

    assert get_current_period_index() == 58  # 14 * 4 + 2

# TODO: Add DST tests when we know specific DST dates for 2025
```

**Validation:**
```bash
./.venv/bin/python -m pytest core/bess/tests/unit/test_time_utils.py -v
```

**Success:** All tests pass, file is ~100 lines (simpler than original)

**Checkpoint:** Core utilities complete and tested

---

## Phase 2: Storage Layer (Day 2 - 5 hours)

### Step 2.1: Simplify HistoricalDataStore (1.5 hours)

**File:** `core/bess/historical_data_store.py`

**Changes:**

1. Remove complex interval methods
2. Change storage to simple `dict[int, PeriodData]` (period_index → data)
3. Add simple `record_period()` method
4. Add simple `get_today_periods()` method

**New Interface:**

```python
class HistoricalDataStore:
    """Stores actual sensor data at quarterly resolution.

    Uses continuous period indices (0 = today 00:00, 96 = tomorrow 00:00).
    Only stores today's data in memory.
    """

    def __init__(self, battery_capacity_kwh: float = 30.0):
        self._records: dict[int, PeriodData] = {}  # period_index → data
        self.total_capacity = battery_capacity_kwh

    def record_period(self, period_index: int, period_data: PeriodData) -> None:
        """Record actual sensor data for a period.

        Args:
            period_index: Continuous index from today 00:00 (0-95)
            period_data: Sensor data with data_source="actual"
        """
        self._records[period_index] = period_data

        logger.debug(
            f"Recorded period {period_index}: "
            f"SOC {period_data.energy.battery_soe_start:.1f} → "
            f"{period_data.energy.battery_soe_end:.1f} kWh"
        )

    def get_period(self, period_index: int) -> PeriodData | None:
        """Get data for a specific period.

        Args:
            period_index: Continuous index from today 00:00

        Returns:
            PeriodData if available, None if missing
        """
        return self._records.get(period_index)

    def get_today_periods(self) -> list[PeriodData | None]:
        """Get all periods for today (accounting for DST).

        Returns:
            List of 92-100 PeriodData (or None for missing periods)
        """
        from .time_utils import get_period_count
        from datetime import datetime

        today = datetime.now(tz=TIMEZONE).date()
        num_periods = get_period_count(today)  # 92-100 for DST

        # Return list with data if available
        return [self._records.get(i) for i in range(num_periods)]
```

**Test updates:** Update `test_historical_data_store.py` to test new interface

**Validation:**
```bash
./.venv/bin/python -m pytest core/bess/tests/unit/test_historical_data_store.py -v
```

**Success:** Simplified to ~150 lines (from ~400)

---

### Step 2.2: SensorCollector - NO Changes Needed (0 hours)

**File:** `core/bess/sensor_collector.py`

**Decision:** Keep existing implementation - use existing methods

**Rationale:**
- SensorCollector already has methods that work (e.g., `collect_interval_data()`)
- Caller (BatterySystemManager) calculates `period_index` and uses existing methods
- **Minimal changes = better!**

**Skip this step** - move directly to integration testing.

---

### Step 2.3: Storage Integration Test (30 minutes)

**Test file:** `core/bess/tests/integration/test_storage_flow.py`

```python
"""Integration test for collection → storage flow."""

from core.bess.historical_data_store import HistoricalDataStore
from core.bess.models import PeriodData, EnergyData

def test_store_and_retrieve_today():
    """Test storing and retrieving today's data."""
    store = HistoricalDataStore(battery_capacity_kwh=30.0)

    # Store 96 periods (continuous indices from 00:00)
    for i in range(96):
        period_data = PeriodData(
            hour=i // 4,
            energy=EnergyData(
                solar_production=1.0,
                home_consumption=0.5,
                battery_charged=0.0,
                battery_discharged=0.0,
                grid_imported=0.0,
                grid_exported=0.5,
                battery_soe_start=15.0,
                battery_soe_end=15.0
            ),
            timestamp=None,
            data_source="actual"
        )

        store.record_period(i, period_data)

    # Retrieve specific period
    period_56 = store.get_period(56)  # 14:00
    assert period_56 is not None
    assert period_56.energy.solar_production == 1.0

    # Retrieve all today's periods
    periods = store.get_today_periods()

    assert len(periods) == 96
    assert all(p is not None for p in periods)
    assert periods[0].energy.solar_production == 1.0
    assert periods[56] == period_56
```

**Checkpoint:** Storage layer complete and tested

---

## Phase 3: ViewBuilder + Manager (Day 3 - 5 hours)

### Step 3.1: Completely Rewrite ViewBuilder (3 hours)

**File:** `core/bess/daily_view_builder.py`

**Delete everything, write from scratch:**

```python
"""ViewBuilder - Creates daily views combining actual + predicted data.

SIMPLIFIED: Always operates on quarterly periods.
"""

import logging
from datetime import date
from dataclasses import dataclass

from .historical_data_store import HistoricalDataStore
from .schedule_store import ScheduleStore
from .settings import BatterySettings
from .models import PeriodData
from .time_utils import get_current_period_index, get_period_count, TIMEZONE

logger = logging.getLogger(__name__)

@dataclass
class DailyView:
    """Daily view with quarterly periods."""
    date: date
    periods: list[PeriodData]  # 92-100 periods depending on DST
    total_savings: float
    actual_count: int
    predicted_count: int

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

        Returns:
            DailyView with quarterly periods (92-100 depending on DST)
        """
        today = datetime.now(tz=TIMEZONE).date()
        logger.info(f"Building view for {today}")

        # 1. Get current period index
        current_period = get_current_period_index()

        # 2. Get data sources
        historical_periods = self.historical_store.get_today_periods()
        predicted_schedule = self.schedule_store.get_latest_schedule()

        if not predicted_schedule:
            raise ValueError("No optimization schedule available")

        predicted_periods = predicted_schedule.optimization_result.hourly_data

        # 3. Merge: past = actual, future = predicted
        periods = []
        num_periods = get_period_count(today)

        for i in range(num_periods):
            if i < current_period and historical_periods[i] is not None:
                # Past: use actual sensor data
                periods.append(historical_periods[i])
            else:
                # Future: use predicted optimization data
                if i < len(predicted_periods):
                    periods.append(predicted_periods[i])
                else:
                    logger.warning(f"No predicted data for period {i}")
                    continue

        # 4. Calculate summary
        total_savings = sum(
            p.economic.hourly_savings for p in periods
            if p.economic is not None
        )

        actual_count = sum(1 for p in periods if p.data_source == "actual")
        predicted_count = len(periods) - actual_count

        logger.info(
            f"Built view: {len(periods)} periods "
            f"({actual_count} actual, {predicted_count} predicted), "
            f"total savings: {total_savings:.2f} SEK"
        )

        return DailyView(
            date=today,
            periods=periods,
            total_savings=total_savings,
            actual_count=actual_count,
            predicted_count=predicted_count
        )
```

**That's it! ~80 lines instead of 1,474.**

**Test file:** `core/bess/tests/unit/test_view_builder_simple.py`

```python
"""Tests for simplified ViewBuilder."""

from datetime import date
from core.bess.daily_view_builder import DailyViewBuilder, DailyView
from core.bess.historical_data_store import HistoricalDataStore
from core.bess.schedule_store import ScheduleStore
from core.bess.settings import BatterySettings

def test_build_view_basic(mock_schedule_store, mock_historical_store):
    """Test basic view building."""
    builder = DailyViewBuilder(
        historical_store=mock_historical_store,
        schedule_store=mock_schedule_store,
        battery_settings=BatterySettings()
    )

    view = builder.build_view(date(2025, 11, 15))

    assert isinstance(view, DailyView)
    assert view.date == date(2025, 11, 15)
    assert len(view.periods) == 96  # Quarterly
    assert view.total_savings >= 0
```

**Validation:**
```bash
./.venv/bin/python -m pytest core/bess/tests/unit/test_view_builder_simple.py -v
```

---

### Step 3.2: Update BatterySystemManager (2 hours)

**File:** `core/bess/battery_system_manager.py`

**Key changes:**

1. Import `get_date_and_period_for_index` from time_utils
2. Update `update_battery_schedule()` to use simple parameters
3. Remove IntervalMetadata usage

**Simplified method:**
```python
def update_battery_schedule(self):
    """Run optimization - supports multi-day."""
    from .time_utils import (
        get_current_period,
        get_period_count,
        get_date_and_period_for_index
    )
    from .exceptions import PriceDataUnavailableError

    # 1. Determine optimization parameters
    start_date, start_period = get_current_period()

    try:
        # Try multi-day
        tomorrow = start_date + timedelta(days=1)
        tomorrow_prices = self._price_manager.get_prices_for_day(tomorrow)

        num_periods = (
            (get_period_count(start_date) - start_period) +
            get_period_count(tomorrow)
        )
        logger.info("Multi-day optimization enabled")

    except PriceDataUnavailableError:
        # Single-day
        num_periods = get_period_count(start_date) - start_period
        logger.info("Single-day optimization (tomorrow prices unavailable)")

    # 2. Get data (arrays)
    buy_prices, sell_prices = self._get_prices_for_periods(
        start_date, start_period, num_periods
    )
    consumption = self._get_consumption_forecast(num_periods)
    solar = self._get_solar_forecast(num_periods)

    # 3. Optimize
    result = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=consumption,
        solar_production=solar,
        battery_settings=self.battery_settings,
        initial_soe=self._get_initial_soe()
    )

    # 4. Store results (use utility function to map indices)
    for i, period_data in enumerate(result.hourly_data):
        target_date, period_idx = get_date_and_period_for_index(
            start_date, start_period, i
        )
        self.historical_store.record_period(target_date, period_idx, period_data)

    # 5. Deploy to hardware
    self._deploy_schedule(result, start_date, start_period)

    return True
```

**Validation:** Run existing manager tests

---

**Checkpoint:** Day 3 complete - core refactor done

---

## Phase 4: API & Frontend (Day 4 - 4 hours)

### Step 4.1: Update API (2 hours)

**File:** `backend/api.py`

**Update dashboard endpoint:**
```python
@app.get("/api/dashboard")
def get_dashboard(display_resolution: str = "quarterly"):
    """Get dashboard data.

    Args:
        display_resolution: "quarterly" or "hourly" (presentation only)
    """
    from datetime import datetime, date
    from core.bess.time_utils import date_and_period_to_timestamp

    # Build view - always quarterly internally
    today = datetime.now().date()
    view = battery_system.daily_view_builder.build_view(today)

    # Convert to API response with timestamps
    periods_response = []
    for i, period in enumerate(view.periods):
        timestamp = date_and_period_to_timestamp(today, i)

        periods_response.append({
            "timestamp": timestamp.isoformat(),
            "energy": {
                "solarProduction": period.energy.solar_production,
                "homeConsumption": period.energy.home_consumption,
                # ... rest of energy fields
            },
            "economic": {
                "hourlySavings": period.economic.hourly_savings if period.economic else 0.0,
                # ... rest of economic fields
            },
            "decision": {
                "strategicIntent": period.decision.strategic_intent,
                # ... rest of decision fields
            },
            "dataSource": period.data_source
        })

    response = {
        "date": today.isoformat(),
        "resolution": "quarterly",
        "periodCount": len(periods_response),
        "periods": periods_response,
        "totalSavings": view.total_savings,
        "actualCount": view.actual_count,
        "predictedCount": view.predicted_count
    }

    # Aggregate if user wants hourly
    if display_resolution == "hourly":
        response = _aggregate_to_hourly_display(response)

    return response

def _aggregate_to_hourly_display(quarterly_response: dict) -> dict:
    """Aggregate quarterly response to hourly for display.

    This is PRESENTATION ONLY - internal data stays quarterly.
    """
    periods = quarterly_response["periods"]
    hourly_periods = []

    # Group by hour
    for hour in range(24):
        quarter_start = hour * 4
        quarter_end = quarter_start + 4
        quarters = periods[quarter_start:quarter_end]

        if not quarters:
            continue

        # Aggregate energy (sum)
        aggregated_energy = {
            "solarProduction": sum(q["energy"]["solarProduction"] for q in quarters),
            "homeConsumption": sum(q["energy"]["homeConsumption"] for q in quarters),
            # ... sum other energy fields
        }

        # Aggregate economic (sum)
        aggregated_economic = {
            "hourlySavings": sum(q["economic"]["hourlySavings"] for q in quarters),
            # ... sum other cost fields
        }

        # Use last quarter for SOC
        last_quarter = quarters[-1]

        hourly_periods.append({
            "timestamp": quarters[0]["timestamp"],  # Start of hour
            "energy": aggregated_energy,
            "economic": aggregated_economic,
            "decision": last_quarter["decision"],
            "dataSource": last_quarter["dataSource"]
        })

    return {
        **quarterly_response,
        "resolution": "hourly",
        "periodCount": len(hourly_periods),
        "periods": hourly_periods
    }
```

**Validation:** Test API manually with curl

---

### Step 4.2: Update Frontend (2 hours)

**File:** `frontend/src/api/scheduleApi.ts`

Update to use new response format (periods instead of hourlyData).

**File:** `frontend/src/components/EnergyFlowChart.tsx`

Update to render periods array.

**Validation:** Run frontend, check dashboard displays

---

**Checkpoint:** Day 4 complete - API and frontend updated

---

## Phase 5: Testing & Cleanup (Day 5 - 4 hours)

### Step 5.1: Run Full Test Suite (1 hour)

```bash
# Run all tests
./.venv/bin/python -m pytest core/bess/tests/ -v

# Check coverage
./.venv/bin/python -m pytest core/bess/tests/ --cov=core.bess --cov-report=html
```

**Fix any failures.**

---

### Step 5.2: Integration Testing (2 hours)

**Manual test checklist:**

- [ ] Dashboard loads without errors
- [ ] Shows 96 quarterly periods
- [ ] Hourly aggregation toggle works
- [ ] Actual vs predicted data shows correctly
- [ ] Multi-day optimization works (when tomorrow prices available)
- [ ] Savings calculations are correct

---

### Step 5.3: Code Cleanup (1 hour)

**Delete files:**
```bash
# Remove old complex implementations
git rm core/bess/interval_metadata.py
```

**Update documentation:**
- Update README.md with new architecture
- Update CLAUDE.md to reference new design

---

### Step 5.4: Final Validation

**Success criteria checklist:**

- [ ] All tests pass (100%)
- [ ] Code is <70% of current branch size
- [ ] ViewBuilder is <200 lines
- [ ] No IntervalMetadata imports
- [ ] No triple data models
- [ ] Frontend displays quarterly data
- [ ] Multi-day optimization works
- [ ] DST handling works

---

## Rollback Plan

If critical issues found:

```bash
# Delete new branch
git checkout main
git branch -D feature/quarterly-simple

# Restore archived branch if needed
git checkout feature/interval-data-refactor-archive
```

---

## Merge Criteria

Before merging to main:

1. ✅ All tests passing
2. ✅ Manual testing complete
3. ✅ Code review approved (by you)
4. ✅ No regressions from main
5. ✅ Performance acceptable

---

**This plan is FINAL. Execute each step in order without deviations.**
