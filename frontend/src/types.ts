/**
 * Battery state naming convention:
 * - SOE (State of Energy): Absolute energy in kWh (0-30 kWh typical)
 * - SOC (State of Charge): Relative charge in % (0-100%)
 * - USE batterySocEnd for battery level displays (clear and unambiguous)
 */
export interface HourlyData {
  // Core display fields (use these for UI)
  hour: string;
  buyPrice: number;           // SEK/kWh
  
  // Energy flows (use these for all energy calculations)  
  solarProduction: number;    // kWh
  homeConsumption: number;    // kWh
  gridImported: number;       // kWh
  gridExported: number;       // kWh  
  batteryCharged: number;     // kWh
  batteryDischarged: number;  // kWh
  
  // Economic fields (use these for cost calculations)
  batteryCycleCost: number;   // SEK battery wear
  gridCost: number;           // SEK net grid cost
  hourlyCost: number;         // SEK total cost
  hourlySavings: number;      // SEK savings
  
  // Battery state (established in SOC/SOE naming fix)
  batterySoeStart: number;    // kWh 
  batterySoeEnd: number;      // kWh
  batterySocStart: number;    // %
  batterySocEnd: number;      // %
  
  // Detailed energy flows
  solarToHome?: number;        // kWh
  solarToBattery?: number;     // kWh  
  solarToGrid?: number;        // kWh
  gridToHome?: number;         // kWh
  gridToBattery?: number;      // kWh
  batteryToHome?: number;      // kWh
  batteryToGrid?: number;      // kWh
  
  // Control and decision fields
  batteryAction?: number;      // kW (+ charge, - discharge)
  strategicIntent?: string;    // strategy name
  
  // Additional economic fields
  solarOnlyCost?: number;      // SEK
  gridOnlyCost?: number;       // SEK
  batterySavings?: number;     // SEK
  solarSavings?: number;       // SEK
  
  // Metadata
  dataSource?: 'actual' | 'predicted';  // ✓ CANONICAL
  timestamp?: string;         // ISO format
}

export interface ScheduleSummary {
  // Baseline costs (what scenarios would cost)
  gridOnlyCost: number;       // SEK if only using grid
  solarOnlyCost: number;      // SEK if solar + grid (no battery)
  optimizedCost: number;      // SEK with battery optimization
  
  // Component costs (breakdown of optimized scenario)
  totalGridCost: number;      // SEK net grid costs
  totalBatteryCycleCost: number; // SEK battery wear costs
  
  // Savings calculations (vs baselines)
  totalSavings: number;       // SEK total savings vs grid-only
  solarSavings: number;       // SEK savings from solar vs grid-only  
  batterySavings: number;     // SEK additional savings from battery
  
  // Energy totals (for context)
  totalSolarProduction: number;   // kWh
  totalHomeConsumption: number;   // kWh
  totalBatteryCharged: number;    // kWh
  totalBatteryDischarged: number; // kWh
  totalGridImported: number;      // kWh
  totalGridExported: number;      // kWh
  
  // Efficiency metrics
  cycleCount: number;         // number of battery cycles
}

export interface BatterySettings {
  // Capacity settings (kWh)
  totalCapacity: number;        // kWh total capacity
  reservedCapacity: number;     // kWh reserved (unusable)
  
  // State of charge limits (%)
  minSoc: number;               // % minimum charge
  maxSoc: number;               // % maximum charge
  
  // Power limits (kW) 
  maxChargePowerKw: number;     // kW max charge power
  maxDischargePowerKw: number;  // kW max discharge power
  
  // Economic settings
  cycleCostPerKwh: number;      // SEK/kWh wear cost
  chargingPowerRate: number;    // % of max power to use
  
  // Efficiency settings (%)
  efficiencyCharge: number;     // % charging efficiency
  efficiencyDischarge: number;  // % discharge efficiency
  
  // Consumption estimate
  estimatedConsumption: number; // kWh daily estimate
  
  // Price settings
  useActualPrice?: boolean;     // use actual vs estimated prices
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


