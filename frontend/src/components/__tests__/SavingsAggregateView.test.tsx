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

  it('requests a rolling window of days for the "day" period, not just today', async () => {
    const fetchSpy = vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-07-10', 1)],
      count: 1,
    });

    render(<SavingsAggregateView period="day" />);

    // Previously this always requested count=1 (today only), so yesterday was
    // invisible until it rolled into the week total. Now it asks for a window.
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith('day', 14, undefined));
  });

  it('omits rows for periods with no recorded day, instead of a zeroed-out row', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-07-10', 0), bucket('2026-07-11', 1)],
      count: 2,
    });

    render(<SavingsAggregateView period="day" />);

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
