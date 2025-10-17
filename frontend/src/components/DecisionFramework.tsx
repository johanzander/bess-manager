// frontend/src/components/DecisionFramework.tsx

import React, { useState, useEffect } from 'react';
import { 
  Brain, 
  TrendingUp, 
  Clock, 
  DollarSign, 
  Target, 
  AlertTriangle, 
  ChevronDown, 
  ChevronUp,
  Sun,
  Home,
  Battery,
  Grid,
  ArrowRight,
  LineChart,
  Activity
} from 'lucide-react';
import { fetchDecisionIntelligence } from '../lib/decisionIntelligenceAPI';
import { FlowPattern } from '../types/decisionFramework';

// Utility functions - NO FORMATTING LOGIC, just display helpers
const getDisplayValue = (field: any) => {
  if (typeof field === 'object' && field?.display !== undefined) {
    return field.display;
  }
  return field?.toString() || '0';
};

const getDisplayUnit = (field: any) => {
  if (typeof field === 'object' && field?.unit !== undefined) {
    return field.unit;
  }
  return '';
};

const getDisplayText = (field: any) => {
  if (typeof field === 'object' && field?.text !== undefined) {
    return field.text;
  }
  return field?.toString() || '-';
};

const getFlowIcon = (flowType: string) => {
  if (flowType.toLowerCase().includes('solar')) return Sun;
  if (flowType.toLowerCase().includes('grid')) return Grid;
  if (flowType.toLowerCase().includes('battery')) return Battery;
  if (flowType.toLowerCase().includes('home')) return Home;
  return Activity;
};

const getFlowColor = (flowType: string) => {
  if (flowType.toLowerCase().includes('solar')) return 'text-yellow-600 dark:text-yellow-400';
  if (flowType.toLowerCase().includes('grid')) return 'text-blue-600 dark:text-blue-400';
  if (flowType.toLowerCase().includes('battery')) return 'text-green-600 dark:text-green-400';
  if (flowType.toLowerCase().includes('home')) return 'text-purple-600 dark:text-purple-400';
  return 'text-gray-600 dark:text-gray-400';
};

// DetailedFlowPatternCard component
const DetailedFlowPatternCard: React.FC<{ pattern: FlowPattern }> = ({ pattern }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  const getRowColor = () => {
    if (pattern.isCurrentHour) return 'bg-purple-50 dark:bg-purple-900/20 border-l-4 border-purple-500';
    if (pattern.isActual) return 'border-l-4 border-green-500';
    return 'border-l-4 border-transparent';
  };

  const getValueColor = (value: any) => {
    const numValue = typeof value === 'object' ? value.value : value;
    if (numValue > 0) return 'text-green-600 dark:text-green-400';
    if (numValue < 0) return 'text-red-600 dark:text-red-400';
    return 'text-gray-600 dark:text-gray-400';
  };


  const getBatteryAction = () => {
    // Helper function to safely get numeric value
    const getNumericValue = (field: any): number => {
      if (!field) return 0;
      return typeof field === 'object' ? (field.value || 0) : (field || 0);
    };

    const chargingValue = getNumericValue(pattern.flows.gridToBattery) + getNumericValue(pattern.flows.solarToBattery);
    const dischargingValue = getNumericValue(pattern.flows.batteryToHome) + getNumericValue(pattern.flows.batteryToGrid);

    const charging = { value: chargingValue, display: chargingValue.toFixed(1), unit: 'kWh', text: `${chargingValue.toFixed(1)} kWh` };
    const discharging = { value: dischargingValue, display: dischargingValue.toFixed(1), unit: 'kWh', text: `${dischargingValue.toFixed(1)} kWh` };

    if (chargingValue > 0.1 && dischargingValue < 0.1) {
      return {
        action: 'Charge',
        amount: charging,
        icon: Battery,
        color: 'text-blue-600 dark:text-blue-400',
        description: getDisplayText(charging)
      };
    } else if (dischargingValue > 0.1 && chargingValue < 0.1) {
      return {
        action: 'Discharge',
        amount: discharging,
        icon: Battery,
        color: 'text-orange-600 dark:text-orange-400',
        description: getDisplayText(discharging)
      };
    } else if (chargingValue > 0.1 && dischargingValue > 0.1) {
      const mixedAmount = { value: chargingValue + dischargingValue, display: (chargingValue + dischargingValue).toFixed(1), unit: 'kWh', text: `${(chargingValue + dischargingValue).toFixed(1)} kWh` };
      return {
        action: 'Mixed',
        amount: mixedAmount,
        icon: Activity,
        color: 'text-purple-600 dark:text-purple-400',
        description: `${getDisplayText(charging)} / ${getDisplayText(discharging)}`
      };
    } else {
      return {
        action: 'Idle',
        amount: 0,
        icon: Activity,
        color: 'text-gray-500 dark:text-gray-400',
        description: 'No significant action'
      };
    }
  };

  const getEnergyFlowsSummary = () => {
    // Helper function to safely get numeric value
    const getNumericValue = (field: any): number => {
      if (!field) return 0;
      return typeof field === 'object' ? (field.value || 0) : (field || 0);
    };

    const flows = [];
    if (getNumericValue(pattern.flows.solarToHome) > 0.1) flows.push(`Solar→Home: ${getDisplayText(pattern.flows.solarToHome)}`);
    if (getNumericValue(pattern.flows.solarToBattery) > 0.1) flows.push(`Solar→Battery: ${getDisplayText(pattern.flows.solarToBattery)}`);
    if (getNumericValue(pattern.flows.solarToGrid) > 0.1) flows.push(`Solar→Grid: ${getDisplayText(pattern.flows.solarToGrid)}`);
    if (getNumericValue(pattern.flows.gridToHome) > 0.1) flows.push(`Grid→Home: ${getDisplayText(pattern.flows.gridToHome)}`);
    if (getNumericValue(pattern.flows.gridToBattery) > 0.1) flows.push(`Grid→Battery: ${getDisplayText(pattern.flows.gridToBattery)}`);
    if (getNumericValue(pattern.flows.batteryToHome) > 0.1) flows.push(`Battery→Home: ${getDisplayText(pattern.flows.batteryToHome)}`);
    if (getNumericValue(pattern.flows.batteryToGrid) > 0.1) flows.push(`Battery→Grid: ${getDisplayText(pattern.flows.batteryToGrid)}`);

    return flows.length > 0 ? flows.join(', ') : 'No significant flows';
  };

  const significantFlows = Object.entries(pattern.flows)
    .filter(([_, value]) => Math.abs(typeof value === 'object' ? value.value : value) >= 0.1)
    .map(([key, value]) => {
      // Convert the camelCase key to a display-friendly format
      const displayKey = key
        .replace(/([A-Z])/g, " $1") // Add spaces before capitals
        .replace(/To/g, "→")        // Replace "To" with arrow
        .toUpperCase();              // Make it all uppercase
      
      return {
        key,
        value,
        displayName: displayKey,
        iconComponent: getFlowIcon(key),
        colorClass: getFlowColor(key),
        economicValue: pattern.immediateFlowValues[key] || 0
      };
    });

  const batteryAction = getBatteryAction();

  return (
    <div className={`transition-all duration-200 hover:bg-gray-50 dark:hover:bg-gray-700/50 ${getRowColor()}`}>
      <div className="p-4">
        <div className="grid grid-cols-12 gap-4 items-center">
          {/* Time & Price */}
          <div className="col-span-2">
            <div className="flex items-center">
              <Clock className="h-4 w-4 mr-2 text-gray-500 dark:text-gray-400" />
              <div>
                <div className="font-semibold text-gray-900 dark:text-white">
                  {pattern.hour.toString().padStart(2, '0')}:00
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400">
                    <span>
                      <span className="font-medium">{getDisplayValue(pattern.electricityPrice)}</span>
                      <span className="text-xs ml-1 opacity-70">{getDisplayUnit(pattern.electricityPrice)}</span>
                    </span>
                </div>
              </div>
            </div>
            <div className="flex mt-1 space-x-1">
              {pattern.isCurrentHour && (
                <span className="px-1.5 py-0.5 bg-purple-100 dark:bg-purple-900 text-purple-800 dark:text-purple-200 text-xs rounded">
                  Current
                </span>
              )}
              {pattern.isActual && (
                <span className="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200 text-xs rounded">
                  Actual
                </span>
              )}
            </div>
          </div>

          {/* Battery Actions */}
          <div className="col-span-2">
            <div className="flex items-center">
              <batteryAction.icon className={`h-4 w-4 mr-2 ${batteryAction.color}`} />
              <div>
                <div className={`font-medium text-sm ${batteryAction.color}`}>
                  {batteryAction.action}
                </div>
                <div className="text-xs text-gray-600 dark:text-gray-400">
                  {batteryAction.description}
                </div>
              </div>
            </div>
          </div>

          {/* Rationale/Context */}
          <div className="col-span-3">
            <div className="text-sm text-gray-700 dark:text-gray-300">
              {pattern.economicContextDescription}
            </div>
          </div>

          {/* Energy Flows */}
          <div className="col-span-2">
            <div className="text-xs text-gray-600 dark:text-gray-400 font-mono">
              {getEnergyFlowsSummary()}
            </div>
          </div>

          {/* Strategy Value with Details Toggle */}
          <div className="col-span-3">
            <div className="flex items-center justify-between">
              <div className="text-right flex-1">
                <div className={`text-lg font-bold ${getValueColor(pattern.netStrategyValue)}`}>
                    <span>
                      <span>{getDisplayValue(pattern.netStrategyValue)}</span>
                      <span className="text-sm font-normal ml-1 opacity-70">{getDisplayUnit(pattern.netStrategyValue)}</span>
                    </span>
                </div>

                <div className="flex justify-end space-x-3 mt-1">
                  <div className="text-center">
                    <div className="text-xs text-gray-500 dark:text-gray-400">Now</div>
                    <div className={`text-xs font-medium ${getValueColor(pattern.immediateTotalValue)}`}>
                        <span>
                          <span>{getDisplayValue(pattern.immediateTotalValue)}</span>
                          <span className="text-xs ml-1 opacity-70">{getDisplayUnit(pattern.immediateTotalValue)}</span>
                        </span>
                    </div>
                  </div>
                  <div className="text-center">
                    <div className="text-xs text-gray-500 dark:text-gray-400">Future</div>
                    <div className={`text-xs font-medium ${getValueColor(pattern.futureOpportunity.expectedValue)}`}>
                        <span>
                          <span>{getDisplayValue(pattern.futureOpportunity.expectedValue)}</span>
                          <span className="text-xs ml-1 opacity-70">{getDisplayUnit(pattern.futureOpportunity.expectedValue)}</span>
                        </span>
                    </div>
                  </div>
                </div>
              </div>
              
              <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="ml-2 p-1 text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded transition-colors"
                title={isExpanded ? "Hide details" : "Show details"}
              >
                {isExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Expanded Details */}
      {isExpanded && (
        <div className="mt-4 space-y-4 border-t pt-4 px-4">
          {/* Detailed Flow Analysis */}
          <div>
            <h4 className="font-semibold text-gray-900 dark:text-white mb-3 flex items-center">
              <LineChart className="h-4 w-4 mr-2" />
              Detailed Flow Analysis
            </h4>
            <div className="grid grid-cols-12 gap-4 text-sm bg-gray-50 dark:bg-gray-700/30 rounded-lg p-3">
              <div className="col-span-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                Flow Type
              </div>
              <div className="col-span-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                Action
              </div>
              <div className="col-span-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                Purpose
              </div>
              <div className="col-span-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                Energy
              </div>
              <div className="col-span-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase text-right">
                Economic Value
              </div>
              
              {significantFlows.map((flow, index) => (
                <React.Fragment key={index}>
                  <div className="col-span-2 flex items-center py-2 border-t border-gray-200 dark:border-gray-600">
                    <flow.iconComponent className={`h-3 w-3 mr-2 ${flow.colorClass}`} />
                    <span className="text-gray-700 dark:text-gray-300 text-xs font-mono">
                      {flow.displayName}
                    </span>
                  </div>
                  
                  <div className="col-span-2 py-2 border-t border-gray-200 dark:border-gray-600">
                    <span className={`font-medium text-xs ${flow.colorClass}`}>
                      Energy flow
                    </span>
                  </div>
                  
                  <div className="col-span-3 py-2 border-t border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-400 text-xs">
                    {flow.key === 'gridToHome' && 'Grid electricity for immediate home consumption'}
                    {flow.key === 'gridToBattery' && 'Grid electricity stored in battery for future use'}
                    {flow.key === 'solarToHome' && 'Solar energy directly consumed by home'}
                    {flow.key === 'solarToBattery' && 'Solar energy stored in battery for later use'}
                    {flow.key === 'solarToGrid' && 'Excess solar energy exported to grid'}
                    {flow.key === 'batteryToHome' && 'Battery energy discharged for home consumption'}
                    {flow.key === 'batteryToGrid' && 'Battery energy exported to grid for revenue'}
                  </div>
                  
                  <div className="col-span-2 py-2 border-t border-gray-200 dark:border-gray-600 font-mono text-xs text-gray-600 dark:text-gray-400">
                      <span>
                        <span className="font-medium">{getDisplayValue(flow.value)}</span>
                        <span className="ml-1 opacity-70">{getDisplayUnit(flow.value)}</span>
                      </span>
                  </div>
                  
                  <div className="col-span-3 py-2 border-t border-gray-200 dark:border-gray-600 text-right">
                    <div className={`font-medium ${getValueColor(flow.economicValue)}`}>
                        <span>
                          <span>{getDisplayValue(flow.economicValue)}</span>
                          <span className="text-xs ml-1 opacity-70">{getDisplayUnit(flow.economicValue)}</span>
                        </span>
                    </div>
                  </div>
                </React.Fragment>
              ))}
            </div>
          </div>

          {/* Economic Strategy Chain */}
          <div>
            <h4 className="font-semibold text-gray-900 dark:text-white mb-3 flex items-center">
              <ArrowRight className="h-4 w-4 mr-2" />
              Economic Strategy Chain
            </h4>
            <div className="bg-gradient-to-r from-blue-50 to-green-50 dark:from-blue-900/20 dark:to-green-900/20 rounded-lg border border-blue-200 dark:border-blue-700 p-4">
              <div className="space-y-3">
                {pattern.economicChain.split('→').map((segment: string, index: number, array: string[]) => (
                  <div key={index} className="flex items-center">
                    {index > 0 && (
                      <div className="flex items-center justify-center mr-3">
                        <ArrowRight className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                      </div>
                    )}
                    <div className={`flex-1 p-3 rounded-lg ${
                      index === 0 ? 'bg-red-100 dark:bg-red-900/30 border-l-4 border-red-400' :
                      index === array.length - 1 ? 'bg-green-100 dark:bg-green-900/30 border-l-4 border-green-400' :
                      'bg-blue-100 dark:bg-blue-900/30 border-l-4 border-blue-400'
                    }`}>
                      <div className="text-sm text-gray-700 dark:text-gray-300">
                        {segment.trim().split(' ').map((word: string, wordIndex: number) => {
                          // Highlight numeric values (currency amounts, etc.)
                          const isNumericValue = word.match(/[+-]?\d+\.\d+/);
                          if (isNumericValue) {
                            return (
                              <strong key={wordIndex} className={
                                word.includes('-') || word.includes('cost') ?
                                'text-red-600 dark:text-red-400' :
                                'text-green-600 dark:text-green-400'
                              }>
                                {word + ' '}
                              </strong>
                            );
                          }
                          if (word.match(/\d{2}:\d{2}/)) {
                            return <strong key={wordIndex} className="text-blue-600 dark:text-blue-400">{word + ' '}</strong>;
                          }
                          if (word.match(/\d+\.\d+kWh/)) {
                            return <strong key={wordIndex} className="text-purple-600 dark:text-purple-400">{word + ' '}</strong>;
                          }
                          return word + ' ';
                        })}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Future Opportunity */}
          {pattern.futureOpportunity.description && (
            <div>
              <h4 className="font-semibold text-gray-900 dark:text-white mb-3 flex items-center">
                <Target className="h-4 w-4 mr-2" />
                Future Opportunity
              </h4>
              <div className="p-4 bg-green-50 dark:bg-green-900/20 rounded-lg border-l-4 border-green-400">
                <p className="text-gray-700 dark:text-gray-300 mb-2">
                  {pattern.futureOpportunity.description}
                </p>
                {pattern.futureOpportunity.targetHours.length > 0 && (
                  <div className="flex items-center text-sm text-gray-600 dark:text-gray-400">
                    <Clock className="h-3 w-3 mr-2" />
                    <span className="mr-2">Target hours:</span>
                    <div className="flex space-x-1">
                      {pattern.futureOpportunity.targetHours.map((h, i) => (
                        <span key={i} className="inline-flex items-center px-2 py-1 bg-green-100 dark:bg-green-800 text-green-800 dark:text-green-200 text-xs rounded font-mono">
                          {h.toString().padStart(2, '0')}:00
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// Main Decision Framework Component
const DecisionFramework: React.FC = () => {
  const [decisionData, setDecisionData] = useState<FlowPattern[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTimeRange, setSelectedTimeRange] = useState<'all' | 'actual' | 'predicted'>('all');

  useEffect(() => {
    const loadData = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const data = await fetchDecisionIntelligence();
        setDecisionData(data);
      } catch (err) {
        setError('Failed to load decision data');
        console.error('Failed to load decision data:', err);
      } finally {
        setIsLoading(false);
      }
    };

    loadData();
  }, []);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="animate-pulse space-y-6">
          <div className="h-8 bg-gray-200 dark:bg-gray-700 rounded w-1/3"></div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="h-32 bg-gray-200 dark:bg-gray-700 rounded"></div>
            <div className="h-32 bg-gray-200 dark:bg-gray-700 rounded"></div>
            <div className="h-32 bg-gray-200 dark:bg-gray-700 rounded"></div>
          </div>
          <div className="h-64 bg-gray-200 dark:bg-gray-700 rounded"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-6">
        <div className="flex items-center">
          <AlertTriangle className="h-6 w-6 text-red-600 dark:text-red-400 mr-3" />
          <div>
            <h3 className="font-semibold text-red-900 dark:text-red-100">Error Loading Decision Data</h3>
            <p className="text-red-800 dark:text-red-200 text-sm">{error}</p>
          </div>
        </div>
      </div>
    );
  }

  const filteredData = decisionData.filter(pattern => {
    if (selectedTimeRange === 'actual') return pattern.isActual;
    if (selectedTimeRange === 'predicted') return !pattern.isActual;
    return true;
  });

  // Helper function to safely get numeric value from strategy value
  const getStrategyValue = (field: any): number => {
    if (!field) return 0;
    return typeof field === 'object' ? (field.value || 0) : (field || 0);
  };

  const totalNetValueNum = filteredData.reduce((sum, pattern) => sum + getStrategyValue(pattern.netStrategyValue), 0);
  const totalNetValue = { value: totalNetValueNum, display: totalNetValueNum.toFixed(2), unit: 'SEK', text: `${totalNetValueNum.toFixed(2)} SEK` };
  const bestDecision = filteredData.reduce((best, current) =>
    getStrategyValue(current.netStrategyValue) > getStrategyValue(best.netStrategyValue) ? current : best,
    filteredData[0]
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center">
            <Brain className="h-6 w-6 mr-3 text-purple-600 dark:text-purple-400" />
            Decision Intelligence
          </h2>
          <p className="text-gray-600 dark:text-gray-400 mt-1">
            Detailed economic reasoning and forward-looking analysis for each battery decision
          </p>
        </div>
        
        <div className="flex items-center space-x-4">
          <select
            value={selectedTimeRange}
            onChange={(e) => setSelectedTimeRange(e.target.value as any)}
            className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm"
          >
            <option value="all">All Hours</option>
            <option value="actual">Actual Data</option>
            <option value="predicted">Predictions</option>
          </select>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white dark:bg-gray-800 p-4 rounded-lg shadow border">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Total Net Strategy Value</p>
              <p className={`text-xl font-bold ${getDisplayValue(totalNetValue) >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                <span>{getDisplayValue(totalNetValue)}</span>
                <span className="text-sm font-normal ml-1 opacity-70">{getDisplayUnit(totalNetValue)}</span>
              </p>
            </div>
            <DollarSign className="h-6 w-6 text-green-600 dark:text-green-400" />
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 p-4 rounded-lg shadow border">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Best Decision Hour</p>
              <p className="text-xl font-bold text-gray-900 dark:text-white">
                {bestDecision?.hour.toString().padStart(2, '0')}:00
              </p>
              <p className="text-sm text-green-600 dark:text-green-400">
                {bestDecision ? (
                  <span>
                    <span>+{getDisplayValue(bestDecision.netStrategyValue)}</span>
                    <span className="text-xs ml-1 opacity-70">{getDisplayUnit(bestDecision.netStrategyValue)}</span>
                  </span>
                ) : 'N/A'}
              </p>
            </div>
            <TrendingUp className="h-6 w-6 text-blue-600 dark:text-blue-400" />
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 p-4 rounded-lg shadow border">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Active Decisions</p>
              <p className="text-xl font-bold text-gray-900 dark:text-white">
                {filteredData.length}
              </p>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {filteredData.filter(d => d.isActual).length} actual, {filteredData.filter(d => !d.isActual).length} predicted
              </p>
            </div>
            <Activity className="h-6 w-6 text-purple-600 dark:text-purple-400" />
          </div>
        </div>
      </div>

      {/* Decision Table */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow border">
        {/* Table Header */}
        <div className="border-b border-gray-200 dark:border-gray-700 p-4 bg-gray-50 dark:bg-gray-700/50">
          <div className="grid grid-cols-12 gap-4 items-center text-sm font-medium text-gray-700 dark:text-gray-300">
            <div className="col-span-2">Time & Price</div>
            <div className="col-span-2">Battery Actions</div>
            <div className="col-span-3">Rationale</div>
            <div className="col-span-2">Energy Flows</div>
            <div className="col-span-3 text-right">Strategy Value</div>
          </div>
        </div>

        {/* Decision Rows */}
        <div className="divide-y divide-gray-200 dark:divide-gray-700">
          {filteredData.map((pattern) => (
            <DetailedFlowPatternCard key={pattern.hour} pattern={pattern} />
          ))}
        </div>
      </div>
    </div>
  );
};

export default DecisionFramework;