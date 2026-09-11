import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import DashboardPage from '../DashboardPage';
import api from '../../lib/api';
import * as scheduleApi from '../../api/scheduleApi';
import { toISODate } from '../../utils/timeUtils';

// Heavy child components are faked so the tests can assert (a) which `date`
// each date-aware child receives and (b) that live-only widgets are hidden on
// historical days. Same approach as SavingsPage.test.tsx.
vi.mock('../../components/EnergyFlowCards', () => ({
  default: ({ date }: { date?: string }) => (
    <div data-testid="energy-flow-cards">{date ?? 'live'}</div>
  ),
}));
vi.mock('../../components/BatteryModeTimeline', () => ({
  BatteryModeTimeline: ({ date }: { date?: string }) => (
    <div data-testid="battery-mode-timeline">{date ?? 'live'}</div>
  ),
}));
vi.mock('../../components/EnergyFlowChart', () => ({
  EnergyFlowChart: ({ dailyViewData }: { dailyViewData?: unknown[] }) => (
    <div data-testid="energy-flow-chart">{dailyViewData?.length ?? 0}</div>
  ),
}));
vi.mock('../../components/BatteryLevelChart', () => ({
  BatteryLevelChart: () => <div data-testid="battery-level-chart" />,
}));
vi.mock('../../components/SystemStatusCard', () => ({
  default: () => <div data-testid="system-status-card" />,
  StatusCard: () => null,
}));
vi.mock('../../components/AlertBanner', () => ({ default: () => null }));
vi.mock('../../components/DeprecationBanner', () => ({ default: () => null }));
vi.mock('../../components/RuntimeFailureAlerts', () => ({
  RuntimeFailureAlerts: () => null,
}));
vi.mock('../../hooks/useRuntimeFailures', () => ({
  useRuntimeFailures: () => ({
    failures: [],
    dismissFailure: vi.fn(),
    dismissAllFailures: vi.fn(),
  }),
}));
vi.mock('../../hooks/useHealthRecoveries', () => ({
  useHealthRecoveries: () => ({ recoveries: [], acknowledgeRecoveries: vi.fn() }),
}));
vi.mock('../../hooks/useUserPreferences', () => ({
  useUserPreferences: () => ({
    dataResolution: 'quarter-hourly',
    setDataResolution: vi.fn(),
    showSellPrice: false,
    setShowSellPrice: vi.fn(),
  }),
}));

const today = new Date();
const yesterday = new Date();
yesterday.setDate(today.getDate() - 1);

const renderDashboard = () =>
  render(
    <DashboardPage
      onLoadingChange={vi.fn()}
      settings={{} as never}
    />,
  );

describe('DashboardPage historical day navigation', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(scheduleApi, 'fetchAvailableDashboardDates').mockResolvedValue([
      toISODate(yesterday),
      toISODate(today),
    ]);
    vi.spyOn(api, 'get').mockImplementation((url: string) => {
      if (url === '/api/dashboard') {
        return Promise.resolve({
          data: {
            hourlyData: [{ hour: 0 }],
            currentHour: 0,
            summary: {},
            totals: {},
          },
        });
      }
      if (url === '/api/dashboard-health-summary') {
        return Promise.resolve({
          data: {
            hasCriticalErrors: false,
            hasWarnings: false,
            criticalIssues: [],
            totalCriticalIssues: 0,
            timestamp: '',
          },
        });
      }
      if (url === '/api/historical-data-status') {
        return Promise.resolve({ data: { isIncomplete: false } });
      }
      return Promise.resolve({ data: {} });
    });
  });

  it('defaults to today (live) and shows the live System Overview', async () => {
    renderDashboard();

    expect(await screen.findByTestId('energy-flow-cards')).toHaveTextContent('live');
    expect(screen.getByTestId('battery-mode-timeline')).toHaveTextContent('live');
    expect(screen.getByText('System Overview')).toBeInTheDocument();
  });

  it('threads an explicit date to the cards and hides live-only widgets on a past day', async () => {
    renderDashboard();
    await screen.findByTestId('energy-flow-cards');

    const prevDayButton = screen
      .getAllByRole('button')
      .find((b) => b.querySelector('svg.lucide-chevron-left'));
    expect(prevDayButton).toBeDefined();
    fireEvent.click(prevDayButton as HTMLElement);

    await waitFor(() => {
      expect(screen.getByTestId('energy-flow-cards')).toHaveTextContent(
        toISODate(yesterday),
      );
    });
    expect(screen.getByTestId('battery-mode-timeline')).toHaveTextContent(
      toISODate(yesterday),
    );
    // Live-only widgets must not render for a historical day.
    expect(screen.queryByText('System Overview')).not.toBeInTheDocument();
    expect(screen.queryByTestId('system-status-card')).not.toBeInTheDocument();
  });
});
