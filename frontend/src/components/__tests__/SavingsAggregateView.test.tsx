import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
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

  it('renders a row per bucket for the default period', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-W28', 1)],
      count: 1,
    });

    render(<SavingsAggregateView />);

    // Default view is the chart, which Recharts doesn't meaningfully render
    // under jsdom (ResponsiveContainer measures 0x0 with no layout engine).
    // Switch to the table view, which renders plain DOM the bucket data.
    fireEvent.click(screen.getByRole('button', { name: /table/i }));

    await waitFor(() => {
      expect(screen.getByText('2026-W28')).toBeInTheDocument();
    });
    expect(screen.getByText('3.00 EUR')).toBeInTheDocument();
  });

  it('defaults to the chart view without crashing', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-W28', 1)],
      count: 1,
    });

    render(<SavingsAggregateView />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^chart$/i })).toBeInTheDocument();
    });
    expect(screen.getByText('Savings History')).toBeInTheDocument();
    expect(screen.queryByText(/could not load savings history/i)).not.toBeInTheDocument();
    // The table view must not be rendered by default - this guards against the
    // regression this branch already reintroduced once (default silently
    // reverting to 'table').
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('refetches with the new period when the toggle is changed', async () => {
    const fetchSpy = vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [bucket('2026-07', 5)],
      count: 1,
    });

    render(<SavingsAggregateView />);

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith('week', undefined));

    fireEvent.click(screen.getByRole('button', { name: /month/i }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith('month', undefined));
  });

  it('shows an empty state when there are no buckets with data', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({ buckets: [], count: 0 });

    render(<SavingsAggregateView />);

    await waitFor(() => {
      expect(screen.getByText(/no savings history yet/i)).toBeInTheDocument();
    });
  });
});
