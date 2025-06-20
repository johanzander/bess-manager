// frontend/src/types/decisionFramework.tsx

export interface DetailedEnergyFlows {
  solarToHome: number;
  solarToBattery: number;
  solarToGrid: number;
  gridToHome: number;
  gridToBattery: number;
  batteryToHome: number;
  batteryToGrid: number;
}

export interface FutureOpportunity {
  description: string;
  targetHours: number[];
  expectedValue: number;
  dependencies: string[];
}

export interface FlowPattern {
  hour: number;
  patternName: string;
  flowDescription: string;
  economicContextDescription: string;
  flows: DetailedEnergyFlows;
  immediateFlowValues: { [key: string]: number };
  immediateTotalValue: number;
  futureOpportunity: FutureOpportunity;
  economicChain: string;
  netStrategyValue: number;
  riskFactors: string[];
  electricityPrice: number;
  isCurrentHour: boolean;
  isActual: boolean;
}

export interface DecisionIntelligenceResponse {
  patterns: FlowPattern[];
  summary: {
    totalNetValue: number;
    bestDecisionHour: number;
    bestDecisionValue: number;
    actualHoursCount: number;
    predictedHoursCount: number;
  };
}