// Unified API client for dashboard data
import api from '../lib/api';
import { FormattedValue } from '../types';

/**
 * Fetch comprehensive dashboard data including schedule, energy flows, and financial metrics.
 * This replaces multiple previous endpoints:
 * - /api/schedule
 * - /api/schedule/detailed  
 * - /api/schedule/current
 * - /api/v2/daily_view
 */
export const fetchDashboardData = async (date?: string, resolution?: string) => {
  const params: Record<string, string> = {};
  if (date) params.date = date;
  if (resolution) params.resolution = resolution;
  const response = await api.get('/api/dashboard', { params });
  return response.data;
};

/**
 * Fetch ISO dates (YYYY-MM-DD) that have dashboard data available, for greying
 * out unavailable days in a date picker instead of erroring on selection.
 */
export const fetchAvailableDashboardDates = async (): Promise<string[]> => {
  const response = await api.get('/api/dashboard/available-dates');
  return response.data.dates;
};

// Type definitions for the unified dashboard response
export interface DashboardHourlyData {
  hour: number;
  period: number;  // Period index (0-23 hourly, 0-95 quarterly)
  dataSource: 'actual' | 'predicted';

  // Core energy flows - FormattedValue
  solarProduction: FormattedValue;
  homeConsumption: FormattedValue;
  gridImported: FormattedValue;
  gridExported: FormattedValue;
  batteryCharged: FormattedValue;
  batteryDischarged: FormattedValue;

  // Battery state - FormattedValue
  batterySocStart: FormattedValue;
  batterySocEnd: FormattedValue;
  batterySoeEnd: FormattedValue;

  // Financial data - FormattedValue
  buyPrice: FormattedValue;
  sellPrice: FormattedValue;
  importCost: FormattedValue;
  exportRevenue: FormattedValue;
  hourlyCost: FormattedValue;
  hourlySavings: FormattedValue;
  batteryCycleCost: FormattedValue;

  // Additional economic fields - FormattedValue
  gridOnlyCost: FormattedValue;
  solarOnlyCost: FormattedValue;
  solarSavings: FormattedValue;
  batterySavings?: FormattedValue;

  // Detailed analysis fields - FormattedValue
  directSolar?: FormattedValue;
  gridImportNeeded: FormattedValue;
  solarExcess: FormattedValue;

  // Control data
  batteryAction: number | null;
  strategicIntent?: string;
}

export interface DashboardSummary {
  // Baseline costs (what scenarios would cost) - CANONICAL
  gridOnlyCost: FormattedValue;
  solarOnlyCost: FormattedValue;
  optimizedCost: FormattedValue;
  netGridCost: FormattedValue;
  netSavings: FormattedValue;

  // Savings calculations - CANONICAL
  totalSavings: FormattedValue;
  solarSavings: FormattedValue;
  batterySavings: FormattedValue;

  // Energy totals - CANONICAL
  totalSolarProduction: FormattedValue;
  totalHomeConsumption: FormattedValue;
  totalBatteryCharged: FormattedValue;
  totalBatteryDischarged: FormattedValue;
  totalGridImported: FormattedValue;
  totalGridExported: FormattedValue;

  // Percentage fields - NEW
  solarSavingsPercentage: FormattedValue;
  selfConsumptionPercentage: FormattedValue;
  totalSavingsPercentage: FormattedValue;

  // Flow breakdowns - NEW
  totalSolarToHome: FormattedValue;
  totalSolarToBattery: FormattedValue;
  totalSolarToGrid: FormattedValue;
  totalGridToHome: FormattedValue;
  totalGridToBattery: FormattedValue;
  totalBatteryToHome: FormattedValue;
  totalBatteryToGrid: FormattedValue;

  // Percentage breakdowns - NEW
  gridToHomePercentage: FormattedValue;
  gridToBatteryPercentage: FormattedValue;
  solarToGridPercentage: FormattedValue;
  batteryToGridPercentage: FormattedValue;
  solarToBatteryPercentage: FormattedValue;
  gridToBatteryChargedPercentage: FormattedValue;
  batteryToHomePercentage: FormattedValue;
  batteryToGridDischargedPercentage: FormattedValue;

  // Additional fields
  averagePrice: FormattedValue;
  netBatteryAction: FormattedValue;
  finalBatterySoe: FormattedValue;
}

export interface DashboardTotals {
  totalHomeConsumption: number;
  totalSolarProduction: number;
  totalGridImport: number;
  totalGridExport: number;
  totalBatteryCharged: number;
  totalBatteryDischarged: number;
  totalSolarToHome: number;
  totalSolarToBattery: number;
  totalSolarToGrid: number;
  totalGridToHome: number;
  totalGridToBattery: number;
  totalBatteryToHome: number;
  totalBatteryToGrid: number;
  avgBuyPrice: number;
  avgSellPrice: number;
  totalChargeFromSolar: number;
  totalChargeFromGrid: number;
  estimatedBatteryCycles: number;
}

export interface DashboardResponse {
  // Core metadata
  date: string;
  currentPeriod: number;
  
  // Financial summary
  totalDailySavings: number;
  actualSavingsSoFar: number;
  predictedRemainingSavings: number;
  
  // Data structure info
  actualHoursCount: number;
  predictedHoursCount: number;
  dataSources: string[];
  
  // Main data
  hourlyData: DashboardHourlyData[];
  tomorrowData?: DashboardHourlyData[] | null;

  // Enhanced summaries
  summary: DashboardSummary;
  totals: DashboardTotals;
  strategicIntentSummary: Record<string, number>;
  batteryCapacity: number;
  
  // Battery state
  batterySoc: number;
  batterySoe: number;
  batterySocFormatted: string;
  batterySoeFormatted: string;
  
  // Real-time power data
  realTimePower: {
    // Raw power values in Watts
    solarPowerW: number;
    homeLoadPowerW: number;
    gridImportPowerW: number;
    gridExportPowerW: number;
    batteryChargePowerW: number;
    batteryDischargePowerW: number;
    netBatteryPowerW: number;
    acPowerW: number;
    
    // Formatted display values
    solarPowerFormatted: string;
    homeLoadPowerFormatted: string;
    gridImportPowerFormatted: string;
    gridExportPowerFormatted: string;
    batteryChargePowerFormatted: string;
    batteryDischargePowerFormatted: string;
    netBatteryPowerFormatted: string;
    acPowerFormatted: string;
  };
}

// Export default dashboard fetch function
export default fetchDashboardData;

export type SavingsAggregatePeriod = 'day' | 'week' | 'month' | 'year';

export interface SavingsBucket {
  label: string;
  startDate: string;
  endDate: string;
  dayCount: number;
  importKwh: FormattedValue;
  importEur: FormattedValue;
  exportKwh: FormattedValue;
  exportEur: FormattedValue;
  gridCost: FormattedValue;
  gridOnlyCost: FormattedValue;
  netSavings: FormattedValue;
  solarSavings: FormattedValue;
  batterySavings: FormattedValue;
  batteryCycleCost: FormattedValue;
  savingsVsGridOnly: FormattedValue;
  solarKwh: FormattedValue;
  batteryChargedKwh: FormattedValue;
  batteryDischargedKwh: FormattedValue;
}

export interface SavingsAggregateResponse {
  buckets: SavingsBucket[];
  count: number;
}

export const fetchSavingsAggregate = async (
  period: SavingsAggregatePeriod,
  count?: number,
  date?: string
): Promise<SavingsAggregateResponse> => {
  const params: Record<string, string | number> = { period };
  if (count) params.count = count;
  if (date) params.date = date;
  const response = await api.get('/api/savings/aggregate', { params });
  return response.data;
};

export interface SavingsHistoryDiskUsage {
  dayCount: number;
  totalBytes: number;
}

export const fetchSavingsHistoryDiskUsage = async (): Promise<SavingsHistoryDiskUsage> => {
  const response = await api.get('/api/savings/history/disk-usage');
  return response.data;
};

export const clearSavingsHistory = async (): Promise<SavingsHistoryDiskUsage> => {
  const response = await api.delete('/api/savings/history');
  return response.data;
};