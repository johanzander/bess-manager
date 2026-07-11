# Savings Date/Resolution Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Savings page's day/week/month/year "rolling window ending at now" toggle with a Day/Month/Year resolution selector plus a date picker, so the report can show any historical day, month, or year — not just the most recent one.

**Architecture:** The core aggregator (`core/bess/savings_aggregator.py::build_buckets`) already accepts an optional `today: date` anchor and walks backward from it — no change needed there. Thread a new optional `date` query param through the FastAPI route into that existing anchor, mirroring the exact pattern `/api/dashboard` already uses for its historical-day picker (`backend/api.py:565-613`). On the frontend, extend the existing `DateSelector` component (already used by `InsightsPage` for day-level history browsing) with a `resolution` prop so it can step by day, month, or year and reuse it on `SavingsPage`.

**Tech Stack:** FastAPI (Python), React + TypeScript, react-datepicker v7, Vitest + Testing Library, pytest.

## Global Constraints

- The visible resolution selector on `SavingsPage` offers only **Day / Month / Year** — `week` is dropped from the UI. The `'week'` value stays in the `SavingsAggregatePeriod` type and backend (`VALID_PERIODS`) unchanged, since it's still exercised directly by existing component tests and there's no reason to break that contract.
- kWh values fold into the metric value string (e.g. `2.50 EUR (20.0 kWh)`), per the existing System-Overview-style card design already shipped on the Savings page — do not reintroduce a separate subtext line.
- Follow existing camelCase-at-the-API-boundary convention: new backend query param is `date` (ISO `YYYY-MM-DD`), matching `/api/dashboard`'s `date` param exactly.
- Run `.venv/bin/pytest -m "not slow"` (backend) and `npx vitest run` (frontend, from `frontend/`) after every task; both must be green before moving on.
- Run `./scripts/quality-check.sh` before considering the branch done.

---

### Task 1: Backend — `date` query param on `/api/savings/aggregate`

**Files:**
- Modify: `backend/api.py:2306-2350`
- Test: `backend/tests/test_savings_aggregate_api.py`

**Interfaces:**
- Consumes: `core.bess.savings_aggregator.build_buckets(period, count, store, today=None, today_view=None)` — unchanged, already supports an arbitrary anchor date (see `core/bess/savings_aggregator.py:140-198`).
- Produces: `GET /api/savings/aggregate?period=...&count=...&date=YYYY-MM-DD` — `date` optional, omit for "ending at now" (unchanged default behavior).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_savings_aggregate_api.py`, inside `class TestSavingsAggregate` (after `test_day_period_default_count_is_one`):

```python
    def test_date_param_anchors_the_buckets_to_that_day(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        store.save_day(
            DailyView(
                date=date(2026, 6, 15),
                periods=[_period(1.0, 0.0)],
                total_savings=1.0,
                actual_count=1,
                predicted_count=0,
            )
        )
        sys.modules["app"].bess_controller = _make_started_controller(store)

        resp = _client.get("/api/savings/aggregate?period=day&count=1&date=2026-06-15")

        assert resp.status_code == 200
        body = resp.json()
        assert body["buckets"][0]["label"] == "2026-06-15"
        assert body["buckets"][0]["dayCount"] == 1

    def test_date_param_for_a_day_with_no_data_returns_empty_bucket(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        sys.modules["app"].bess_controller = _make_started_controller(store)

        resp = _client.get("/api/savings/aggregate?period=day&count=1&date=2026-05-01")

        assert resp.status_code == 200
        body = resp.json()
        assert body["buckets"][0]["label"] == "2026-05-01"
        assert body["buckets"][0]["dayCount"] == 0

    def test_date_param_does_not_use_the_live_daily_view_for_a_historical_day(self, tmp_path):
        controller = _make_started_controller(DailyViewStore(persist_dir=tmp_path))
        sys.modules["app"].bess_controller = controller

        resp = _client.get("/api/savings/aggregate?period=day&count=1&date=2026-05-01")

        assert resp.status_code == 200
        # The live view (today's in-progress data) must never be consulted
        # when browsing a historical date — only the persisted store.
        controller.system.daily_view_builder.build_daily_view.assert_not_called()

    def test_invalid_date_param_returns_422(self, tmp_path):
        sys.modules["app"].bess_controller = _make_started_controller(
            _seeded_store(tmp_path)
        )

        resp = _client.get("/api/savings/aggregate?period=day&date=not-a-date")

        assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest backend/tests/test_savings_aggregate_api.py -k date_param -v`
Expected: FAIL — `date` isn't a recognized query param yet (extra params are ignored by FastAPI by default, so `label` assertions fail instead of the request erroring; `test_invalid_date_param_returns_422` fails because there's no validation to reject it).

- [ ] **Step 3: Implement the `date` param**

In `backend/api.py`, replace the route (lines 2306-2350):

```python
@router.get("/api/savings/aggregate")
async def get_savings_aggregate(
    period: str = Query(..., pattern="^(day|week|month|year)$"),
    count: int | None = Query(None, ge=1, le=520),  # 520 weeks is roughly 10 years
    date: str | None = Query(
        None, description="ISO date (YYYY-MM-DD) to anchor the buckets to; omit for now"
    ),
):
    """Get day/week/month/year savings aggregates, anchored to `date` (or now).

    `day` is today's live (in-progress) view when no snapshot has been
    persisted for it yet and `date` is omitted or equals today; any other
    date (including a historical `day` request) reads the persisted daily
    history only, same as `/api/dashboard`'s historical-day handling.
    """
    from app import bess_controller

    _require_configured_system(bess_controller)

    try:
        target_date = date_cls.fromisoformat(date) if date else time_utils.today()
    except ValueError as e:
        raise HTTPException(
            status_code=422, detail=f"Invalid date {date!r}: {e}"
        ) from e

    try:
        resolved_count = count or DEFAULT_COUNTS[period]

        today_view = None
        if period == "day" and target_date == time_utils.today():
            now = time_utils.now()
            current_period = now.hour * 4 + now.minute // 15
            today_view = bess_controller.system.daily_view_builder.build_daily_view(
                current_period
            )

        buckets = build_buckets(
            period,
            resolved_count,
            bess_controller.system.daily_view_store,
            today=target_date,
            today_view=today_view,
        )
        currency = bess_controller.system.home_settings.currency

        api_buckets = [APISavingsBucket.from_internal(b, currency) for b in buckets]

        response = {
            "buckets": [b.__dict__ for b in api_buckets],
            "count": len(api_buckets),
        }

        return convert_keys_to_camel_case(response)

    except Exception as e:
        logger.error(f"Error building savings aggregate: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
```

`date_cls` and `time_utils` are already imported at the top of `backend/api.py` (`from datetime import date as date_cls` at line 8; `time_utils` is imported and already used by `/api/dashboard` at line 601) — no new imports needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest backend/tests/test_savings_aggregate_api.py -v`
Expected: PASS — all tests in the file, including the 4 new ones and the pre-existing ones (`test_day_period_uses_live_daily_view_for_today` still passes because it doesn't set `date`, so `target_date` defaults to `time_utils.today()`).

- [ ] **Step 5: Run the full fast backend suite**

Run: `.venv/bin/pytest -m "not slow"`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/api.py backend/tests/test_savings_aggregate_api.py
git commit -m "feat: anchor savings aggregate to an arbitrary date, not just now"
```

---

### Task 2: Frontend API client — thread `date` through `fetchSavingsAggregate`

**Files:**
- Modify: `frontend/src/api/scheduleApi.ts:232-240`

**Interfaces:**
- Consumes: nothing new (calls the endpoint from Task 1).
- Produces: `fetchSavingsAggregate(period: SavingsAggregatePeriod, count?: number, date?: string): Promise<SavingsAggregateResponse>` — `date` is an ISO `YYYY-MM-DD` string; omit/undefined means "now", exactly like the existing `fetchDashboardData` convention elsewhere in this file.

There is no dedicated test file for this raw client function today (it's covered indirectly through the `useSavingsAggregate` hook tests in Task 3) — no new test file here.

- [ ] **Step 1: Update the function signature**

In `frontend/src/api/scheduleApi.ts`, replace lines 232-240:

```typescript
export const fetchSavingsAggregate = async (
  period: SavingsAggregatePeriod,
  count?: number,
  date?: string
): Promise<SavingsAggregateResponse> => {
  const params: Record<string, string | number> = { period };
  if (count) params.count = count;
  if (date) params.date = date;
  const response = await api.get('/api/savings/aggregate', { params });
  return response.data;
};
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit -p .`
Expected: no errors (this is a backward-compatible optional-param addition; every existing call site still compiles).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/scheduleApi.ts
git commit -m "feat: add optional date param to fetchSavingsAggregate"
```

---

### Task 3: Frontend hook — thread `date` through `useSavingsAggregate`

**Files:**
- Modify: `frontend/src/hooks/useSavingsAggregate.ts`
- Test: `frontend/src/hooks/__tests__/useSavingsAggregate.test.ts`

**Interfaces:**
- Consumes: `fetchSavingsAggregate(period, count?, date?)` from Task 2.
- Produces: `useSavingsAggregate(period: SavingsAggregatePeriod, count?: number, date?: string): { data, loading, error }` — refetches whenever `period`, `count`, or `date` changes.

- [ ] **Step 1: Write the failing test**

In `frontend/src/hooks/__tests__/useSavingsAggregate.test.ts`, update the two existing `toHaveBeenCalledWith` assertions to include the new third arg, and add a new test. Replace line 43:

```typescript
    expect(fetchSpy).toHaveBeenCalledWith('week', 1, undefined);
```

Replace line 80:

```typescript
    expect(fetchSpy).toHaveBeenCalledWith('day', 1, undefined);
```

Add a new test at the end of the `describe` block (before the closing `});` on line 96):

```typescript
  it('passes the date param through to fetchSavingsAggregate', async () => {
    const fetchSpy = vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [],
      count: 0,
    });

    const { result } = renderHook(() => useSavingsAggregate('month', undefined, '2026-05-01'));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(fetchSpy).toHaveBeenCalledWith('month', undefined, '2026-05-01');
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useSavingsAggregate.test.ts`
Expected: FAIL — `fetchSpy` is currently called with only 2 args (`period, count`), so the updated 3-arg assertions and the new test fail.

- [ ] **Step 3: Implement**

Replace the full contents of `frontend/src/hooks/useSavingsAggregate.ts`:

```typescript
import { useState, useEffect, useCallback } from 'react';
import { fetchSavingsAggregate, SavingsBucket, SavingsAggregatePeriod } from '../api/scheduleApi';

interface UseSavingsAggregateResult {
  data: SavingsBucket[] | null;
  loading: boolean;
  error: string | null;
}

export const useSavingsAggregate = (
  period: SavingsAggregatePeriod,
  count?: number,
  date?: string
): UseSavingsAggregateResult => {
  const [data, setData] = useState<SavingsBucket[] | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await fetchSavingsAggregate(period, count, date);
      setData(result.buckets);
    } catch (err) {
      console.error('Failed to fetch savings aggregate:', err);
      const errorMessage = err instanceof Error ? err.message : 'Failed to load savings history';
      setError(errorMessage);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [period, count, date]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { data, loading, error };
};

export default useSavingsAggregate;
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useSavingsAggregate.test.ts`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useSavingsAggregate.ts frontend/src/hooks/__tests__/useSavingsAggregate.test.ts
git commit -m "feat: thread date param through useSavingsAggregate"
```

---

### Task 4: Frontend `DateSelector` — add a `resolution` prop (day/month/year navigation)

**Files:**
- Modify: `frontend/src/components/DateSelector.tsx`
- Test: `frontend/src/components/__tests__/DateSelector.test.tsx`

**Interfaces:**
- Consumes: nothing new.
- Produces: `DateSelector` gains an optional `resolution?: 'day' | 'month' | 'year'` prop, default `'day'` (so `InsightsPage`'s existing untouched call site keeps its current day-stepping behavior). When `resolution === 'month'`, prev/next step by calendar month and the popup shows react-datepicker's month/year grid (`showMonthYearPicker`); when `'year'`, prev/next step by calendar year and the popup shows the year grid (`showYearPicker`). `availableDates` (a `Set` of ISO **day** strings) is checked by prefix match at month/year resolution — "available" means at least one persisted day falls in that month/year.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/components/__tests__/DateSelector.test.tsx`, as a new `describe` block after the existing one (before the final closing, i.e. append to the file):

```typescript
describe('DateSelector resolution', () => {
  it('steps by month when resolution="month"', () => {
    const selected = new Date(2026, 5, 15); // June 15, 2026
    const onDateChange = vi.fn();

    render(
      <DateSelector
        selectedDate={selected}
        onDateChange={onDateChange}
        resolution="month"
        availableDates={null}
      />
    );

    const [prevButton] = screen.getAllByRole('button');
    fireEvent.click(prevButton);

    expect(onDateChange).toHaveBeenCalledTimes(1);
    const result = onDateChange.mock.calls[0][0] as Date;
    expect(result.getFullYear()).toBe(2026);
    expect(result.getMonth()).toBe(4); // May
  });

  it('steps by year when resolution="year"', () => {
    const selected = new Date(2026, 5, 15);
    const onDateChange = vi.fn();

    render(
      <DateSelector
        selectedDate={selected}
        onDateChange={onDateChange}
        resolution="year"
        availableDates={null}
      />
    );

    const buttons = screen.getAllByRole('button');
    const nextButton = buttons[buttons.length - 1];
    fireEvent.click(nextButton);

    expect(onDateChange).toHaveBeenCalledTimes(1);
    const result = onDateChange.mock.calls[0][0] as Date;
    expect(result.getFullYear()).toBe(2027);
  });

  it('treats a month as available if any persisted day falls inside it', () => {
    const selected = new Date(2026, 5, 15); // June 2026
    const onDateChange = vi.fn();

    render(
      <DateSelector
        selectedDate={selected}
        onDateChange={onDateChange}
        resolution="month"
        availableDates={new Set(['2026-05-20', '2026-06-01'])}
      />
    );

    const [prevButton] = screen.getAllByRole('button');
    expect(prevButton).not.toBeDisabled();
  });

  it('displays just the year when resolution="year"', () => {
    const selected = new Date(2026, 5, 15);

    render(
      <DateSelector selectedDate={selected} onDateChange={vi.fn()} resolution="year" />
    );

    expect(screen.getByText('2026')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/__tests__/DateSelector.test.tsx`
Expected: FAIL — `resolution` prop doesn't exist yet, so navigation still steps by day and the display format is unchanged.

- [ ] **Step 3: Implement**

Replace the full contents of `frontend/src/components/DateSelector.tsx`:

```typescript
import { useState } from 'react';
import { Calendar, ChevronLeft, ChevronRight } from 'lucide-react';
import DatePicker from 'react-datepicker';
import 'react-datepicker/dist/react-datepicker.css';
import { toISODate } from '../utils/timeUtils';

type DateResolution = 'day' | 'month' | 'year';

const DateSelector = ({
  selectedDate,
  onDateChange,
  maxDate = new Date(new Date().setDate(new Date().getDate() + 1)), // Allow selecting up to tomorrow
  minDate = new Date(new Date().setMonth(new Date().getMonth() - 2)), // Set min date to today minus 2 months
  isLoading = false,
  availableDates = null, // Restrict selection to these ISO dates; null = no restriction (e.g. still loading)
  resolution = 'day',
}: {
  selectedDate: Date;
  onDateChange: (date: Date) => void;
  maxDate?: Date;
  minDate?: Date;
  isLoading?: boolean;
  availableDates?: Set<string> | null;
  resolution?: DateResolution;
}) => {
  const [isOpen, setIsOpen] = useState(false);

  // Format date for display, matching the selected resolution's granularity.
  const formatDisplayDate = (date: Date): string => {
    if (resolution === 'month') {
      return date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
    }
    if (resolution === 'year') {
      return String(date.getFullYear());
    }
    return date.toLocaleDateString('sv-SE', {
      weekday: 'short',
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    });
  };

  // availableDates holds day-level ISO strings even at month/year
  // resolution — a month/year counts as available if any persisted day
  // falls inside it.
  const isAvailable = (date: Date): boolean => {
    if (!availableDates) return true;
    if (resolution === 'day') return availableDates.has(toISODate(date));
    const prefix =
      resolution === 'month'
        ? `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
        : `${date.getFullYear()}-`;
    for (const d of availableDates) {
      if (d.startsWith(prefix)) return true;
    }
    return false;
  };

  const stepDate = (from: Date, direction: number): Date => {
    const next = new Date(from);
    if (resolution === 'month') {
      next.setMonth(next.getMonth() + direction, 1);
    } else if (resolution === 'year') {
      next.setFullYear(next.getFullYear() + direction, 0, 1);
    } else {
      next.setDate(next.getDate() + direction);
    }
    return next;
  };

  // Walk day/month/year-by-day-by-step toward `direction` until an
  // available date is found (skipping gaps in the persisted history) or
  // the min/max bound is hit.
  const findNextAvailable = (from: Date, direction: number): Date | null => {
    let candidate = stepDate(from, direction);
    while (candidate >= minDate && candidate <= maxDate) {
      if (isAvailable(candidate)) return candidate;
      candidate = stepDate(candidate, direction);
    }
    return null;
  };

  const navigateDay = (direction: number) => {
    const newDate = findNextAvailable(selectedDate, direction);
    if (newDate) {
      onDateChange(newDate);
    }
  };

  const canNavigate = (direction: number): boolean =>
    findNextAvailable(selectedDate, direction) !== null;

  return (
    <div className="relative">
      <div className="bg-white p-4 rounded-lg shadow flex items-center justify-between" style={{ height: '75px', width: '300px' }}>
        <button
          onClick={() => navigateDay(-1)}
          className="p-1 hover:bg-gray-100 rounded-full disabled:opacity-30 disabled:cursor-not-allowed"
          disabled={selectedDate <= minDate || !canNavigate(-1)}
        >
          <ChevronLeft className="w-5 h-5 text-gray-600" />
        </button>
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="flex items-center space-x-2 px-3 py-2 border border-gray-300 rounded-md hover:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
          disabled={isLoading}
        >
          <Calendar className="w-5 h-5 text-gray-600" />
          <span className="text-gray-700">{formatDisplayDate(selectedDate)}</span>
        </button>
        <button
          onClick={() => navigateDay(1)}
          className="p-1 hover:bg-gray-100 rounded-full disabled:opacity-30 disabled:cursor-not-allowed"
          disabled={selectedDate >= maxDate || !canNavigate(1)}
        >
          <ChevronRight className="w-5 h-5 text-gray-600" />
        </button>
      </div>

      {isLoading && (
        <div className="absolute top-full left-0 right-0 pt-2">
          <div className="flex items-center justify-center space-x-2 text-gray-600">
            <div className="animate-spin h-5 w-5 border-2 border-blue-500 rounded-full border-t-transparent"></div>
            <span className="text-sm">Loading...</span>
          </div>
        </div>
      )}

      {isOpen && (
        <div className="absolute top-20 left-0 z-10 w-64 bg-white rounded-lg shadow-lg border border-gray-200">
          <div className="p-2">
            <DatePicker
              selected={selectedDate}
              onChange={(date: Date | null) => {
                if (date) {
                  onDateChange(date);
                  setIsOpen(false);
                }
              }}
              inline
              minDate={minDate}
              maxDate={maxDate}
              filterDate={isAvailable}
              showMonthYearPicker={resolution === 'month'}
              showYearPicker={resolution === 'year'}
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default DateSelector;
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/__tests__/DateSelector.test.tsx`
Expected: PASS, 7 tests (3 existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DateSelector.tsx frontend/src/components/__tests__/DateSelector.test.tsx
git commit -m "feat: add month/year resolution stepping to DateSelector"
```

---

### Task 5: `SavingsAggregateView` — accept a `date` prop and label cards by the viewed period

**Files:**
- Modify: `frontend/src/components/SavingsAggregateView.tsx`
- Test: `frontend/src/components/__tests__/SavingsAggregateView.test.tsx`

**Interfaces:**
- Consumes: `useSavingsAggregate(period, count?, date?)` from Task 3.
- Produces: `SavingsAggregateView` gains an optional `date?: string` prop (ISO `YYYY-MM-DD`; omit for "now", same convention as everywhere else). Card titles ("Today's Cost" / "Jun 15 Cost" / "June 2026 Cost" / "2026 Cost") are now derived from the *returned bucket's own `startDate`/`label`*, not from the `period` prop alone, so they stay correct when `date` points at a historical period.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/components/__tests__/SavingsAggregateView.test.tsx`, as a new `describe` block appended after the existing one:

```typescript
describe('SavingsAggregateView with a historical date', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('passes the date prop through to fetchSavingsAggregate', async () => {
    const fetchSpy = vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-05-01', 1)],
      count: 1,
    });

    render(<SavingsAggregateView period="day" date="2026-05-01" />);

    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    expect(fetchSpy).toHaveBeenCalledWith('day', 14, '2026-05-01');
  });

  it('titles the cards from the bucket label, not "Today", when browsing a historical month', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [{ ...bucket('2026-05', 1), startDate: '2026-05-01', endDate: '2026-05-31' }],
      count: 1,
    });

    render(<SavingsAggregateView period="month" date="2026-05-15" />);

    await waitFor(() => {
      expect(screen.getByText('May 2026 Cost')).toBeInTheDocument();
    });
    expect(screen.getByText('May 2026 Savings')).toBeInTheDocument();
  });

  it('titles a historical single day by its date, not "Today"', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [{ ...bucket('2026-05-01', 1), startDate: '2026-05-01', endDate: '2026-05-01' }],
      count: 1,
    });

    render(<SavingsAggregateView period="day" date="2026-05-01" />);

    await waitFor(() => {
      expect(screen.getByText(/Cost$/)).toBeInTheDocument();
    });
    expect(screen.queryByText("Today's Cost")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/__tests__/SavingsAggregateView.test.tsx`
Expected: FAIL — `date` prop is currently accepted nowhere, `fetchSavingsAggregate` is called with only `(period, count)`, and titles are always "Today's Cost"/"Today's Savings" for `period="day"`.

- [ ] **Step 3: Implement**

In `frontend/src/components/SavingsAggregateView.tsx`:

1. Add the `toISODate` import (line 1 area, alongside the existing imports):

```typescript
import { toISODate } from '../utils/timeUtils';
```

2. Replace the `SavingsHero` component and the props/hook wiring (lines 26-41 and 43-95 and 102-107) as follows.

Replace:

```typescript
interface SavingsAggregateViewProps {
  period: SavingsAggregatePeriod;
}

const SavingsHero: React.FC<{ bucket: SavingsBucket; period: SavingsAggregatePeriod }> = ({
  bucket,
  period,
}) => {
  const percentSaved =
    bucket.gridOnlyCost.value > 0.001
      ? (bucket.netSavings.value / bucket.gridOnlyCost.value) * 100
      : null;

  const costTitle = period === 'day' ? "Today's Cost" : `${SAVINGS_PERIOD_LABELS[period]} Cost`;
  const savingsTitle =
    period === 'day' ? "Today's Savings" : `${SAVINGS_PERIOD_LABELS[period]} Savings`;
```

with:

```typescript
interface SavingsAggregateViewProps {
  period: SavingsAggregatePeriod;
  date?: string;
}

// Bucket-derived label so titles stay correct when browsing a historical
// date, not just "now" — e.g. "May 2026" instead of always "Month".
const formatPeriodLabel = (period: SavingsAggregatePeriod, bucket: SavingsBucket): string => {
  const start = new Date(`${bucket.startDate}T00:00:00`);
  if (period === 'day') {
    return bucket.startDate === toISODate(new Date())
      ? 'Today'
      : start.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
  if (period === 'month') {
    return start.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
  }
  if (period === 'year') {
    return bucket.label;
  }
  return SAVINGS_PERIOD_LABELS[period];
};

const SavingsHero: React.FC<{ bucket: SavingsBucket; period: SavingsAggregatePeriod }> = ({
  bucket,
  period,
}) => {
  const percentSaved =
    bucket.gridOnlyCost.value > 0.001
      ? (bucket.netSavings.value / bucket.gridOnlyCost.value) * 100
      : null;

  const periodLabel = formatPeriodLabel(period, bucket);
  const costTitle = periodLabel === 'Today' ? "Today's Cost" : `${periodLabel} Cost`;
  const savingsTitle = periodLabel === 'Today' ? "Today's Savings" : `${periodLabel} Savings`;
```

3. Replace the component signature and hook call (lines 102-107):

```typescript
export const SavingsAggregateView: React.FC<SavingsAggregateViewProps> = ({ period, date }) => {
  const [viewMode, setViewMode] = useState<'chart' | 'table'>('chart');
  const { data, loading, error } = useSavingsAggregate(
    period,
    period === 'day' ? DAY_VIEW_COUNT : undefined,
    date
  );
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/__tests__/SavingsAggregateView.test.tsx`
Expected: PASS, all 16 tests (13 existing + 3 new).

- [ ] **Step 5: Run the full frontend suite**

Run: `cd frontend && npx vitest run && npx tsc --noEmit -p .`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/SavingsAggregateView.tsx frontend/src/components/__tests__/SavingsAggregateView.test.tsx
git commit -m "feat: label savings cards from the viewed bucket, not always 'now'"
```

---

### Task 6: `SavingsPage` — Day/Month/Year resolution selector + date picker

**Files:**
- Modify: `frontend/src/pages/SavingsPage.tsx`
- Test: `frontend/src/pages/__tests__/SavingsPage.test.tsx`

**Interfaces:**
- Consumes: `SavingsAggregateView({ period, date? })` from Task 5, `DateSelector({ selectedDate, onDateChange, availableDates, resolution })` from Task 4, `useAvailableDashboardDates()` (existing hook, `frontend/src/hooks/useAvailableDashboardDates.ts` — already fetches `/api/dashboard/available-dates`, which is the same `DailyViewStore`-backed set of persisted days the savings aggregator reads from, so it's the correct source for greying out unavailable days/months/years here too).
- Produces: nothing consumed elsewhere — this is the page's top-level composition.

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `frontend/src/pages/__tests__/SavingsPage.test.tsx`:

```typescript
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import SavingsPage from '../SavingsPage';
import api from '../../lib/api';
import * as scheduleApi from '../../api/scheduleApi';

vi.mock('../../components/SavingsAggregateView', () => ({
  SavingsAggregateView: ({ period, date }: { period: string; date?: string }) => (
    <div data-testid="savings-aggregate-view">
      {period}:{date ?? 'live'}
    </div>
  ),
  SAVINGS_PERIOD_LABELS: { day: 'Today', week: 'Week', month: 'Month', year: 'Year' },
}));

describe('SavingsPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'get').mockResolvedValue({ data: {} });
    vi.spyOn(scheduleApi, 'fetchAvailableDashboardDates').mockResolvedValue(['2026-07-11']);
  });

  it('renders only the savings aggregate view — Scenario Comparison moved to Insights', () => {
    render(<SavingsPage />);

    expect(screen.getByTestId('savings-aggregate-view')).toBeInTheDocument();
    expect(screen.queryByTestId('detailed-savings-analysis')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^overview$/i })).not.toBeInTheDocument();
  });

  it('defaults to the day resolution, live (no date), and lets the header pills change resolution', () => {
    render(<SavingsPage />);

    expect(screen.getByTestId('savings-aggregate-view')).toHaveTextContent('day:live');

    fireEvent.click(screen.getByRole('button', { name: /^month$/i }));
    expect(screen.getByTestId('savings-aggregate-view')).toHaveTextContent('month:live');

    fireEvent.click(screen.getByRole('button', { name: /^year$/i }));
    expect(screen.getByTestId('savings-aggregate-view')).toHaveTextContent('year:live');
  });

  it('does not offer a Week resolution button', () => {
    render(<SavingsPage />);

    expect(screen.queryByRole('button', { name: /^week$/i })).not.toBeInTheDocument();
  });

  it('passes a date to SavingsAggregateView once a non-today date is picked', async () => {
    render(<SavingsPage />);

    // The date-picker button shows the currently selected date; clicking the
    // next-day chevron (2nd of the 3 DateSelector buttons... actually the
    // 3rd, since prev/label/next) moves off "today" and should start
    // passing an explicit date instead of leaving it live.
    const buttons = screen.getAllByRole('button');
    const prevDayButton = buttons.find((b) => b.querySelector('svg.lucide-chevron-left'));
    expect(prevDayButton).toBeDefined();

    fireEvent.click(prevDayButton as HTMLElement);

    expect(screen.getByTestId('savings-aggregate-view').textContent).not.toContain(':live');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/__tests__/SavingsPage.test.tsx`
Expected: FAIL — `SavingsPage` still renders Day/Week/Month/Year buttons with no `DateSelector`, and `SavingsAggregateView` is never called with a `date` prop.

- [ ] **Step 3: Implement**

Replace the full contents of `frontend/src/pages/SavingsPage.tsx`:

```typescript
import React, { useState, useEffect } from 'react';
import { SavingsAggregateView, SAVINGS_PERIOD_LABELS } from '../components/SavingsAggregateView';
import DateSelector from '../components/DateSelector';
import { useAvailableDashboardDates } from '../hooks/useAvailableDashboardDates';
import { SavingsAggregatePeriod } from '../api/scheduleApi';
import { toISODate } from '../utils/timeUtils';
import api from '../lib/api';

type SavingsResolution = Extract<SavingsAggregatePeriod, 'day' | 'month' | 'year'>;

const RESOLUTIONS: SavingsResolution[] = ['day', 'month', 'year'];

const SavingsPage: React.FC = () => {
  const [systemMode, setSystemMode] = useState<string>('normal');
  const [resolution, setResolution] = useState<SavingsResolution>('day');
  const [selectedDate, setSelectedDate] = useState<Date>(new Date());
  const availableDates = useAvailableDashboardDates();

  useEffect(() => {
    api.get('/api/settings')
      .then(({ data }) => {
        const dm = data.demoMode || data.demo_mode || {};
        setSystemMode(dm.enabled ? 'demo' : 'normal');
      })
      .catch(() => {});
  }, []);

  const isLive = toISODate(selectedDate) === toISODate(new Date());

  return (
    <div className="space-y-6">
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Savings Report</h1>
            <p className="text-gray-600 dark:text-gray-300">
              What you actually paid the grid, and how much solar and battery saved you against grid-only power, over time.
            </p>
            {systemMode === 'demo' && (
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                All savings are theoretical estimates based on optimization plans
              </p>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex bg-gray-100 dark:bg-gray-700 rounded-lg p-1 w-fit">
              {RESOLUTIONS.map((r) => (
                <button
                  key={r}
                  onClick={() => setResolution(r)}
                  className={`px-3 py-1 rounded-md text-sm font-medium capitalize transition-colors ${
                    resolution === r
                      ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                      : 'text-gray-600 dark:text-gray-300'
                  }`}
                >
                  {SAVINGS_PERIOD_LABELS[r]}
                </button>
              ))}
            </div>
            <DateSelector
              selectedDate={selectedDate}
              onDateChange={setSelectedDate}
              availableDates={availableDates}
              resolution={resolution}
            />
          </div>
        </div>
      </div>

      <SavingsAggregateView
        period={resolution}
        date={isLive ? undefined : toISODate(selectedDate)}
      />
    </div>
  );
};

export default SavingsPage;
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/__tests__/SavingsPage.test.tsx`
Expected: PASS, all 4 tests.

- [ ] **Step 5: Run the full frontend suite and type-check**

Run: `cd frontend && npx vitest run && npx tsc --noEmit -p . && npm run lint:fix`
Expected: All tests pass; `tsc` clean; lint shows no new errors (pre-existing warnings elsewhere are fine, don't fix unrelated files).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/SavingsPage.tsx frontend/src/pages/__tests__/SavingsPage.test.tsx
git commit -m "feat: replace Day/Week/Month/Year toggle with resolution + date picker on Savings page"
```

---

### Task 7: Manual verification in the browser

**Files:** none (verification only).

- [ ] **Step 1: Start the dev stack**

Run: `docker-compose up -d` (or `cd frontend && npm run dev` alongside the existing backend dev process, per whichever this repo's checkout is already using).

- [ ] **Step 2: Walk the golden path**

In the browser, open the Savings page and:
1. Confirm it defaults to **Day** resolution with today's date, showing the same Cost/Savings cards as before this branch.
2. Click **Month**, then **Year** — confirm the cards update and titles read "<Month> <Year> Cost"/"Savings" and "<Year> Cost"/"Savings" respectively, with data for the current month/year.
3. Open the date picker and step back a day/month/year (as available) — confirm the card titles and values change to the historical period, and the History chart/table below still renders.
4. Confirm the percent-saved badge on the Savings card still shows green for positive, red for negative.

- [ ] **Step 3: Report findings**

If everything matches, this task is done — no code change. If something looks wrong, note the specific mismatch (screenshot or exact text) so it becomes a follow-up fix task before merging.
