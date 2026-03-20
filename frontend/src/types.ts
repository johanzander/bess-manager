/**
 * Battery state naming convention:
 * - SOE (State of Energy): Absolute energy in kWh (0-30 kWh typical)
 * - SOC (State of Charge): Relative charge in % (0-100%)
 * - USE batterySocEnd for battery level displays (clear and unambiguous)
 */

/**
 * Unified formatting interface for all user-facing values
 */
export interface FormattedValue {
  value: number;        // Raw numeric value for calculations/sorting
  display: string;      // Formatted number without unit ("84.87", "700")
  unit: string;         // Unit label (currency code, "kWh", "Wh", "%")
  text: string;         // Complete formatted text ("84.87 EUR", "700 Wh")
}
export interface HourlyData {
  // Core display fields (use these for UI)
  period: number;  // Period index (0-23 for hourly, 0-95 for quarterly)

  // Economic fields (use these for cost calculations)
  batteryCycleCost?: number;   // battery wear cost
  gridCost?: number;           // net grid cost
  hourlyCost?: number;         // total cost
  hourlySavings?: number;      // savings

  // Battery state (established in SOC/SOE naming fix)
  batterySoeStart?: number;    // kWh
  batterySoeEnd?: number;      // kWh

  // Detailed energy flows
  solarToHome?: number;        // kWh
  solarToBattery?: number;     // kWh
  solarToGrid?: number;        // kWh
  gridToHome?: number;         // kWh
  gridToBattery?: number;      // kWh
  batteryToHome?: number;      // kWh
  batteryToGrid?: number;      // kWh

  // Control and decision fields
  strategicIntent?: string;    // strategy name

  // All user-facing data via FormattedValue - canonical naming
  buyPrice?: FormattedValue;
  sellPrice?: FormattedValue;
  solarProduction?: FormattedValue;
  homeConsumption?: FormattedValue;
  gridImported?: FormattedValue;
  gridExported?: FormattedValue;
  batteryCharged?: FormattedValue;
  batteryDischarged?: FormattedValue;
  batterySocStart?: FormattedValue;
  batterySocEnd?: FormattedValue;
  batteryAction?: FormattedValue;
  
  // Additional economic fields
  solarOnlyCost?: number;
  gridOnlyCost?: number;
  batterySavings?: number;
  solarSavings?: number;       // Solar-Only vs Grid-Only savings
  
  // Metadata
  dataSource?: string;  // 'actual' | 'predicted' | others
  timestamp?: string;         // ISO format
}

export interface ScheduleSummary {
  // Baseline costs (what scenarios would cost)
  gridOnlyCost: number;       // cost if only using grid
  solarOnlyCost: number;      // cost if solar + grid (no battery)
  optimizedCost: number;      // cost with battery optimization

  // Component costs (breakdown of optimized scenario)
  totalGridCost: number;      // net grid costs
  totalBatteryCycleCost: number; // battery wear costs

  // Savings calculations (vs baselines)
  totalSavings: number;       // total savings vs grid-only
  solarSavings: number;       // savings from solar vs grid-only
  batterySavings: number;     // additional savings from battery
  
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
  cycleCostPerKwh: number;      // wear cost per kWh
  chargingPowerRate: number;    // % of max power to use
  dischargingPowerRate: number; // % of max power to use for discharge
  
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
  area: string;
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
  rawValue: any; // Original sensor value for logic/comparisons
  displayValue: string; // Human-readable with units (required, no fallbacks)
  error: string | null;
  message?: string | null;
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

export interface PredictionSnapshot {
  snapshotTimestamp: string;
  optimizationPeriod: number;
  predictedDailySavings: FormattedValue;
  periodCount: number;
  actualCount: number;
  growattScheduleCount: number;
}

export interface PeriodDeviation {
  period: number;
  predictedBatteryAction: FormattedValue;
  actualBatteryAction: FormattedValue;
  batteryActionDeviation: FormattedValue;
  predictedConsumption: FormattedValue;
  actualConsumption: FormattedValue;
  consumptionDeviation: FormattedValue;
  predictedSolar: FormattedValue;
  actualSolar: FormattedValue;
  solarDeviation: FormattedValue;
  predictedSavings: FormattedValue;
  actualSavings: FormattedValue;
  savingsDeviation: FormattedValue;
  deviationType: string;
}

export interface SnapshotComparison {
  snapshotTimestamp: string;
  snapshotPeriod: number;
  comparisonTime: string;
  periodDeviations: PeriodDeviation[];
  totalPredictedSavings: FormattedValue;
  totalActualSavings: FormattedValue;
  savingsDeviation: FormattedValue;
  primaryDeviationCause: string;
  predictedGrowattSchedule: any[];
  currentGrowattSchedule: any[];
}

export interface SnapshotDataPoint {
  solar: FormattedValue;
  consumption: FormattedValue;
  batteryAction: FormattedValue;
  batterySoe: FormattedValue;
  gridImport: FormattedValue;
  gridExport: FormattedValue;
  cost: FormattedValue;
  gridOnlyCost: FormattedValue;
  savings: FormattedValue;
  dataSource: string;
}

export interface PeriodComparison {
  period: number;
  snapshotA: SnapshotDataPoint;
  snapshotB: SnapshotDataPoint;
  delta: Omit<SnapshotDataPoint, 'dataSource'>;
}

export interface SnapshotToSnapshotComparison {
  snapshotAPeriod: number;
  snapshotATimestamp: string;
  snapshotBPeriod: number;
  snapshotBTimestamp: string;
  periodComparisons: PeriodComparison[];
  growattScheduleA: any[];
  growattScheduleB: any[];
}

export interface RuntimeFailure {
  id: string;
  timestamp: string;
  operation: string;
  category: string;
  error_message: string;
  error_type: string;
  retry_count: number;
}


