import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import SavingsPage from '../SavingsPage';
import * as useSettingsHook from '../../hooks/useSettings';
import * as useUserPreferencesHook from '../../hooks/useUserPreferences';
import api from '../../lib/api';

vi.mock('../../components/DetailedSavingsAnalysis', () => ({
  DetailedSavingsAnalysis: () => <div data-testid="detailed-savings-analysis">Detailed Savings Analysis</div>,
}));

vi.mock('../../components/SavingsAggregateView', () => ({
  SavingsAggregateView: () => <div data-testid="savings-aggregate-view">Savings Aggregate View</div>,
}));

describe('SavingsPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();

    vi.spyOn(useSettingsHook, 'useSettings').mockReturnValue({
      batterySettings: null,
      electricitySettings: null,
      isLoading: false,
      error: null,
    });

    vi.spyOn(useUserPreferencesHook, 'useUserPreferences').mockReturnValue({
      preferences: { dataResolution: 'quarter-hourly', showSellPrice: false },
      setPreferences: vi.fn(),
      dataResolution: 'quarter-hourly',
      setDataResolution: vi.fn(),
      showSellPrice: false,
      setShowSellPrice: vi.fn(),
    });

    vi.spyOn(api, 'get').mockResolvedValue({ data: {} });
  });

  it('renders the Scenario Comparison view and the savings aggregate view, with no Overview toggle', () => {
    render(<SavingsPage />);

    expect(screen.queryByRole('button', { name: /^overview$/i })).not.toBeInTheDocument();
    expect(screen.getByTestId('savings-aggregate-view')).toBeInTheDocument();
    expect(screen.getByTestId('detailed-savings-analysis')).toBeInTheDocument();
  });
});
