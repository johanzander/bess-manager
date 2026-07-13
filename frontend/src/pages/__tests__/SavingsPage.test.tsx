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
