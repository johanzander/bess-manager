import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import api from '../../lib/api';
import PerformanceView from '../PerformanceView';

describe('Weekly Performance coverage', () => {
  it('withholds unsupported financial claims when history is incomplete', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce({
      data: {
        performance: {
          startDate: '2026-09-07',
          endDate: '2026-09-13',
          timezone: 'Europe/Helsinki',
          currency: 'EUR',
          verifiedPeriods: 671,
          expectedPeriods: 672,
          coveragePercent: 99.85,
          availableWeeks: ['2026-09-07'],
          status: 'insufficient_data',
          issues: ['Missing historical quarter.'],
          daily: [],
          periods: [],
          capturedPercent: null,
          missedSavings: null,
          actual: null,
          optimal: null,
        },
      },
    });
    render(<PerformanceView />);
    await waitFor(() => expect(screen.getByText(/Comparison withheld/)).toBeInTheDocument());
    expect(screen.getByText('Missing historical quarter.')).toBeInTheDocument();
    expect(screen.queryByText('Actual net grid cost')).not.toBeInTheDocument();
    expect(screen.getByText(/Missed savings and captured savings: N\/A/)).toBeInTheDocument();
    vi.restoreAllMocks();
  });
});
