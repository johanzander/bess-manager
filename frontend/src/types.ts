/**
 * Battery state naming convention:
 * - SOE (State of Energy): Absolute energy in kWh (0-30 kWh typical)
 * - SOC (State of Charge): Relative charge in % (0-100%)
 * - USE batterySocEnd for battery level displays (clear and unambiguous)
 */
export interface HourlyData {
  // Core fields
  hour: string;
  price: number;
  consumption: number;
  gridCost: number;
  batteryCost: number;
  totalCost: number;
  savings: number;
  
  // Energy data fields - canonical camelCase names
  solarProduction: number;
  homeConsumption: number;
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
  
  // Battery State of Energy (kWh) - absolute values
  batterySoeStart?: number;  // kWh
  batterySoeEnd?: number;    // kWh
  
  // Battery State of Charge (%) - percentage values  
  batterySocStart?: number;  // % (0-100)
  batterySocEnd?: number;    // % (0-100)
  
  // API camelCase fields
  buyPrice?: number;
  batteryAction?: number;
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


