import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { SavingsAggregateView } from '../SavingsAggregateView';
import * as scheduleApi from '../../api/scheduleApi';

const bucket = (label: string, dayCount: number) => ({
  label,
  startDate: '2026-07-06',
  endDate: '2026-07-12',
  dayCount,
  importKwh: { value: 1, display: '1.0', unit: 'kWh', text: '1.0 kWh' },
  importEur: { value: 2, display: '2.00', unit: 'EUR', text: '2.00 EUR' },
  exportKwh: { value: 2, display: '2.0', unit: 'kWh', text: '2.0 kWh' },
  exportEur: { value: 2, display: '2.00', unit: 'EUR', text: '2.00 EUR' },
  gridCost: { value: 0, display: '0.00', unit: 'EUR', text: '0.00 EUR' },
  gridOnlyCost: { value: 5, display: '5.00', unit: 'EUR', text: '5.00 EUR' },
  netSavings: { value: 4.5, display: '4.50', unit: 'EUR', text: '4.50 EUR' },
  solarSavings: { value: 2.5, display: '2.50', unit: 'EUR', text: '2.50 EUR' },
  batterySavings: { value: 2, display: '2.00', unit: 'EUR', text: '2.00 EUR' },
  batteryCycleCost: { value: 0.1, display: '0.10', unit: 'EUR', text: '0.10 EUR' },
  savingsVsGridOnly: { value: 3, display: '3.00', unit: 'EUR', text: '3.00 EUR' },
  solarKwh: { value: 1, display: '1.0', unit: 'kWh', text: '1.0 kWh' },
  batteryChargedKwh: { value: 0, display: '0.0', unit: 'kWh', text: '0.0 kWh' },
  batteryDischargedKwh: { value: 0, display: '0.0', unit: 'kWh', text: '0.0 kWh' },
});

describe('SavingsAggregateView', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders a row per bucket for the given period', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-W28', 1)],
      count: 1,
    });

    render(<SavingsAggregateView period="week" />);

    // Default view is the chart, which Recharts doesn't meaningfully render
    // under jsdom (ResponsiveContainer measures 0x0 with no layout engine).
    // Switch to the table view, which renders plain DOM the bucket data.
    fireEvent.click(screen.getByRole('button', { name: /table/i }));

    await waitFor(() => {
      expect(screen.getByText('2026-W28')).toBeInTheDocument();
    });
    expect(screen.getAllByText('4.50 EUR').length).toBeGreaterThan(0);
  });

  it('defaults to the chart view without crashing', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-W28', 1)],
      count: 1,
    });

    render(<SavingsAggregateView period="week" />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^chart$/i })).toBeInTheDocument();
    });
    expect(screen.getByText(/net savings/i)).toBeInTheDocument();
    expect(screen.queryByText(/could not load savings history/i)).not.toBeInTheDocument();
    // The table view must not be rendered by default - this guards against the
    // regression this branch already reintroduced once (default silently
    // reverting to 'table').
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('refetches when the period prop changes', async () => {
    const fetchSpy = vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-07', 5)],
      count: 1,
    });

    const { rerender } = render(<SavingsAggregateView period="week" />);

    // The hero card always requests exactly one bucket for the selected
    // period itself; the History drill-down's exact params vary with
    // "today", so only the stable hero call is asserted here.
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith('week', 1, undefined));

    rerender(<SavingsAggregateView period="month" />);

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith('month', 1, undefined));
  });

  it('shows an empty state when there are no buckets with data', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({ buckets: [], count: 0 });

    render(<SavingsAggregateView period="week" />);

    await waitFor(() => {
      expect(screen.getByText(/no savings history yet/i)).toBeInTheDocument();
    });
  });

  it('shows the hero cards for the selected period even when it has no recorded data', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-05', 0)],
      count: 1,
    });

    render(<SavingsAggregateView period="month" />);

    // The empty month is still the selected period, so its (zeroed-out)
    // cards render instead of the whole hero disappearing.
    await waitFor(() => {
      expect(screen.getByText('Net Cost')).toBeInTheDocument();
    });
    expect(screen.getByText('Net Savings')).toBeInTheDocument();
    // The History section below still hides periods with no recorded day.
    expect(screen.getByText(/no savings history yet/i)).toBeInTheDocument();
  });

  it('shows Grid Only in the savings card and Grid-Only Cost in the table', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-W28', 1)],
      count: 1,
    });

    render(<SavingsAggregateView period="week" />);

    // The savings card shows the grid-only baseline next to Net Savings, so
    // the user can see what was saved against.
    await waitFor(() => {
      expect(screen.getByText('Grid Only')).toBeInTheDocument();
    });
    expect(screen.getAllByText('5.00 EUR').length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: /table/i }));

    await waitFor(() => {
      expect(screen.getByText('2026-W28')).toBeInTheDocument();
    });
    // In the table it's useful context for how Net Savings was derived.
    expect(screen.getByText('Grid-Only Cost')).toBeInTheDocument();
  });

  it('renders a Net Savings column populated from bucket.netSavings.text, not savingsVsGridOnly', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-W28', 1)],
      count: 1,
    });

    render(<SavingsAggregateView period="week" />);

    fireEvent.click(screen.getByRole('button', { name: /table/i }));

    await waitFor(() => {
      expect(screen.getAllByText(/net savings/i).length).toBeGreaterThan(0);
    });
    // netSavings (4.50 EUR) is distinct from savingsVsGridOnly (3.00 EUR) in
    // the fixture - a wrong-field regression would show 3.00 EUR instead.
    expect(screen.getAllByText('4.50 EUR').length).toBeGreaterThan(0);
    expect(screen.queryByText('3.00 EUR')).not.toBeInTheDocument();
  });

  it('omits rows for periods with no recorded day, instead of a zeroed-out row', async () => {
    // Day resolution's History is now an hourly drill-down (see the
    // dedicated describe block below), so this "omit empty periods"
    // behavior is exercised here via week, which still uses the
    // savings-aggregate rolling-window path.
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-07-10', 0), bucket('2026-07-11', 1)],
      count: 2,
    });

    render(<SavingsAggregateView period="week" />);

    fireEvent.click(screen.getByRole('button', { name: /table/i }));

    await waitFor(() => {
      expect(screen.getByText('2026-07-11')).toBeInTheDocument();
    });
    expect(screen.queryByText('2026-07-10')).not.toBeInTheDocument();
  });

  it('does not render a Days column', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-W28', 1)],
      count: 1,
    });

    render(<SavingsAggregateView period="week" />);

    fireEvent.click(screen.getByRole('button', { name: /table/i }));

    await waitFor(() => {
      expect(screen.getByText('2026-W28')).toBeInTheDocument();
    });
    expect(screen.queryByText('Days')).not.toBeInTheDocument();
  });

  it('shows just the EUR value (no kWh) on the Solar/Battery Contribution rows', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [
        {
          ...bucket('2026-W28', 1),
          solarKwh: { value: 20, display: '20.0', unit: 'kWh', text: '20.0 kWh' },
          batteryDischargedKwh: { value: 10, display: '10.0', unit: 'kWh', text: '10.0 kWh' },
        },
      ],
      count: 1,
    });

    render(<SavingsAggregateView period="week" />);

    await waitFor(() => {
      expect(screen.getByText('Solar Contribution')).toBeInTheDocument();
    });
    expect(screen.queryByText(/kWh\)/)).not.toBeInTheDocument();
  });

  it('groups the table into a Grid cost section (first) and a Savings section (second)', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-W28', 1)],
      count: 1,
    });

    render(<SavingsAggregateView period="week" />);

    fireEvent.click(screen.getByRole('button', { name: /table/i }));

    await waitFor(() => {
      expect(screen.getAllByText(/grid cost/i).length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText(/savings breakdown/i).length).toBeGreaterThan(0);
    expect(screen.getByText('Import Cost')).toBeInTheDocument();
    expect(screen.getByText('Export Revenue')).toBeInTheDocument();

    // Grid columns (Import Cost) must come before Savings columns (From Solar)
    // in document order — cost is primary, savings is secondary.
    const headers = screen.getAllByRole('columnheader').map((el) => el.textContent);
    const importIdx = headers.findIndex((h) => h === 'Import Cost');
    const solarIdx = headers.findIndex((h) => h === 'From Solar');
    expect(importIdx).toBeGreaterThan(-1);
    expect(solarIdx).toBeGreaterThan(-1);
    expect(importIdx).toBeLessThan(solarIdx);
  });

  it('renders From Solar and From Battery columns in the table', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-W28', 1)],
      count: 1,
    });

    render(<SavingsAggregateView period="week" />);

    fireEvent.click(screen.getByRole('button', { name: /table/i }));

    await waitFor(() => {
      expect(screen.getByText('From Solar')).toBeInTheDocument();
    });
    expect(screen.getByText('From Battery')).toBeInTheDocument();
    // 2.50 EUR appears both in the hero card and this table row now that
    // the hero no longer suffixes a kWh value to disambiguate them.
    expect(screen.getAllByText('2.50 EUR').length).toBeGreaterThan(0);
    expect(screen.getAllByText('2.00 EUR').length).toBeGreaterThan(0);
  });

  it('never renders Battery Wear, even when batteryCycleCost is non-zero', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-W28', 1)],
      count: 1,
    });

    render(<SavingsAggregateView period="week" />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^chart$/i })).toBeInTheDocument();
    });
    expect(screen.queryByText(/battery wear/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /table/i }));

    await waitFor(() => {
      expect(screen.getByText('2026-W28')).toBeInTheDocument();
    });
    expect(screen.queryByText(/battery wear/i)).not.toBeInTheDocument();
  });
});

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

    // The hero always requests exactly one day-level bucket for the
    // selected date; Day resolution's History no longer requests a
    // rolling window via fetchSavingsAggregate (it uses the dashboard's
    // hourly data instead — see the dedicated describe block below).
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    expect(fetchSpy).toHaveBeenCalledWith('day', 1, '2026-05-01');
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

    // "Cost$" alone is ambiguous: the StatusCard body always renders a
    // "Net Cost" label regardless of the card title, so scope to the
    // bucket-derived title ("May 1 Cost") rather than a generic suffix match.
    await waitFor(() => {
      expect(screen.getByText('May 1 Cost')).toBeInTheDocument();
    });
    expect(screen.queryByText("Today's Cost")).not.toBeInTheDocument();
  });
});

describe('SavingsAggregateView History drill-down', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date('2026-08-20T12:00:00'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('drills into the months of the selected year, not a trailing window of years', async () => {
    const fetchSpy = vi
      .spyOn(scheduleApi, 'fetchSavingsAggregate')
      .mockImplementation(async (_period, count) => {
        if (count === 1) {
          return { buckets: [{ ...bucket('2024', 1), startDate: '2024-01-01' }], count: 1 };
        }
        return { buckets: [bucket('2024-12', 1)], count: 1 };
      });

    render(<SavingsAggregateView period="year" date="2024-03-15" />);

    // The selected year (2024) has fully elapsed by the fake "today"
    // (2026-08-20), so History should request all 12 of its months,
    // anchored at its last day — not a trailing window of year buckets
    // (the hero's own count=1 'year' call is expected and separate).
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith('month', 12, '2024-12-31'));
  });

  it('drills into the days of the selected month, not a trailing window of months', async () => {
    const fetchSpy = vi
      .spyOn(scheduleApi, 'fetchSavingsAggregate')
      .mockImplementation(async (_period, count) => {
        if (count === 1) {
          return { buckets: [{ ...bucket('2024-02', 1), startDate: '2024-02-01' }], count: 1 };
        }
        return { buckets: [bucket('2024-02-15', 1)], count: 1 };
      });

    render(<SavingsAggregateView period="month" date="2024-02-10" />);

    // February 2024 (a leap year) has fully elapsed by the fake "today",
    // so History should request all 29 of its days, anchored at its last
    // day — not a trailing window of month buckets (the hero's own
    // count=1 'month' call is expected and separate).
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith('day', 29, '2024-02-29'));
  });

  it('labels the History section by the drilled-down granularity', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockImplementation(async (_period, count) => {
      if (count === 1) {
        return { buckets: [{ ...bucket('2024', 1), startDate: '2024-01-01' }], count: 1 };
      }
      return { buckets: [bucket('2024-12', 1)], count: 1 };
    });

    render(<SavingsAggregateView period="year" date="2024-03-15" />);

    await waitFor(() => {
      expect(screen.getByText('Months in 2024')).toBeInTheDocument();
    });
  });

  it('caps the drill-down at today for the in-progress current month', async () => {
    // Fake "today" is 2026-08-20; viewing the current month (no explicit
    // date) must not request days past today.
    const fetchSpy = vi
      .spyOn(scheduleApi, 'fetchSavingsAggregate')
      .mockResolvedValue({ buckets: [bucket('2026-08', 1)], count: 1 });

    render(<SavingsAggregateView period="month" />);

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith('day', 20, '2026-08-20'));
  });
});

describe('SavingsAggregateView Day-resolution hourly drill-down', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  const hourlyItem = (
    period: number,
    overrides: Partial<{
      importCost: number;
      exportRevenue: number;
      gridCost: number;
      gridOnlyCost: number;
      solarSavings: number;
      batterySavings: number;
      netSavings: number;
    }> = {}
  ) => {
    const v = (value: number) => ({ value, display: value.toFixed(2), unit: 'EUR', text: `${value.toFixed(2)} EUR` });
    return {
      hour: Math.floor(period / 4),
      period,
      dataSource: 'actual' as const,
      solarProduction: v(0),
      homeConsumption: v(0),
      gridImported: v(0),
      gridExported: v(0),
      batteryCharged: v(0),
      batteryDischarged: v(0),
      batterySocStart: v(0),
      batterySocEnd: v(0),
      batterySoeEnd: v(0),
      buyPrice: v(0),
      sellPrice: v(0),
      importCost: v(overrides.importCost ?? 0),
      exportRevenue: v(overrides.exportRevenue ?? 0),
      hourlyCost: v(0),
      hourlySavings: v(0),
      batteryCycleCost: v(0),
      gridOnlyCost: v(overrides.gridOnlyCost ?? 10),
      solarOnlyCost: v(6),
      solarSavings: v(overrides.solarSavings ?? 4),
      batterySavings: v(overrides.batterySavings ?? 4),
      netSavings: v(overrides.netSavings ?? 8),
      gridCost: v(overrides.gridCost ?? 2),
      gridImportNeeded: v(0),
      solarExcess: v(0),
      batteryAction: null,
    };
  };

  it('fetches dashboard hourly data (not a savings-aggregate day history) when period is day', async () => {
    const savingsSpy = vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-07-11', 1)],
      count: 1,
    });
    const dashboardSpy = vi.spyOn(scheduleApi, 'fetchDashboardData').mockResolvedValue({
      hourlyData: [hourlyItem(0), hourlyItem(4)],
    });

    render(<SavingsAggregateView period="day" date="2026-07-11" />);

    await waitFor(() => expect(dashboardSpy).toHaveBeenCalledWith('2026-07-11', 'quarter-hourly'));
    // The hero still requests exactly one day-level bucket for its own
    // totals; History no longer requests a rolling window of days.
    expect(savingsSpy).toHaveBeenCalledWith('day', 1, '2026-07-11');
    expect(savingsSpy).not.toHaveBeenCalledWith('day', 14, expect.anything());
  });

  it('labels the History section "Hours in <day>" and shows HH:MM rows', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [{ ...bucket('2026-07-11', 1), startDate: '2026-07-11', endDate: '2026-07-11' }],
      count: 1,
    });
    vi.spyOn(scheduleApi, 'fetchDashboardData').mockResolvedValue({
      hourlyData: [hourlyItem(0), hourlyItem(4)], // 00:00 and 01:00
    });

    render(<SavingsAggregateView period="day" date="2026-07-11" />);

    await waitFor(() => {
      expect(screen.getByText(/^Hours in /)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /table/i }));

    await waitFor(() => {
      expect(screen.getByText('00:00')).toBeInTheDocument();
    });
    expect(screen.getByText('01:00')).toBeInTheDocument();
  });

  it('renders the API-provided Net Savings and Battery Contribution for hourly rows, not a re-derived value', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [{ ...bucket('2026-07-11', 1), startDate: '2026-07-11', endDate: '2026-07-11' }],
      count: 1,
    });
    vi.spyOn(scheduleApi, 'fetchDashboardData').mockResolvedValue({
      // netSavings/batterySavings are deliberately set to values that do
      // NOT match gridOnlyCost/solarOnlyCost/gridCost arithmetic, so this
      // test fails if the component re-derives them instead of reading
      // the API's own fields.
      hourlyData: [hourlyItem(0, { netSavings: 99, batterySavings: 77 })],
    });

    render(<SavingsAggregateView period="day" date="2026-07-11" />);

    fireEvent.click(screen.getByRole('button', { name: /table/i }));

    await waitFor(() => {
      expect(screen.getByText('00:00')).toBeInTheDocument();
    });
    expect(screen.getByText('99.00 EUR')).toBeInTheDocument();
    expect(screen.getByText('77.00 EUR')).toBeInTheDocument();
  });

  it('does not affect the History drill-down for month/year resolutions', async () => {
    const dashboardSpy = vi.spyOn(scheduleApi, 'fetchDashboardData');
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [{ ...bucket('2026-07', 1), startDate: '2026-07-01', endDate: '2026-07-31' }],
      count: 1,
    });

    render(<SavingsAggregateView period="month" date="2026-07-15" />);

    await waitFor(() => {
      expect(screen.getByText('Net Cost')).toBeInTheDocument();
    });
    expect(dashboardSpy).not.toHaveBeenCalled();
  });
});
