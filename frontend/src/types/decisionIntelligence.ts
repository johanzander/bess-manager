// frontend/src/types/decisionIntelligence.ts

export interface DecisionAlternative {
  batteryAction: number;
  immediateReward: number;
  futureValue: number;
  totalReward: number;
  confidenceScore: number;
}

export interface EconomicBreakdown {
  gridPurchaseCost: number;
  gridAvoidanceBenefit: number;
  batteryCostBasis: number;
  batteryWearCost: number;
  exportRevenue: number;
  netImmediateValue: number;
}

export interface FutureValueContribution {
  hour: number;
  contribution: number;
  action: number;
  actionType: string;
}

export interface DecisionContext {
  gridPrice: number;
  consumption: number;
  solarProduction: number;
  batterySoe: number;
}

export interface DecisionPattern {
  hour: number;
  batteryAction: number;
  strategicIntent: string;
  patternName: string;
  description: string;
  economicChain: string;
  immediateValue: number;
  futureValue: number;
  netStrategyValue: number;
  costBasis: number;
  isCurrentHour: boolean;
  isActual: boolean;
  
  // Enhanced decision intelligence fields
  decisionLandscape: DecisionAlternative[];
  economicBreakdown: EconomicBreakdown;
  futureTimeline: FutureValueContribution[];
  decisionConfidence: number;
  opportunityCost: number;
  context: DecisionContext;
}

export interface DecisionIntelligenceSummary {
  totalNetValue: number;
  bestDecisionHour: number;
  bestDecisionValue: number;
  actualHoursCount: number;
  predictedHoursCount: number;
  averageConfidence: number;
  totalOpportunityCost: number;
  hoursWithAlternatives: number;
  analysisVersion: string;
}

export interface DecisionIntelligenceResponse {
  patterns: DecisionPattern[];
  summary: DecisionIntelligenceSummary;
}

// Analysis view types
export type AnalysisView = 'landscape' | 'economic' | 'future';
export type DisplayMode = 'chart' | 'table';