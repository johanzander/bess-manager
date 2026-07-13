import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Mock the API module before importing the component
vi.mock('../../lib/api', () => ({
  default: {
    get: vi.fn(),
  },
}));

// Mock the dashboard hook
vi.mock('../../hooks/useDashboardData', () => ({
  useDashboardData: vi.fn(),
}));

import SystemStatusCard from '../SystemStatusCard';
import api from '../../lib/api';
import { useDashboardData } from '../../hooks/useDashboardData';

const fv = (value: number, display: string, unit = '') => ({
  value,
  display,
  unit,
  text: unit ? `${display} ${unit}` : display,
});

// Generate hourly data for all 24 hours
const baseHourlyEntry = {
  dataSource: 'actual' as const,
  solarProduction: fv(2.5, '2.50', 'kW'),
  homeConsumption: fv(1.0, '1.00', 'kW'),
  gridImported: fv(0, '0.00', 'kW'),
  gridExported: fv(0, '0.00', 'kW'),
  batteryCharged: fv(0, '0.00', 'kW'),
  batteryDischarged: fv(1.5, '1.50', 'kW'),
  batterySocStart: fv(80, '80', '%'),
  batterySocEnd: fv(75, '75', '%'),
  batterySoeEnd: fv(22.5, '22.5', 'kWh'),
  buyPrice: fv(0.15, '0.15', 'EUR/kWh'),
  sellPrice: fv(0.10, '0.10', 'EUR/kWh'),
  importCost: fv(0.15, '0.15', 'EUR'),
  exportRevenue: fv(0, '0.00', 'EUR'),
  hourlyCost: fv(0.15, '0.15', 'EUR'),
  gridCost: fv(0.15, '0.15', 'EUR'),
  hourlySavings: fv(0.05, '0.05', 'EUR'),
  batteryCycleCost: fv(0.02, '0.02', 'EUR'),
  gridOnlyCost: fv(0.20, '0.20', 'EUR'),
  solarOnlyCost: fv(0.18, '0.18', 'EUR'),
  solarSavings: fv(0.02, '0.02', 'EUR'),
  batterySavings: fv(0.03, '0.03', 'EUR'),
  netSavings: fv(0.05, '0.05', 'EUR'),
  batteryAction: -1.5,
  strategicIntent: 'LOAD_SUPPORT',
  directSolar: fv(2.5, '2.50', 'kW'),
  gridImportNeeded: fv(0, '0.00', 'kW'),
  solarExcess: fv(1.5, '1.50', 'kW'),
};

const mockDashboardData = {
  date: '2026-07-11',
  currentPeriod: 12,
  totalDailySavings: 2.5,
  actualSavingsSoFar: 1.0,
  predictedRemainingSavings: 1.5,
  actualHoursCount: 12,
  predictedHoursCount: 12,
  dataSources: ['actual', 'predicted'],
  hourlyData: Array.from({ length: 24 }, (_, i) => ({
    hour: i,
    period: i,
    ...baseHourlyEntry,
  })),
  summary: {
    gridOnlyCost: fv(2.0, '2.00', 'EUR'),
    solarOnlyCost: fv(1.95, '1.95', 'EUR'),
    optimizedCost: fv(1.9, '1.90', 'EUR'), // Old bundled cost (includes battery wear)
    netGridCost: fv(1.5, '1.50', 'EUR'),   // New net cost (grid only, no wear)
    netSavings: fv(0.65, '0.65', 'EUR'),   // Wear-free savings, distinct from totalSavings
    totalSavings: fv(0.5, '0.50', 'EUR'),
    solarSavings: fv(0.05, '0.05', 'EUR'),
    batterySavings: fv(0.45, '0.45', 'EUR'),
    totalSolarProduction: fv(25, '25.00', 'kWh'),
    totalHomeConsumption: fv(12, '12.00', 'kWh'),
    totalBatteryCharged: fv(8, '8.00', 'kWh'),
    totalBatteryDischarged: fv(7.5, '7.50', 'kWh'),
    totalGridImported: fv(2, '2.00', 'kWh'),
    totalGridExported: fv(1, '1.00', 'kWh'),
    solarSavingsPercentage: fv(2.5, '2.5', '%'),
    selfConsumptionPercentage: fv(52, '52', '%'),
    totalSavingsPercentage: fv(25, '25', '%'),
    totalSolarToHome: fv(12, '12.00', 'kWh'),
    totalSolarToBattery: fv(13, '13.00', 'kWh'),
    totalSolarToGrid: fv(0, '0.00', 'kWh'),
    totalGridToHome: fv(0, '0.00', 'kWh'),
    totalGridToBattery: fv(2, '2.00', 'kWh'),
    totalBatteryToHome: fv(7.5, '7.50', 'kWh'),
    totalBatteryToGrid: fv(0, '0.00', 'kWh'),
    gridToHomePercentage: fv(0, '0', '%'),
    gridToBatteryPercentage: fv(100, '100', '%'),
    solarToGridPercentage: fv(0, '0', '%'),
    batteryToGridPercentage: fv(0, '0', '%'),
    solarToBatteryPercentage: fv(52, '52', '%'),
    gridToBatteryChargedPercentage: fv(100, '100', '%'),
    batteryToHomePercentage: fv(100, '100', '%'),
    batteryToGridDischargedPercentage: fv(0, '0', '%'),
    averagePrice: fv(0.15, '0.15', 'EUR/kWh'),
    netBatteryAction: fv(-7.5, '-7.50', 'kWh'),
    finalBatterySoe: fv(22.5, '22.5', 'kWh'),
  },
  totals: {
    totalHomeConsumption: 12,
    totalSolarProduction: 25,
    totalGridImport: 2,
    totalGridExport: 1,
    totalBatteryCharged: 8,
    totalBatteryDischarged: 7.5,
    totalSolarToHome: 12,
    totalSolarToBattery: 13,
    totalSolarToGrid: 0,
    totalGridToHome: 0,
    totalGridToBattery: 2,
    totalBatteryToHome: 7.5,
    totalBatteryToGrid: 0,
    avgBuyPrice: 0.15,
    avgSellPrice: 0.10,
    totalChargeFromSolar: 13,
    totalChargeFromGrid: 2,
    estimatedBatteryCycles: 0.15,
  },
  strategicIntentSummary: {
    LOAD_SUPPORT: 6,
    IDLE: 6,
    SOLAR_STORAGE: 6,
  },
  batteryCapacity: 30,
  batterySoc: fv(75, '75', '%') as any,
  batterySoe: fv(22.5, '22.5', 'kWh') as any,
  batterySocFormatted: '75%',
  batterySoeFormatted: '22.5 kWh',
  realTimePower: {
    solarPower: fv(2500, '2.50', 'kW'),
    homeLoadPower: fv(1000, '1.00', 'kW'),
    gridImportPower: fv(0, '0.00', 'kW'),
    gridExportPower: fv(0, '0.00', 'kW'),
    batteryChargePower: fv(0, '0.00', 'kW'),
    batteryDischargePower: fv(1500, '1.50', 'kW'),
    netBatteryPower: fv(-1500, '-1.50', 'kW'),
    acPower: fv(500, '0.50', 'kW'),
    solarPowerW: 2500,
    homeLoadPowerW: 1000,
    gridImportPowerW: 0,
    gridExportPowerW: 0,
    batteryChargePowerW: 0,
    batteryDischargePowerW: 1500,
    netBatteryPowerW: -1500,
    acPowerW: 500,
    solarPowerFormatted: '2.50 kW',
    homeLoadPowerFormatted: '1.00 kW',
    gridImportPowerFormatted: '0.00 kW',
    gridExportPowerFormatted: '0.00 kW',
    batteryChargePowerFormatted: '0.00 kW',
    batteryDischargePowerFormatted: '1.50 kW',
    netBatteryPowerFormatted: '-1.50 kW',
    acPowerFormatted: '0.50 kW',
  } as any,
  tomorrowData: null,
};

const mockInverterData = {
  batteryMode: 'LOAD_FIRST',
};

describe('SystemStatusCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    // Mock useDashboardData hook to always return the mock data
    vi.mocked(useDashboardData).mockReturnValue({
      data: mockDashboardData,
      loading: false,
      error: null,
      refetch: vi.fn(),
    });

    // Mock API calls for inverter data - use synchronous resolution for testing
    vi.mocked(api.get).mockResolvedValue({
      data: mockInverterData,
    });
  });

  it('shows Net Grid Cost as the headline, not the bundled optimized cost', async () => {
    render(<SystemStatusCard systemMode="live" />);

    // Wait for the component to load and render the actual content
    await waitFor(() => {
      expect(screen.getByText('Home Power')).toBeInTheDocument();
    });

    // The "Today's Cost & Savings" card should show Net Grid Cost (1.50 EUR) as the headline,
    // not Optimized Cost (1.90 EUR)
    expect(screen.getByText('1.50 EUR')).toBeInTheDocument();
    expect(screen.queryByText('1.90 EUR')).not.toBeInTheDocument();

    // Also verify that the metric label is now "Net Grid Cost" instead of "Today's Costs"
    expect(screen.getByText('Net Grid Cost')).toBeInTheDocument();
  });

  it('shows wear-free Net Savings sub-metric, not the wear-inclusive Today\'s Savings', async () => {
    render(<SystemStatusCard systemMode="live" />);

    await waitFor(() => {
      expect(screen.getByText('Home Power')).toBeInTheDocument();
    });

    // The savings sub-metric should read summary.netSavings (0.65 EUR), not
    // summary.totalSavings (0.50 EUR), and be labelled "Net Savings".
    expect(screen.getByText('Net Savings')).toBeInTheDocument();
    expect(screen.getByText('0.65 EUR')).toBeInTheDocument();
    expect(screen.queryByText('0.50 EUR')).not.toBeInTheDocument();
    expect(screen.queryByText("Today's Savings")).not.toBeInTheDocument();
  });

  it('does not show a horizon annotation for a single-day plan', async () => {
    render(<SystemStatusCard systemMode="live" />);

    await waitFor(() => {
      expect(screen.getByText('Home Power')).toBeInTheDocument();
    });

    expect(screen.queryByText(/Today:/)).not.toBeInTheDocument();
  });

  it('shows the full-horizon total as headline with Today/Tomorrow breakdown when a 2-day plan is active', async () => {
    vi.mocked(useDashboardData).mockReturnValue({
      data: {
        ...mockDashboardData,
        summary: {
          ...mockDashboardData.summary,
          horizonDays: 2,
          netGridCostFullHorizon: fv(-0.05, '-0.05', 'EUR'),
          netSavingsFullHorizon: fv(2.05, '2.05', 'EUR'),
        },
      },
      loading: false,
      error: null,
      refetch: vi.fn(),
    });

    render(<SystemStatusCard systemMode="live" />);

    await waitFor(() => {
      expect(screen.getByText('Home Power')).toBeInTheDocument();
    });

    // Title reflects the 2-day horizon.
    expect(screen.getByText('Cost & Savings (2 days)')).toBeInTheDocument();
    expect(screen.queryByText("Today's Cost & Savings")).not.toBeInTheDocument();

    // Full-horizon totals become the headline values...
    expect(screen.getByText('-0.05 EUR')).toBeInTheDocument();
    expect(screen.getByText('2.05 EUR')).toBeInTheDocument();
    // ...with a Today/Tomorrow breakdown after the headline (netGridCost today
    // 1.50, so tomorrow = -0.05 - 1.50 = -1.55).
    expect(screen.getByText('Today: 1.50 EUR')).toBeInTheDocument();
    expect(screen.getByText('Tomorrow: -1.55 EUR')).toBeInTheDocument();
    // ...and Today/Tomorrow beside Net Savings too (today 0.65, so
    // tomorrow = 2.05 - 0.65 = 1.40).
    expect(screen.getByText('Today: 0.65 EUR')).toBeInTheDocument();
    expect(screen.getByText('Tomorrow: 1.40 EUR')).toBeInTheDocument();
  });

  it('keeps the single-day title and no breakdown when only today is planned', async () => {
    render(<SystemStatusCard systemMode="live" />);

    await waitFor(() => {
      expect(screen.getByText('Home Power')).toBeInTheDocument();
    });

    expect(screen.getByText("Today's Cost & Savings")).toBeInTheDocument();
    expect(screen.queryByText(/Cost & Savings \(2 days\)/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Tomorrow:/)).not.toBeInTheDocument();
  });
});
