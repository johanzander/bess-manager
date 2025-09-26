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
export const fetchDashboardData = async (date?: string) => {
  const params = date ? { date } : {};
  const response = await api.get('/api/dashboard', { params });
  return response.data;
};

// Type definitions for the unified dashboard response
export interface DashboardHourlyData {
  hour: number;
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
  currentHour: number;
  
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
    netGridPowerW: number;
    acPowerW: number;
    selfPowerW: number;
    
    // Formatted display values
    solarPowerFormatted: string;
    homeLoadPowerFormatted: string;
    gridImportPowerFormatted: string;
    gridExportPowerFormatted: string;
    batteryChargePowerFormatted: string;
    batteryDischargePowerFormatted: string;
    netBatteryPowerFormatted: string;
    netGridPowerFormatted: string;
    acPowerFormatted: string;
    selfPowerFormatted: string;
  };
}

// Export default dashboard fetch function
export default fetchDashboardData;