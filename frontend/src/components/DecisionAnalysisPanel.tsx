import React, { useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { BarChart3, Table2, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { DecisionPattern, AnalysisView, DisplayMode } from '../types/decisionIntelligence';

interface DecisionAnalysisPanelProps {
  pattern: DecisionPattern;
  view: AnalysisView;
  className?: string;
}

const DecisionAnalysisPanel: React.FC<DecisionAnalysisPanelProps> = ({
  pattern,
  view,
  className = '',
}) => {
  const [displayMode, setDisplayMode] = useState<DisplayMode>('chart');

  const renderModeToggle = () => (
    <div className="flex items-center gap-2 mb-4">
      <button
        onClick={() => setDisplayMode('chart')}
        className={`flex items-center gap-1 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
          displayMode === 'chart'
            ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
            : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800'
        }`}
      >
        <BarChart3 className="h-4 w-4" />
        Chart
      </button>
      <button
        onClick={() => setDisplayMode('table')}
        className={`flex items-center gap-1 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
          displayMode === 'table'
            ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
            : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800'
        }`}
      >
        <Table2 className="h-4 w-4" />
        Table
      </button>
    </div>
  );

  const renderDecisionLandscape = () => {
    if (!pattern.decisionLandscape || pattern.decisionLandscape.length === 0) {
      return (
        <div className="text-center py-8 text-gray-500 dark:text-gray-400">
          No alternative actions available for this hour
        </div>
      );
    }

    // Prepare data for chart
    const chartData = pattern.decisionLandscape.map((alt, index) => ({
      name: `${alt.batteryAction.toFixed(1)} kWh`,
      totalReward: alt.totalReward,
      immediateReward: alt.immediateReward,
      futureValue: alt.futureValue,
      confidence: alt.confidenceScore,
      isChosen: Math.abs(alt.batteryAction - (pattern.batteryAction || 0)) < 0.01,
      index,
    }));

    if (displayMode === 'chart') {
      return (
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis 
                dataKey="name" 
                tick={{ fontSize: 12, fill: 'currentColor' }}
                angle={-45}
                textAnchor="end"
                height={60}
              />
              <YAxis 
                tick={{ fontSize: 12, fill: 'currentColor' }}
                label={{ value: 'Reward (SEK)', angle: -90, position: 'insideLeft' }}
              />
              <Tooltip 
                contentStyle={{ 
                  backgroundColor: 'var(--tw-bg-opacity, 1)', 
                  border: '1px solid #d1d5db',
                  borderRadius: '0.5rem'
                }}
                formatter={(value: number, name: string) => [
                  `${value.toFixed(2)} SEK`,
                  name === 'totalReward' ? 'Total Reward' : 
                  name === 'immediateReward' ? 'Immediate Reward' : 'Future Value'
                ]}
                labelFormatter={(label) => `Action: ${label}`}
              />
              <Bar dataKey="totalReward" name="totalReward">
                {chartData.map((entry, index) => (
                  <Cell 
                    key={`cell-${index}`}
                    fill={entry.isChosen ? '#3b82f6' : entry.confidence > 0.8 ? '#10b981' : '#6b7280'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      );
    } else {
      return (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-100 dark:bg-gray-900/50">
              <tr>
                <th className="px-3 py-2 text-left font-medium text-gray-700 dark:text-gray-300">Action</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700 dark:text-gray-300">Immediate</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700 dark:text-gray-300">Future</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700 dark:text-gray-300">Total</th>
                <th className="px-3 py-2 text-center font-medium text-gray-700 dark:text-gray-300">Confidence</th>
                <th className="px-3 py-2 text-center font-medium text-gray-700 dark:text-gray-300">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {chartData.map((alt, index) => (
                <tr 
                  key={index}
                  className={alt.isChosen ? 'bg-blue-50 dark:bg-blue-900/20 border-l-4 border-l-blue-500' : ''}
                >
                  <td className="px-3 py-2 font-medium dark:text-white">
                    {alt.name}
                    {alt.isChosen && (
                      <span className="ml-2 text-xs bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300 px-1.5 py-0.5 rounded">
                        CHOSEN
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span className={alt.immediateReward >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}>
                      {(alt.immediateReward ?? 0).toFixed(2)}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span className={alt.futureValue >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}>
                      {(alt.futureValue ?? 0).toFixed(2)}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right font-medium">
                    <span className={alt.totalReward >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}>
                      {(alt.totalReward ?? 0).toFixed(2)}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-center">
                    <span className={`px-2 py-1 rounded-full text-xs ${
                      alt.confidence >= 0.9 ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400' :
                      alt.confidence >= 0.7 ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400' :
                      'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
                    }`}>
                      {((alt.confidence ?? 0) * 100).toFixed(0)}%
                    </span>
                  </td>
                  <td className="px-3 py-2 text-center">
                    {alt.isChosen ? (
                      <span className="text-blue-600 dark:text-blue-400 font-medium">✓ Optimal</span>
                    ) : (
                      <span className="text-gray-500 dark:text-gray-400">Alternative</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
  };

const renderEconomicBreakdown = () => {
  if (!pattern.economicBreakdown) {
    return (
      <div className="text-center py-8 text-gray-500 dark:text-gray-400">
        <div className="space-y-2">
          <p>No economic breakdown available for this hour</p>
          <p className="text-xs">Pattern: {pattern.patternName || 'Unknown'}</p>
          <p className="text-xs">Hour: {pattern.hour}</p>
        </div>
      </div>
    );
  }

  const breakdown = pattern.economicBreakdown;
    const components = [
      { name: 'Grid Purchase Cost', value: breakdown.gridPurchaseCost ?? 0, type: 'cost' as const },
      { name: 'Grid Avoidance Benefit', value: breakdown.gridAvoidanceBenefit ?? 0, type: 'benefit' as const },
      { name: 'Battery Cost Basis', value: breakdown.batteryCostBasis ?? 0, type: 'cost' as const },
      { name: 'Battery Wear Cost', value: breakdown.batteryWearCost ?? 0, type: 'cost' as const },
      { name: 'Export Revenue', value: breakdown.exportRevenue ?? 0, type: 'benefit' as const },
    ];

    if (displayMode === 'chart') {
      // ...existing code for chart mode...
      // (leave as is)
    } else {
      // Table mode: match reference.txt style
      return (
        <div className="space-y-4">
          <table className="w-full text-base" style={{ fontFamily: 'inherit' }}>
            <thead className="bg-gray-100 dark:bg-gray-900/50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-gray-700 dark:text-gray-300">Component</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-700 dark:text-gray-300">Value</th>
              </tr>
            </thead>
            <tbody>
              {components.map((comp, index) => (
                <tr
                  key={index}
                  className={
                    comp.name.includes('Grid Purchase') ? 'bg-red-50 dark:bg-red-900/20' :
                    comp.name.includes('Avoidance') ? 'bg-green-50 dark:bg-green-900/20' :
                    comp.name.includes('Export') ? 'bg-purple-50 dark:bg-purple-900/20' :
                    comp.name.includes('Wear') ? 'bg-yellow-50 dark:bg-yellow-900/20' :
                    comp.name.includes('Battery Cost') ? 'bg-blue-50 dark:bg-blue-900/20' :
                    ''
                  }
                >
                  <td className="px-4 py-3 font-normal text-gray-900 dark:text-white">{comp.name}</td>
                  <td className={`px-4 py-3 text-right font-semibold ${
                    comp.value >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                  }`}>
                    {comp.value >= 0 ? '+' : ''}{comp.value.toFixed(2)} SEK
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2">
                <td className="px-4 py-3 font-bold text-gray-900 dark:text-white">Net Immediate Value</td>
                <td className={`px-4 py-3 text-right font-bold ${
                  breakdown.netImmediateValue >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                }`}>
                  {breakdown.netImmediateValue >= 0 ? '+' : ''}{(breakdown.netImmediateValue ?? 0).toFixed(2)} SEK
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      );
    }
  };

  const renderFutureTimeline = () => {
    if (!pattern.futureTimeline || pattern.futureTimeline.length === 0) {
      return (
        <div className="text-center py-8 text-gray-500 dark:text-gray-400">
          No future timeline available for this hour
        </div>
      );
    }

    const timeline = pattern.futureTimeline;

    if (displayMode === 'chart') {
      const chartData = timeline.map((item, index) => ({
        name: `${item.hour.toString().padStart(2, '0')}:00`,
        contribution: item.contribution,
        action: Math.abs(item.action),
        hour: item.hour,
        actionType: item.actionType,
        index,
      }));

      return (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis 
                dataKey="name" 
                tick={{ fontSize: 12, fill: 'currentColor' }}
              />
              <YAxis 
                tick={{ fontSize: 12, fill: 'currentColor' }}
                label={{ value: 'Contribution (SEK)', angle: -90, position: 'insideLeft' }}
              />
              <Tooltip 
                contentStyle={{ 
                  backgroundColor: 'var(--tw-bg-opacity, 1)', 
                  border: '1px solid #d1d5db',
                  borderRadius: '0.5rem'
                }}
                formatter={(value: number, name: string, props: any) => [
                  `${value.toFixed(2)} SEK`,
                  `${props.payload.actionType} Contribution`
                ]}
                labelFormatter={(label) => `Hour: ${label}`}
              />
              <Bar dataKey="contribution" fill="#8b5cf6">
                {chartData.map((entry, index) => (
                  <Cell 
                    key={`cell-${index}`}
                    fill="#8b5cf6"
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      );
    } else {
      return (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-100 dark:bg-gray-900/50">
              <tr>
                <th className="px-3 py-2 text-left font-medium text-gray-700 dark:text-gray-300">Hour</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 dark:text-gray-300">Action Type</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700 dark:text-gray-300">Planned Action</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700 dark:text-gray-300">Contribution</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {timeline.map((item, index) => (
                <tr key={index}>
                  <td className="px-3 py-2 font-medium dark:text-white">
                    {item.hour.toString().padStart(2, '0')}:00
                  </td>
                  <td className="px-3 py-2 dark:text-gray-300">
                    <span className="px-2 py-1 rounded text-xs bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300">
                      {item.actionType}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right dark:text-gray-300">
                    {Math.abs(item.action).toFixed(1)} kWh
                    <span className="ml-1 text-xs text-gray-500">
                      {(item.action ?? 0) > 0 ? '↑' : (item.action ?? 0) < 0 ? '↓' : '—'}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right font-medium">
                    <span className="text-green-600 dark:text-green-400">
                      +{(item.contribution ?? 0).toFixed(2)} SEK
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
  };

  const renderContent = () => {
    switch (view) {
      case 'landscape':
        return renderDecisionLandscape();
      case 'economic':
        return renderEconomicBreakdown();
      case 'future':
        return renderFutureTimeline();
      default:
        return null;
    }
  };

  const getViewTitle = () => {
    switch (view) {
      case 'landscape':
        return 'Decision Landscape - Alternative Actions Evaluated';
      case 'economic':
        return 'Economic Impact Breakdown - Cost & Benefit Analysis';
      case 'future':
        return 'Future Value Timeline - When Value is Realized';
      default:
        return '';
    }
  };

  return (
    <div className={className}>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-medium text-gray-900 dark:text-white">
          {getViewTitle()}
        </h3>
        {renderModeToggle()}
      </div>
      
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
        {renderContent()}
      </div>
    </div>
  );
};

export default DecisionAnalysisPanel;