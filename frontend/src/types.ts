export type AreaCode = 'SE1' | 'SE2' | 'SE3' | 'SE4';

export interface BatterySettings {
  totalCapacity: number;
  reservedCapacity: number;
  estimatedConsumption: number;
  maxChargeDischarge: number;
  chargeCycleCost: number;
  chargingPowerRate: number;
  useActualPrice: boolean;
}

export interface ElectricitySettings {
  markupRate: number;
  vatMultiplier: number;
  additionalCosts: number;
  taxReduction: number;
  area: AreaCode;
}

export interface PriceData {
  timestamp: string;
  price: number;
  buy_price: number;
  sell_price: number;
}

export interface HourlyData {
  hour: string;
  price: number;
  consumption: number;
  baseCost: number;
  batteryLevel: number;
  action: number;
  gridUsed?: number;     // Grid energy needed in Solar+Battery case
  gridCost: number;      // Cost of grid energy in Solar+Battery case
  batteryCost: number;   // Cost of battery operations
  totalCost: number;     // Total cost in Solar+Battery case
  savings: number;       // Total savings compared to Grid-Only case
  
  // Solar fields
  solarProduction?: number;    // Total solar production this hour
  solarCharged?: number;       // For backward compatibility
  directSolarUsed?: number;    // Solar energy directly used
  solarExcess?: number;        // Excess solar not immediately used
  
  // Solar-only scenario fields
  solarOnlyGridNeeded?: number; // Grid energy needed in Solar-Only case
  solarOnlyCost?: number;       // Cost in Solar-Only case
  solarOnlySavings?: number;    // Savings in Solar-Only case compared to Grid-Only
}

export interface ScheduleSummary {
  baseCost: number;               // Grid-Only total cost
  optimizedCost: number;          // Solar+Battery total cost
  savings: number;                // Total savings (Grid-Only - Optimized)
  cycleCount?: number;            // Battery cycle count
  gridCosts: number;              // Grid energy costs in Optimized case
  batteryCosts: number;           // Battery operation costs
  
  // Enhanced reporting fields
  solarOnlyCost?: number;         // Cost with solar but no battery
  solarOnlySavings?: number;      // Savings from solar only
  batterySavings?: number;        // Additional savings from battery
  totalSolarProduction?: number;  // Total solar production
  totalBatteryCharge?: number;    // Total energy charged to battery
  totalBatteryDischarge?: number; // Total energy discharged from battery
}

export interface ScheduleData {
  hourlyData: HourlyData[];
  summary: ScheduleSummary;
}