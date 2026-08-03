import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

// Mock the prediction analysis hooks before importing the component
vi.mock('../../hooks/usePredictionAnalysis', () => ({
  usePredictionSnapshots: vi.fn(),
  useSnapshotToSnapshotComparison: vi.fn(),
}));

import PredictionAnalysisView from '../PredictionAnalysisView';
import {
  usePredictionSnapshots,
  useSnapshotToSnapshotComparison,
} from '../../hooks/usePredictionAnalysis';

const fv = (value: number, display: string, unit = '') => ({
  value,
  display,
  unit,
  text: unit ? `${display} ${unit}` : display,
});

const dataPoint = () => ({
  solar: fv(1, '1.00', 'kWh'),
  consumption: fv(1, '1.00', 'kWh'),
  batteryAction: fv(0, '0.00', 'kWh'),
  batterySoe: fv(10, '10.00', 'kWh'),
  gridImport: fv(0, '0.00', 'kWh'),
  gridExport: fv(0, '0.00', 'kWh'),
  cost: fv(0.1, '0.10', 'EUR'),
  gridOnlyCost: fv(0.2, '0.20', 'EUR'),
  savings: fv(0.1, '0.10', 'EUR'),
  dataSource: 'actual',
});

const deltaPoint = () => ({
  solar: fv(0, '0.00', 'kWh'),
  consumption: fv(0, '0.00', 'kWh'),
  batteryAction: fv(0, '0.00', 'kWh'),
  batterySoe: fv(0, '0.00', 'kWh'),
  gridImport: fv(0, '0.00', 'kWh'),
  gridExport: fv(0, '0.00', 'kWh'),
  cost: fv(0, '0.00', 'EUR'),
  gridOnlyCost: fv(0, '0.00', 'EUR'),
  savings: fv(0, '0.00', 'EUR'),
});

const baseComparison = {
  snapshotAPeriod: 24,
  snapshotATimestamp: '2026-07-29T06:00:00Z',
  snapshotBPeriod: 40,
  snapshotBTimestamp: '2026-07-29T10:00:00Z',
  periodComparisons: [
    {
      period: 24,
      snapshotA: dataPoint(),
      snapshotB: dataPoint(),
      delta: deltaPoint(),
    },
  ],
  growattScheduleA: [] as unknown[],
  growattScheduleB: [] as unknown[],
};

const mockSnapshots = [
  { snapshotTimestamp: '2026-07-29T06:00:00Z', optimizationPeriod: 24, predictedDailySavings: fv(1, '1.00', 'EUR'), totalExpectedSavings: fv(1, '1.00', 'EUR'), periodCount: 96, actualCount: 24, growattScheduleCount: 4 },
  { snapshotTimestamp: '2026-07-29T10:00:00Z', optimizationPeriod: 40, predictedDailySavings: fv(1, '1.00', 'EUR'), totalExpectedSavings: fv(1, '1.00', 'EUR'), periodCount: 96, actualCount: 40, growattScheduleCount: 4 },
];

describe('PredictionAnalysisView', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(usePredictionSnapshots).mockReturnValue({
      snapshots: mockSnapshots,
      loading: false,
      error: null,
      refetch: vi.fn(),
    });
  });

  it('renders VPP power percent instead of Mode label when battMode is absent', () => {
    const comparison = {
      ...baseComparison,
      growattScheduleA: [
        { segmentId: 1, startTime: '06:00', endTime: '06:15', enabled: true, vppPowerPct: 0, vppRemoteControl: true },
      ],
    };

    vi.mocked(useSnapshotToSnapshotComparison).mockReturnValue({
      comparison,
      loading: false,
      error: null,
      refetch: vi.fn(),
    });

    render(<PredictionAnalysisView />);

    expect(screen.getByText(/VPP Power/i)).toBeInTheDocument();
    expect(screen.queryByText(/Load First|Battery First/)).not.toBeInTheDocument();
  });

  it('renders the existing TOU mode label when battMode is present', () => {
    const comparison = {
      ...baseComparison,
      growattScheduleA: [
        { startTime: '06:00', endTime: '06:15', enabled: true, battMode: 'battery_first', power: 50 },
      ],
    };

    vi.mocked(useSnapshotToSnapshotComparison).mockReturnValue({
      comparison,
      loading: false,
      error: null,
      refetch: vi.fn(),
    });

    render(<PredictionAnalysisView />);

    expect(screen.getByText(/Battery First/)).toBeInTheDocument();
    expect(screen.queryByText(/VPP Power/i)).not.toBeInTheDocument();
  });

  it('flags a VPP interval as changed when vppPowerPct differs between snapshots', () => {
    const comparison = {
      ...baseComparison,
      growattScheduleA: [
        { segmentId: 1, startTime: '06:00', endTime: '06:15', enabled: true, power: 50, vppPowerPct: 20, vppRemoteControl: true },
      ],
      growattScheduleB: [
        { segmentId: 1, startTime: '06:00', endTime: '06:15', enabled: true, power: 50, vppPowerPct: 60, vppRemoteControl: true },
      ],
    };

    vi.mocked(useSnapshotToSnapshotComparison).mockReturnValue({
      comparison,
      loading: false,
      error: null,
      refetch: vi.fn(),
    });

    render(<PredictionAnalysisView />);

    const changedBadge = screen.getByText('Changed');
    expect(changedBadge).toBeInTheDocument();

    const intervalCard = changedBadge.closest('div.border.rounded-lg');
    expect(intervalCard).not.toBeNull();
    expect(intervalCard).toHaveClass('bg-yellow-50');
    expect(intervalCard).toHaveClass('border-yellow-300');
  });
});
