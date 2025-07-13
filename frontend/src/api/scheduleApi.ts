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

/**
 * Legacy function for backward compatibility.
 * @deprecated Use fetchDashboardData() instead
 */
export const fetchScheduleData = async (date?: string) => {
  console.warn('fetchScheduleData() is deprecated, use fetchDashboardData() instead');
  return fetchDashboardData(date);
};

/**
 * Legacy function for backward compatibility.
 * @deprecated Use fetchDashboardData() instead
 */
export const fetchEnergyProfile = async (date?: string) => {
  console.warn('fetchEnergyProfile() is deprecated, use fetchDashboardData() instead');
  return fetchDashboardData(date);
};

/**
 * Legacy function for backward compatibility.
 * @deprecated Use fetchDashboardData() instead
 */
export const fetchDailyView = async (date?: string) => {
  console.warn('fetchDailyView() is deprecated, use fetchDashboardData() instead');
  return fetchDashboardData(date);
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
  batteryLevel: number; // Alias for batterySocEnd
  
  // Financial data
  buyPrice: number;
  sellPrice: number;
  hourlyCost: number;
  hourlySavings: number;
  batteryCycleCost: number;
  
  // Control data
  batteryAction: number | null;
  strategicIntent?: string;
  
  // Compatibility flags
  isActual: boolean;
  isPredicted: boolean;
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
  cycleCount: number;
  avgBuyPrice: number;
  avgSellPrice: number;
  totalChargeFromSolar: number;
  totalChargeFromGrid: number;
  estimatedBatteryCycles: number;
}

export interface EnergyProfile {
  consumption: number[];
  solar: number[];
  batterySoc: number[];
  actualHours: number;
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
  enhancedSummary: DashboardSummary; // Alias
  totals: DashboardTotals;
  strategicIntentSummary: Record<string, number>;
  batteryCapacity: number;
  
  // Energy profile for compatibility
  energyProfile: EnergyProfile;
}

// Export default dashboard fetch function
export default fetchDashboardData;