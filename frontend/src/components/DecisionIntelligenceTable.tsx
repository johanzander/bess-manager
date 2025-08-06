import React, { useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { ChevronDown, ChevronRight, BarChart3, Clock } from 'lucide-react';

interface DecisionPattern {
  hour: number;
  batteryAction: number;
  immediateValue: number;
  futureValue: number;
  totalReward: number;
  gridPrice: number;
  isActual: boolean;
  isCurrentHour: boolean;
  strategicIntent: string;
  netStrategyValue: number;
  decisionLandscape: Array<{
    batteryAction: number;
    immediateReward: number;
    futureValue: number;
    totalReward: number;
    confidenceScore: number;
  }>;
  economicBreakdown: {
    gridPurchaseCost?: number;
    gridAvoidanceBenefit?: number;
    batteryCostBasis?: number;
    batteryWearCost?: number;
    exportRevenue?: number;
    netImmediateValue?: number;
  };
  futureTimeline: Array<{
    hour: number;
    contribution: number;
    action: number;
    actionType: string;
  }>;
  decisionConfidence: number;
  opportunityCost: number;
}

interface DecisionIntelligenceTableProps {
  patterns: DecisionPattern[];
}

export default function DecisionIntelligenceTable({ patterns }: DecisionIntelligenceTableProps) {
  // Track showTable state for each expanded hour/tab
  const [expandedHour, setExpandedHour] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<'landscape' | 'economic' | 'timeline'>('landscape');
  const [showTable, setShowTable] = useState<{ [key: string]: boolean }>({});
  // --- Move up: renderDecisionLandscape ---
  const renderDecisionLandscape = (pattern: DecisionPattern, showTable: boolean, setShowTable: (v: boolean) => void) => {
    if (!pattern.decisionLandscape || pattern.decisionLandscape.length === 0) {
      return (
        <div className="text-center py-8 text-gray-500">
          <BarChart3 className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p>Decision alternatives not available</p>
        </div>
      );
    }
    const chosenAction = pattern.batteryAction;
    const landscapeData = pattern.decisionLandscape.map((alt, index) => ({
      ...alt,
      isChosen: Math.abs(alt.batteryAction - chosenAction) < 0.1,
      status: Math.abs(alt.batteryAction - chosenAction) < 0.1 ? 'Chosen' : 'Alternative'
    }));
    return (
      <div className="space-y-4">
        {/* Tab-style toggle for graph/table, matching reference UI */}
        <div className="flex border-b border-gray-200 mb-2">
          <button
            className={`tab-toggle px-4 py-2 -mb-px text-sm font-medium focus:outline-none transition-colors border-b-2 ${!showTable ? 'border-blue-600 text-blue-600 bg-white' : 'border-transparent text-gray-500 bg-transparent hover:text-blue-600'}`}
            style={{ borderRadius: 0 }}
            onClick={() => setShowTable(false)}
          >
            Graph
          </button>
          <button
            className={`tab-toggle px-4 py-2 -mb-px text-sm font-medium focus:outline-none transition-colors border-b-2 ${showTable ? 'border-blue-600 text-blue-600 bg-white' : 'border-transparent text-gray-500 bg-transparent hover:text-blue-600'}`}
            style={{ borderRadius: 0 }}
            onClick={() => setShowTable(true)}
          >
            Table
          </button>
        </div>
        {!showTable ? (
          <div className="w-full h-56 bg-gray-100 flex items-center justify-center rounded text-gray-400 text-base" style={{fontFamily: 'inherit'}}>
            [Graph: Battery Action Analysis]
          </div>
        ) : (
          <table className="w-full" style={{fontFamily: 'inherit'}}>
            <thead>
              <tr className="border-b">
                <th className="text-left py-2">Action (kWh)</th>
                <th className="text-right py-2">Immediate</th>
                <th className="text-right py-2">Future</th>
                <th className="text-right py-2">Total</th>
                <th className="text-right py-2">Confidence</th>
                <th className="text-center py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {landscapeData.map((alt, index) => (
                <tr key={index} className={`border-b ${alt.isChosen ? 'bg-green-50' : ''}`} style={{fontFamily: 'inherit'}}>
                  <td className="py-2">{(alt.batteryAction ?? 0).toFixed(1)}</td>
                  <td className="text-right py-2">{formatValue(alt.immediateReward)}</td>
                  <td className="text-right py-2">{formatValue(alt.futureValue)}</td>
                  <td className="text-right py-2 font-semibold">{formatValue(alt.totalReward)}</td>
                  <td className="text-right py-2">{((alt.confidenceScore ?? 0) * 100).toFixed(0)}%</td>
                  <td className="text-center py-2">
                    <span className={`px-2 py-1 rounded text-xs ${
                      alt.isChosen 
                        ? 'bg-green-100 text-green-800' 
                        : 'bg-gray-100 text-gray-600'
                    }`}>
                      {alt.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    );
  };

  // --- Move up: renderFutureTimeline ---
  const renderFutureTimeline = (pattern: DecisionPattern, showTable: boolean, setShowTable: (v: boolean) => void) => {
    if (!pattern.futureTimeline || pattern.futureTimeline.length === 0) {
      return (
        <div className="text-center py-8 text-gray-500">
          <Clock className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p>Future timeline not available</p>
        </div>
      );
    }
    return (
      <div className="space-y-4">
        {/* Toggle for graph/table */}
        <div className="flex gap-2 mb-2">
          <button
            className={`px-3 py-1 rounded ${!showTable ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700'}`}
            onClick={() => setShowTable(false)}
          >
            Graph
          </button>
          <button
            className={`px-3 py-1 rounded ${showTable ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700'}`}
            onClick={() => setShowTable(true)}
          >
            Table
          </button>
        </div>
        {!showTable ? (
          <div className="w-full h-56 bg-gray-100 flex items-center justify-center rounded text-gray-400 text-base" style={{fontFamily: 'inherit'}}>
            [Graph: Future Value]
          </div>
        ) : (
          <table className="w-full" style={{fontFamily: 'inherit'}}>
            <thead>
              <tr className="border-b">
                <th className="text-left py-2">Hour</th>
                <th className="text-right py-2">Contribution (SEK)</th>
                <th className="text-right py-2">Action (kWh)</th>
                <th className="text-left py-2">Action Type</th>
              </tr>
            </thead>
            <tbody>
              {pattern.futureTimeline.map((item, index) => (
                <tr key={index} className="border-b" style={{fontFamily: 'inherit'}}>
                  <td className="py-2">{formatTime(item.hour)}</td>
                  <td className={`text-right py-2 ${
                    item.contribution >= 0 ? 'text-green-600' : 'text-red-600'
                  }`}>
                    {formatValue(item.contribution)}
                  </td>
                  <td className="text-right py-2">{formatValue(item.action)}</td>
                  <td className="py-2">{item.actionType}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    );
  };


  const toggleExpanded = (hour: number, isActual: boolean) => {
    if (isActual) return; // Don't expand actual hours
    if (expandedHour === hour) {
      setExpandedHour(null);
    } else {
      setExpandedHour(hour);
      setActiveTab('landscape'); // Reset to first tab when expanding
      setShowTable((prev) => ({ ...prev, [`${hour}-landscape`]: false, [`${hour}-timeline`]: false }));
    }
  };

  const formatValue = (value: number) => {
    return (value ?? 0) > 0 ? `+${(value ?? 0).toFixed(1)}` : (value ?? 0).toFixed(1);
  }

  const formatTime = (hour: number) => {
    return `${hour.toString().padStart(2, '0')}:00`;
  }



  const renderEconomicBreakdown = (pattern: DecisionPattern) => {
    const breakdown = pattern.economicBreakdown;
    if (!breakdown || Object.keys(breakdown).length === 0) {
      return <div className="text-center py-8 text-gray-500">No economic breakdown available.</div>;
    }
    // ...existing breakdown rendering logic...
  };

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
      <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
          Decision Intelligence Analysis
        </h3>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Comprehensive analysis of optimization decisions and alternatives
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse bg-white">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Hour</th>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Battery Action</th>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Immediate Value</th>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Future Value</th>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-700 uppercase border">Total Reward</th>
              <th className="border"></th>
            </tr>
          </thead>
          <tbody>
            {patterns.map((pattern) => (
              <React.Fragment key={pattern.hour}>
                <tr className={`hour-row ${pattern.isActual ? 'actual' : pattern.isCurrentHour ? 'current' : 'predicted'} cursor-pointer transition hover:bg-gray-50 ${pattern.isActual ? 'border-l-4 border-green-500 bg-gray-50' : pattern.isCurrentHour ? 'border-l-4 border-purple-500 bg-purple-50' : 'border-l-4 border-gray-200 bg-white'}`} onClick={() => toggleExpanded(pattern.hour, pattern.isActual)} data-hour={pattern.hour}>
                  {/* Hour column with badge inside */}
                  <td className="text-left align-middle font-medium text-gray-900">
                    <div className="flex items-center">
                      <span>{formatTime(pattern.hour)}</span>
                      {pattern.isActual && <span className="ml-2 px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">Actual</span>}
                      {pattern.isCurrentHour && <span className="ml-2 px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800">Current</span>}
                      {!pattern.isActual && !pattern.isCurrentHour && <span className="ml-2 px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800">Predicted</span>}
                    </div>
                  </td>
                  {/* Battery Action */}
                  <td className="text-center align-middle">
                    <div className={pattern.batteryAction > 0 ? 'text-green-600 font-medium' : pattern.batteryAction < 0 ? 'text-red-600 font-medium' : 'text-gray-500 font-medium'}>
                      {pattern.batteryAction > 0 ? '+' : ''}{(pattern.batteryAction ?? 0).toFixed(1)} kWh
                    </div>
                    <span className="text-xs text-gray-500 font-normal block">{pattern.batteryAction > 0 ? 'Charge' : pattern.batteryAction < 0 ? 'Discharge' : 'Hold'}</span>
                  </td>
                  {/* Immediate Value */}
                  <td className="text-center align-middle">
                    <div className={pattern.immediateValue > 0 ? 'text-green-600 font-medium' : pattern.immediateValue < 0 ? 'text-red-600 font-medium' : 'text-gray-500 font-medium'}>
                      {pattern.immediateValue > 0 ? '+' : ''}{(pattern.immediateValue ?? 0).toFixed(1)}
                    </div>
                    <span className="text-xs text-gray-500 font-normal block">SEK</span>
                  </td>
                  {/* Future Value */}
                  <td className="text-center align-middle">
                    <div className={pattern.futureValue > 0 ? 'text-green-600 font-medium' : pattern.futureValue < 0 ? 'text-red-600 font-medium' : 'text-gray-500 font-medium'}>
                      {pattern.futureValue > 0 ? '+' : ''}{(pattern.futureValue ?? 0).toFixed(1)}
                    </div>
                    <span className="text-xs text-gray-500 font-normal block">SEK</span>
                  </td>
                  {/* Total Reward */}
                  <td className="text-center align-middle">
                    <div className={(pattern.totalReward ?? 0) > 0 ? 'text-green-600 font-medium' : (pattern.totalReward ?? 0) < 0 ? 'text-red-600 font-medium' : 'text-gray-500 font-medium'}>
                      {(pattern.totalReward ?? 0) > 0 ? '+' : ''}{(pattern.totalReward ?? 0).toFixed(1)}
                    </div>
                    <span className="text-xs text-gray-500 font-normal block">SEK</span>
                  </td>
                  {/* Expand icon */}
                  <td className="text-center align-middle">
                    <svg className="expand-icon w-4 h-4 text-gray-400 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" /></svg>
                  </td>
                </tr>

                {expandedHour === pattern.hour && !pattern.isActual && (
                  <tr>
                    <td colSpan={8} className="px-6 py-4 bg-gray-50 dark:bg-gray-900/50">
                      <div className="space-y-4">
                        {/* Tab Navigation - Use project font, correct names, no icons */}
                        <div className="flex space-x-1 bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
                          <button
                            onClick={(e) => { e.stopPropagation(); setActiveTab('landscape'); }}
                            className={`px-4 py-2 text-base rounded-md transition-colors font-normal ${
                              activeTab === 'landscape'
                                ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                                : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white'
                            }`}
                          >
                            Battery Action
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); setActiveTab('economic'); }}
                            className={`px-4 py-2 text-base rounded-md transition-colors font-normal ${
                              activeTab === 'economic'
                                ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                                : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white'
                            }`}
                          >
                            Immediate Value
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); setActiveTab('timeline'); }}
                            className={`px-4 py-2 text-base rounded-md transition-colors font-normal ${
                              activeTab === 'timeline'
                                ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                                : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white'
                            }`}
                          >
                            Future Value
                          </button>
                        </div>

                        {/* No view toggle, just section title with project font */}
                        <div className="flex items-center justify-between">
                          <h4 className="text-base font-normal text-gray-900 dark:text-white">
                            {activeTab === 'landscape' && 'Battery Action Analysis'}
                            {activeTab === 'economic' && 'Immediate Value Analysis'}
                            {activeTab === 'timeline' && 'Future Value'}
                          </h4>
                        </div>

                        {/* Content with graph/table toggle for relevant tabs */}
                        <div className="bg-white dark:bg-gray-800 rounded-lg p-4">
                          {activeTab === 'landscape' && renderDecisionLandscape(
                            pattern,
                            showTable[`${pattern.hour}-landscape`] ?? false,
                            (v: boolean) => setShowTable((prev) => ({ ...prev, [`${pattern.hour}-landscape`]: v }))
                          )}
                          {activeTab === 'economic' && renderEconomicBreakdown(pattern)}
                          {activeTab === 'timeline' && renderFutureTimeline(
                            pattern,
                            showTable[`${pattern.hour}-timeline`] ?? false,
                            (v: boolean) => setShowTable((prev) => ({ ...prev, [`${pattern.hour}-timeline`]: v }))
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                )}

                {expandedHour === pattern.hour && pattern.isActual && (
                  <tr>
                    <td colSpan={8} className="px-6 py-4 bg-gray-50 dark:bg-gray-900/50 text-center text-gray-500">
                      <Clock className="w-8 h-8 mx-auto mb-2 opacity-50" />
                      <p className="text-sm">
                        Decision intelligence is only available for predicted hours.
                      </p>
                      <p className="text-xs mt-2 text-gray-400">
                        Future versions will store decision data for comparison with actual results.
                      </p>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>

      <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <span className="text-gray-500 dark:text-gray-400">Predicted Net Value:</span>
            <span className="ml-2 font-medium text-gray-900 dark:text-white">
              {patterns.filter(p => !p.isActual).reduce((sum, p) => sum + (p.netStrategyValue ?? 0), 0).toFixed(2)} SEK
            </span>
          </div>
          <div>
            <span className="text-gray-500 dark:text-gray-400">Avg Confidence:</span>
            <span className="ml-2 font-medium text-gray-900 dark:text-white">
              {(() => {
                const predictedPatterns = patterns.filter(p => !p.isActual);
                return predictedPatterns.length > 0
                  ? ((predictedPatterns.reduce((sum, p) => sum + (p.decisionConfidence ?? 0), 0) / predictedPatterns.length) * 100).toFixed(0)
                  : 'N/A';
              })()}%
            </span>
          </div>
          <div>
            <span className="text-gray-500 dark:text-gray-400">Opportunity Cost:</span>
            <span className="ml-2 font-medium text-red-600 dark:text-red-400">
              {patterns.filter(p => !p.isActual).reduce((sum, p) => sum + (p.opportunityCost ?? 0), 0).toFixed(2)} SEK
            </span>
          </div>
          <div>
            <span className="text-gray-500 dark:text-gray-400">Predicted Hours:</span>
            <span className="ml-2 font-medium text-gray-900 dark:text-white">
              {patterns.filter(p => !p.isActual).length} / {patterns.length}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}