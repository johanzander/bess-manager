export interface HourlyData {
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
  
  // Legacy field for compatibility
  solarCharged?: number;
}

export interface ScheduleSummary {
  baseCost: number;
  optimizedCost: number;
  gridCosts: number;
  batteryCosts: number;
  savings: number;
}

export interface BatterySettings {
  totalCapacity: number;
  reservedCapacity: number;
  minSoc: number;
  maxSoc: number;
  maxChargeDischarge: number;
  chargeCycleCost: number;
  chargingPowerRate: number;
  estimatedConsumption: number;
}

export interface EnhancedSummary {
  gridOnlyCost: number;
  solarOnlyCost: number;
  batterySolarCost: number;
  solarSavings: number;
  batterySavings: number;
  totalSavings: number;
  solarProduction: number;
  directSolarUse: number;
  solarExcess: number;
  totalCharged: number;
  totalDischarged: number;
  estimatedBatteryCycles: number;
  totalConsumption?: number;
  totalImport?: number;
}

export interface EnergyProfile {
  consumption: number[];
  solar: number[];
  battery_soc: number[];
  battery_soe?: number[];
  actualHours: number;
}

export interface ScheduleResponse {
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