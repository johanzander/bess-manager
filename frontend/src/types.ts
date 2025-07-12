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
  savings: number;
  
  // Energy data fields - canonical camelCase names
  solarProduction: number;
  homeConsumption: number;
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
  
  // API camelCase fields
  buyPrice?: number;
  batteryAction?: number;
  batterySoc?: number;
  gridImported?: number;
  gridExported?: number;
}

export interface ScheduleSummary {
  gridOnlyCost: number;
  optimizedCost: number;
  gridCosts: number;
  batteryCosts: number;
  savings: number;
  
  // Optional fields for enhanced summary
  solarOnlySavings?: number;
  solarOnlyCost?: number;
  batterySavings?: number;
  totalSolarProduction?: number;
  totalBatteryCharged?: number;
  totalBatteryDischarged?: number;
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

export interface ScheduleData {
  hourlyData: HourlyData[];
  summary: ScheduleSummary;
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


