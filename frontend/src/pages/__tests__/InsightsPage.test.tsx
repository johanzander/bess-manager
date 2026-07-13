import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import InsightsPage from '../InsightsPage';

vi.mock('../../components/PredictionAccuracyView', () => ({
  default: () => <div data-testid="prediction-accuracy-view">Prediction Accuracy</div>,
}));

vi.mock('../../components/ConsumptionForecastComparison', () => ({
  default: () => <div data-testid="consumption-forecast-comparison">Consumption Forecast</div>,
}));

vi.mock('../../components/BatteryActionsTable', () => ({
  BatteryActionsTable: ({ date }: { date?: string }) => (
    <div data-testid="battery-actions-table">{date ?? 'today'}</div>
  ),
}));

vi.mock('../../components/DetailedSavingsAnalysis', () => ({
  DetailedSavingsAnalysis: () => <div data-testid="detailed-savings-analysis">Scenario Comparison</div>,
}));

vi.mock('../../components/DateSelector', () => ({
  default: () => <div data-testid="date-selector">Date Selector</div>,
}));

vi.mock('../../hooks/useAvailableDashboardDates', () => ({
  useAvailableDashboardDates: () => null,
}));

describe('InsightsPage', () => {
  it('defaults to the Forecast Accuracy tab', () => {
    render(<InsightsPage />);

    expect(screen.getByTestId('prediction-accuracy-view')).toBeInTheDocument();
    expect(screen.queryByTestId('battery-actions-table')).not.toBeInTheDocument();
    expect(screen.queryByTestId('detailed-savings-analysis')).not.toBeInTheDocument();
  });

  it('shows the date picker only on the Battery Actions tab', () => {
    render(<InsightsPage />);
    expect(screen.queryByTestId('date-selector')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Battery Actions' }));
    expect(screen.getByTestId('date-selector')).toBeInTheDocument();
    expect(screen.getByTestId('battery-actions-table')).toHaveTextContent('today');

    fireEvent.click(screen.getByRole('button', { name: 'Scenario Comparison' }));
    expect(screen.queryByTestId('date-selector')).not.toBeInTheDocument();
    expect(screen.getByTestId('detailed-savings-analysis')).toBeInTheDocument();
    expect(screen.queryByTestId('battery-actions-table')).not.toBeInTheDocument();
  });
});
