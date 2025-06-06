export interface HourlyData {
  // Core fields
  hour: string;
  price: number;
  consumption: number;
  batteryLevel: number;
  action: number;
  gridCost: number;
  batteryCost: number;
  totalCost: number;
  baseCost: number;
  savings: number;
  
  // Solar data fields
  solarProduction?: number;
  directSolar?: number;
  exportSolar?: number;
  importFromGrid?: number;
  solarOnlyCost?: number;
  solarSavings?: number;
  gridOnlyCost?: number;
  batterySavings?: number;
  batteryGridConsumption?: number;
  
  // Additional energy flow fields
  batteryCharge?: number;
  batteryDischarge?: number;
  gridImport?: number;
  gridExport?: number;
  gridToBattery?: number;
  solarToBattery?: number;
  
  // Legacy field for compatibility
  solarCharged?: number;
  
  // API snake_case alternatives
  battery_level?: number;
  battery_action?: number;
  battery_soc?: number;
  grid_cost?: number;
  battery_cost?: number;
  total_cost?: number;
  base_cost?: number;
  solar_production?: number;
  electricity_price?: number;
  
  // API camelCase alternatives
  electricityPrice?: number;
  batteryAction?: number;
  batterySoc?: number;
  homeConsumption?: number;
  solarGenerated?: number;
  gridImported?: number;
  gridExported?: number;
}

export interface ScheduleSummary {
  baseCost: number;
  optimizedCost: number;
  gridCosts: number;
  batteryCosts: number;
  savings: number;
  
  // Optional fields for enhanced summary
  solarOnlySavings?: number;
  solarOnlyCost?: number;
  batterySavings?: number;
  totalSolarProduction?: number;
  totalBatteryCharge?: number;
  totalBatteryDischarge?: number;
  totalGridImport?: number;
  totalGridExport?: number;
  cycleCount?: number;
}

export interface BatterySettings {
  totalCapacity: number;
  reservedCapacity: number;
  minSoc?: number;
  maxSoc?: number;
  maxChargeDischarge: number;
  chargeCycleCost: number;
  chargingPowerRate: number;
  estimatedConsumption: number;
  useActualPrice?: boolean;
}

export interface ElectricitySettings {
  markupRate: number;
  vatMultiplier: number;
  additionalCosts: number;
  taxReduction: number;
  area: 'SE1' | 'SE2' | 'SE3' | 'SE4';
}

export interface EnhancedSummary {
  gridOnlyCost: number;
  solarOnlyCost: number;
  batterySolarCost: number;
  solarSavings: number;
  solarOnlySavings?: number;  // Added field for solar-only savings
  arbitrageSavings?: number;  // Added field for arbitrage savings
  batterySavings: number;
  totalSavings: number;
  solarProduction: number;
  directSolarUse: number;
  solarExcess: number;
  totalCharged: number;
  totalDischarged: number;
  totalChargeFromSolar?: number;  // Added field for battery charging from solar
  totalChargeFromGrid?: number;   // Added field for battery charging from grid
  totalGridExport?: number;       // Added field for total grid export
  totalGridImport?: number;       // Added field for total grid import
  totalBatteryGridConsumption?: number; // Added field for battery grid consumption
  estimatedBatteryCycles: number;
  totalConsumption?: number;
  avgBuyPrice?: number;          // Added field for average buy price
  avgSellPrice?: number;         // Added field for average sell price
  totalImport?: number;
}

export interface EnergyProfile {
  consumption: number[];
  solar: number[];
  battery_soc: number[];
  battery_soe?: number[];
  actualHours: number;
}

export interface ScheduleData {
  hourlyData: HourlyData[];
  summary: ScheduleSummary;
  energyProfile?: EnergyProfile;
  enhancedSummary?: EnhancedSummary;
}

export type HealthStatus = "OK" | "WARNING" | "ERROR" | "UNKNOWN";

export interface HealthCheckResult {
  name: string;
  key: string | null;
  entity_id?: string | null;
  status: HealthStatus;
  value: any;
  error: string | null;
}

export interface ComponentHealthStatus {
  name: string;
  description: string;
  required: boolean;
  status: HealthStatus;
  checks: HealthCheckResult[];
  last_run: string;
}

export interface SystemHealthData {
  timestamp: string;
  system_mode: string;
  checks: ComponentHealthStatus[];
}


