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
    batteryLevel: number;
    action: number;
    gridUsed: number;
    gridCost: number;     
    batteryCost: number; 
    totalCost: number;   
    savings: number;
    consumption: number;
    solarCharged: number;
  }
  
  export interface ScheduleSummary {
    baseCost: number;
    optimizedCost: number;
    savings: number;
    cycleCount: number;
    gridCosts: number;    
    batteryCosts: number;
  }
  
  export interface ScheduleData {
    hourlyData: HourlyData[];
    summary: ScheduleSummary;
  }