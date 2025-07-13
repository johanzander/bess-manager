// Unified API client for dashboard data
import api from '../lib/api';

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
  
  // Core energy flows
  solarProduction: number;
  homeConsumption: number;
  gridImported: number;
  gridExported: number;
  batteryCharged: number;
  batteryDischarged: number;
  
  // Detailed energy flows (enhanced)
  solarToHome?: number;
  solarToBattery?: number;
  solarToGrid?: number;
  gridToHome?: number;
  gridToBattery?: number;
  batteryToHome?: number;
  batteryToGrid?: number;
  
  // Battery state
  batterySocStart: number;
  batterySocEnd: number;
  
  // Financial data
  buyPrice: number;
  sellPrice: number;
  hourlyCost: number;
  hourlySavings: number;
  batteryCycleCost: number;
  
  // Additional economic fields
  gridOnlyCost: number;
  solarOnlyCost: number;
  solarSavings: number;
  batterySavings?: number;
  
  // Detailed analysis fields
  directSolar: number;
  gridImportNeeded: number;
  solarExcess: number;
  
  // Control data
  batteryAction: number | null;
  strategicIntent?: string;
}

export interface DashboardSummary {
  // Baseline costs (what scenarios would cost) - CANONICAL
  gridOnlyCost: number;  
  solarOnlyCost: number;
  optimizedCost: number; 
  
  // Component costs (breakdown) - CANONICAL
  totalGridCost: number; 
  totalBatteryCycleCost: number; 
  
  // Savings calculations - CANONICAL
  totalSavings: number;
  solarSavings: number;
  batterySavings: number;
  
  // Energy totals - CANONICAL
  totalSolarProduction: number;
  totalHomeConsumption: number;
  totalBatteryCharged: number;
  totalBatteryDischarged: number;
  totalGridImported: number;
  totalGridExported: number;
  
  // Efficiency metrics - CANONICAL
  cycleCount: number;
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
}

// Export default dashboard fetch function
export default fetchDashboardData;