import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import api from '../../lib/api';
import PerformanceView from '../PerformanceView';
import { PerformanceResult, PerformanceScenario } from '../../types';

const coverage = {
  expectedPeriods: 672,
  analyzedPeriods: 671,
  coveragePercent: 99.85,
  actualPeriods: 671,
  predictedPeriods: 1,
  missingPeriods: 0,
  invalidRecords: 0,
  restartPlaceholders: 0,
  socDropouts: 0,
  belowReservePeriods: 0,
  excludedIntervals: [],
  gapBoundaries: [],
};

const base: PerformanceResult = {
  startDate: '2026-09-07',
  endDate: '2026-09-13',
  period: 'week',
  inProgress: false,
  timezone: 'Europe/Helsinki',
  currency: 'EUR',
  status: 'insufficient_data',
  issues: ['No usable actual energy/price observations are available.'],
  warnings: [],
  availablePeriods: ['2026-09-07'],
  coverage,
  batteryModel: null,
  comparison: null,
  daily: [],
  periods: [],
  socTimeline: [],
};

const scenario = (total: number): PerformanceScenario => ({
  netGridCost: total,
  wearCost: 0,
  totalEconomicCost: total,
  gridImportKwh: 10,
  gridExportKwh: 0,
  importCost: total,
  exportRevenue: 0,
  chargedKwh: 1,
  dischargedKwh: 1,
  throughputKwh: 2,
  solarExportKwh: 0,
  solarSelfConsumptionPercent: null,
  initialSoc: 10,
  finalSoc: 10,
  terminalShortfallCost: 0,
});

const physics = {
  maxEnergyBalanceErrorKwh: 0,
  energyBalanceMismatches: 0,
  operationalSocViolations: 0,
  minimumEnergyKwh: 1,
  maximumEnergyKwh: 1,
};

describe('Performance view', () => {
  afterEach(() => vi.restoreAllMocks());

  it('withholds financial claims when history is insufficient', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce({ data: { performance: base } });
    render(<PerformanceView />);
    await waitFor(() => expect(screen.getByText(/Comparison withheld/)).toBeInTheDocument());
    expect(
      screen.getByText('No usable actual energy/price observations are available.')
    ).toBeInTheDocument();
    expect(screen.queryByText('Actual net grid cost')).not.toBeInTheDocument();
    expect(screen.getByText(/Missed savings and captured savings: N\/A/)).toBeInTheDocument();
  });

  it('labels a comparison as an estimate on current settings', async () => {
    const estimate: PerformanceResult = {
      ...base,
      status: 'estimated_partial',
      issues: [],
      batteryModel: {
        capacityKwh: 10,
        minSoc: 10,
        maxSoc: 100,
        maxChargePowerKw: 5,
        maxDischargePowerKw: 5,
        efficiencyCharge: 0.95,
        efficiencyDischarge: 0.95,
        cycleCostPerKwh: 0.05,
        historySource: 'the lifetime battery charge/discharge meters',
        efficiencyCalibration: null,
        capacityCalibration: null,
      },
      comparison: {
        actual: scenario(8),
        optimal: scenario(6),
        solarOnly: { netGridCost: 10, wearCost: 0, totalEconomicCost: 10 },
        gridOnly: { netGridCost: 12, wearCost: 0, totalEconomicCost: 12 },
        missedSavings: 2,
        capturedPercent: 50,
        comparisonStart: '2026-09-06T21:00:00Z',
        comparisonEnd: '2026-09-13T21:00:00Z',
        initialEnergyKwh: 1,
        terminalEnergyKwh: 1,
        terminalTimestamp: '2026-09-13T21:00:00Z',
        terminalEvidence: 'last observed quarter closing battery energy',
        modelTerminalEnergyKwh: 1,
        terminalDifferenceKwh: 0,
        executionReplayed: true,
        solver: { solveSeconds: 1 },
        actualValidation: physics,
        modelValidation: physics,
      },
    };
    vi.spyOn(api, 'get').mockResolvedValueOnce({ data: { performance: estimate } });
    render(<PerformanceView />);
    await waitFor(() => expect(screen.getByText('Actual net grid cost')).toBeInTheDocument());
    expect(screen.getByText('Estimate')).toBeInTheDocument();
    expect(screen.getByText(/Estimated cost comparison · observed intervals/)).toBeInTheDocument();
    expect(screen.queryByText('Verified')).not.toBeInTheDocument();
  });
});
