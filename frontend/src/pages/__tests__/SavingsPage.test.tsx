import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import SavingsPage from '../SavingsPage';
import api from '../../lib/api';

vi.mock('../../components/SavingsAggregateView', () => ({
  SavingsAggregateView: ({ period }: { period: string }) => (
    <div data-testid="savings-aggregate-view">{period}</div>
  ),
  SAVINGS_PERIODS: ['day', 'week', 'month', 'year'],
  SAVINGS_PERIOD_LABELS: { day: 'Today', week: 'Week', month: 'Month', year: 'Year' },
}));

describe('SavingsPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'get').mockResolvedValue({ data: {} });
  });

  it('renders only the savings aggregate view — Scenario Comparison moved to Insights', () => {
    render(<SavingsPage />);

    expect(screen.getByTestId('savings-aggregate-view')).toBeInTheDocument();
    expect(screen.queryByTestId('detailed-savings-analysis')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^overview$/i })).not.toBeInTheDocument();
  });

  it('defaults to the day period (so it has data even before a full week exists) and lets the header pills change it', () => {
    render(<SavingsPage />);

    expect(screen.getByTestId('savings-aggregate-view')).toHaveTextContent('day');

    fireEvent.click(screen.getByRole('button', { name: /^week$/i }));
    expect(screen.getByTestId('savings-aggregate-view')).toHaveTextContent('week');

    fireEvent.click(screen.getByRole('button', { name: /^month$/i }));
    expect(screen.getByTestId('savings-aggregate-view')).toHaveTextContent('month');
  });
});
