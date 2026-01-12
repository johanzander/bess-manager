// frontend/src/components/PredictionAnalysisView.tsx

import React, { useState, useMemo } from 'react';
import { usePredictionSnapshots, useSnapshotToSnapshotComparison } from '../hooks/usePredictionAnalysis';
import { AlertCircle, TrendingUp, ChevronDown } from 'lucide-react';
import { FormattedValue } from '../types';

// Type for Growatt TOU schedule intervals
interface GrowattInterval {
  startTime: string;
  endTime: string;
  enabled: boolean;
  battMode: string;
  power: number;
  acChargeEnabled?: boolean;
}

const PredictionAnalysisView: React.FC = () => {
  const { snapshots, loading, error } = usePredictionSnapshots();
  const [selectedPeriodA, setSelectedPeriodA] = useState<number | null>(null);
  const [selectedPeriodB, setSelectedPeriodB] = useState<number | null>(null);

  // Automatically select first and last snapshots when data loads
  useMemo(() => {
    if (snapshots.length > 0 && selectedPeriodA === null && selectedPeriodB === null) {
      setSelectedPeriodA(snapshots[0].optimizationPeriod);
      setSelectedPeriodB(snapshots[snapshots.length - 1].optimizationPeriod);
    }
  }, [snapshots, selectedPeriodA, selectedPeriodB]);

  const { comparison, loading: comparisonLoading, error: comparisonError } =
    useSnapshotToSnapshotComparison(selectedPeriodA, selectedPeriodB);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12">
        <div className="text-gray-600 dark:text-gray-300">Loading prediction snapshots...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded-lg p-6">
        <div className="flex items-center">
          <AlertCircle className="h-5 w-5 text-red-600 dark:text-red-400 mr-2" />
          <p className="text-red-800 dark:text-red-200">{error}</p>
        </div>
      </div>
    );
  }

  if (snapshots.length === 0) {
    return (
      <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-lg p-6">
        <div className="flex items-center">
          <TrendingUp className="h-5 w-5 text-blue-600 dark:text-blue-400 mr-2" />
          <p className="text-blue-800 dark:text-blue-200">
            No prediction snapshots available yet. Snapshots are captured every 15 minutes during optimization.
          </p>
        </div>
      </div>
    );
  }

  // Helper function to format period as time string
  const formatPeriodTime = (period: number): string => {
    const hour = Math.floor(period / 4);
    const minute = (period % 4) * 15;
    return `${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`;
  };

  // Helper function to render a formatted value with color coding for deltas
  const renderValue = (value: FormattedValue, isDelta: boolean = false): React.JSX.Element => {
    if (!isDelta) {
      return <span>{value.display}</span>;
    }

    // Color code deltas
    const numValue = value.value;
    const colorClass = numValue > 0.05
      ? 'text-green-600 dark:text-green-400 font-medium'
      : numValue < -0.05
      ? 'text-red-600 dark:text-red-400 font-medium'
      : 'text-gray-600 dark:text-gray-400';

    return <span className={colorClass}>{value.display}</span>;
  };

  return (
    <div className="space-y-6">
      {/* Header with Snapshot Selectors */}
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow border border-gray-200 dark:border-gray-700">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
          Compare Prediction Snapshots
        </h2>
        <p className="text-gray-600 dark:text-gray-300 mb-6">
          Select two snapshots to compare how predictions evolved throughout the day.
          View period-by-period differences in solar, consumption, battery action, and more.
        </p>

        {/* Snapshot Selectors */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Snapshot A Selector */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Snapshot A (Earlier Prediction)
            </label>
            <div className="relative">
              <select
                value={selectedPeriodA ?? ''}
                onChange={(e) => setSelectedPeriodA(Number(e.target.value))}
                className="w-full px-4 py-2 pr-10 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 appearance-none"
              >
                <option value="">Select snapshot...</option>
                {snapshots.map((snapshot) => (
                  <option key={snapshot.optimizationPeriod} value={snapshot.optimizationPeriod}>
                    {formatPeriodTime(snapshot.optimizationPeriod)} - Period {snapshot.optimizationPeriod}
                    ({new Date(snapshot.snapshotTimestamp).toLocaleTimeString('sv-SE')})
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400 pointer-events-none" />
            </div>
            {selectedPeriodA !== null && (
              <div className="mt-2 text-sm text-gray-600 dark:text-gray-400">
                Predicted savings: {snapshots.find(s => s.optimizationPeriod === selectedPeriodA)?.predictedDailySavings.text}
              </div>
            )}
          </div>

          {/* Snapshot B Selector */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Snapshot B (Later Prediction)
            </label>
            <div className="relative">
              <select
                value={selectedPeriodB ?? ''}
                onChange={(e) => setSelectedPeriodB(Number(e.target.value))}
                className="w-full px-4 py-2 pr-10 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 appearance-none"
              >
                <option value="">Select snapshot...</option>
                {snapshots.map((snapshot) => (
                  <option key={snapshot.optimizationPeriod} value={snapshot.optimizationPeriod}>
                    {formatPeriodTime(snapshot.optimizationPeriod)} - Period {snapshot.optimizationPeriod}
                    ({new Date(snapshot.snapshotTimestamp).toLocaleTimeString('sv-SE')})
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400 pointer-events-none" />
            </div>
            {selectedPeriodB !== null && (
              <div className="mt-2 text-sm text-gray-600 dark:text-gray-400">
                Predicted savings: {snapshots.find(s => s.optimizationPeriod === selectedPeriodB)?.predictedDailySavings.text}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Comparison Results */}
      {comparisonLoading && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-12">
          <div className="text-center text-gray-600 dark:text-gray-300">Loading comparison...</div>
        </div>
      )}

      {comparisonError && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded-lg p-6">
          <div className="flex items-center">
            <AlertCircle className="h-5 w-5 text-red-600 dark:text-red-400 mr-2" />
            <p className="text-red-800 dark:text-red-200">{comparisonError}</p>
          </div>
        </div>
      )}

      {comparison && selectedPeriodA !== null && selectedPeriodB !== null && !comparisonLoading && (() => {
        // Calculate totals
        const totals = comparison.periodComparisons.reduce((acc, periodComp) => {
          return {
            snapshotA: {
              solar: acc.snapshotA.solar + periodComp.snapshotA.solar.value,
              consumption: acc.snapshotA.consumption + periodComp.snapshotA.consumption.value,
              batteryAction: acc.snapshotA.batteryAction + periodComp.snapshotA.batteryAction.value,
              gridImport: acc.snapshotA.gridImport + periodComp.snapshotA.gridImport.value,
              gridExport: acc.snapshotA.gridExport + periodComp.snapshotA.gridExport.value,
              cost: acc.snapshotA.cost + periodComp.snapshotA.cost.value,
              gridOnlyCost: acc.snapshotA.gridOnlyCost + periodComp.snapshotA.gridOnlyCost.value,
              savings: acc.snapshotA.savings + periodComp.snapshotA.savings.value,
            },
            snapshotB: {
              solar: acc.snapshotB.solar + periodComp.snapshotB.solar.value,
              consumption: acc.snapshotB.consumption + periodComp.snapshotB.consumption.value,
              batteryAction: acc.snapshotB.batteryAction + periodComp.snapshotB.batteryAction.value,
              gridImport: acc.snapshotB.gridImport + periodComp.snapshotB.gridImport.value,
              gridExport: acc.snapshotB.gridExport + periodComp.snapshotB.gridExport.value,
              cost: acc.snapshotB.cost + periodComp.snapshotB.cost.value,
              gridOnlyCost: acc.snapshotB.gridOnlyCost + periodComp.snapshotB.gridOnlyCost.value,
              savings: acc.snapshotB.savings + periodComp.snapshotB.savings.value,
            },
            delta: {
              solar: acc.delta.solar + periodComp.delta.solar.value,
              consumption: acc.delta.consumption + periodComp.delta.consumption.value,
              batteryAction: acc.delta.batteryAction + periodComp.delta.batteryAction.value,
              gridImport: acc.delta.gridImport + periodComp.delta.gridImport.value,
              gridExport: acc.delta.gridExport + periodComp.delta.gridExport.value,
              cost: acc.delta.cost + periodComp.delta.cost.value,
              gridOnlyCost: acc.delta.gridOnlyCost + periodComp.delta.gridOnlyCost.value,
              savings: acc.delta.savings + periodComp.delta.savings.value,
            },
          };
        }, {
          snapshotA: { solar: 0, consumption: 0, batteryAction: 0, gridImport: 0, gridExport: 0, cost: 0, gridOnlyCost: 0, savings: 0 },
          snapshotB: { solar: 0, consumption: 0, batteryAction: 0, gridImport: 0, gridExport: 0, cost: 0, gridOnlyCost: 0, savings: 0 },
          delta: { solar: 0, consumption: 0, batteryAction: 0, gridImport: 0, gridExport: 0, cost: 0, gridOnlyCost: 0, savings: 0 },
        });

        // Get final SOE values (last period)
        const lastPeriod = comparison.periodComparisons[comparison.periodComparisons.length - 1];
        const currency = lastPeriod?.snapshotA.cost.unit || 'SEK';

        return (
        <div className="space-y-6">
          {/* Comparison Header with Key Metrics */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              Comparing {formatPeriodTime(selectedPeriodA)} vs {formatPeriodTime(selectedPeriodB)}
            </h3>
            <div className="grid grid-cols-2 gap-4 text-sm mb-6">
              <div>
                <span className="text-gray-600 dark:text-gray-400">Snapshot A:</span>
                <span className="ml-2 font-medium text-gray-900 dark:text-white">
                  {new Date(comparison.snapshotATimestamp).toLocaleString('sv-SE')}
                </span>
              </div>
              <div>
                <span className="text-gray-600 dark:text-gray-400">Snapshot B:</span>
                <span className="ml-2 font-medium text-gray-900 dark:text-white">
                  {new Date(comparison.snapshotBTimestamp).toLocaleString('sv-SE')}
                </span>
              </div>
            </div>

            {/* Key Metrics Summary */}
            <div className="border-t border-gray-200 dark:border-gray-700 pt-4">
              <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Daily Cost Summary</h4>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {/* Snapshot A Metrics */}
                <div className="bg-blue-50 dark:bg-blue-900/20 p-4 rounded-lg">
                  <div className="text-xs font-medium text-blue-700 dark:text-blue-300 mb-3">
                    Snapshot A ({formatPeriodTime(selectedPeriodA)})
                  </div>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-gray-600 dark:text-gray-400">Grid Only:</span>
                      <span className="font-semibold text-gray-900 dark:text-white">
                        {totals.snapshotA.gridOnlyCost.toFixed(2)} {currency}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-600 dark:text-gray-400">Optimized:</span>
                      <span className="font-semibold text-gray-900 dark:text-white">
                        {totals.snapshotA.cost.toFixed(2)} {currency}
                      </span>
                    </div>
                    <div className="flex justify-between border-t border-blue-200 dark:border-blue-700 pt-2">
                      <span className="text-blue-700 dark:text-blue-300 font-medium">Savings:</span>
                      <span className="font-bold text-blue-700 dark:text-blue-300">
                        {(totals.snapshotA.gridOnlyCost - totals.snapshotA.cost).toFixed(2)} {currency}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Snapshot B Metrics */}
                <div className="bg-green-50 dark:bg-green-900/20 p-4 rounded-lg">
                  <div className="text-xs font-medium text-green-700 dark:text-green-300 mb-3">
                    Snapshot B ({formatPeriodTime(selectedPeriodB)})
                  </div>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-gray-600 dark:text-gray-400">Grid Only:</span>
                      <span className="font-semibold text-gray-900 dark:text-white">
                        {totals.snapshotB.gridOnlyCost.toFixed(2)} {currency}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-600 dark:text-gray-400">Optimized:</span>
                      <span className="font-semibold text-gray-900 dark:text-white">
                        {totals.snapshotB.cost.toFixed(2)} {currency}
                      </span>
                    </div>
                    <div className="flex justify-between border-t border-green-200 dark:border-green-700 pt-2">
                      <span className="text-green-700 dark:text-green-300 font-medium">Savings:</span>
                      <span className="font-bold text-green-700 dark:text-green-300">
                        {(totals.snapshotB.gridOnlyCost - totals.snapshotB.cost).toFixed(2)} {currency}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Delta Metrics */}
                <div className={`p-4 rounded-lg ${
                  (totals.snapshotB.gridOnlyCost - totals.snapshotB.cost) - (totals.snapshotA.gridOnlyCost - totals.snapshotA.cost) >= 0
                    ? 'bg-purple-50 dark:bg-purple-900/20'
                    : 'bg-red-50 dark:bg-red-900/20'
                }`}>
                  <div className={`text-xs font-medium mb-3 ${
                    (totals.snapshotB.gridOnlyCost - totals.snapshotB.cost) - (totals.snapshotA.gridOnlyCost - totals.snapshotA.cost) >= 0
                      ? 'text-purple-700 dark:text-purple-300'
                      : 'text-red-700 dark:text-red-300'
                  }`}>
                    Change (B - A)
                  </div>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-gray-600 dark:text-gray-400">Grid Only:</span>
                      <span className={`font-semibold ${
                        totals.delta.gridOnlyCost > 0.05 ? 'text-green-600 dark:text-green-400' :
                        totals.delta.gridOnlyCost < -0.05 ? 'text-red-600 dark:text-red-400' :
                        'text-gray-900 dark:text-white'
                      }`}>
                        {totals.delta.gridOnlyCost >= 0 ? '+' : ''}{totals.delta.gridOnlyCost.toFixed(2)} {currency}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-600 dark:text-gray-400">Optimized:</span>
                      <span className={`font-semibold ${
                        totals.delta.cost > 0.05 ? 'text-green-600 dark:text-green-400' :
                        totals.delta.cost < -0.05 ? 'text-red-600 dark:text-red-400' :
                        'text-gray-900 dark:text-white'
                      }`}>
                        {totals.delta.cost >= 0 ? '+' : ''}{totals.delta.cost.toFixed(2)} {currency}
                      </span>
                    </div>
                    <div className={`flex justify-between border-t pt-2 ${
                      (totals.snapshotB.gridOnlyCost - totals.snapshotB.cost) - (totals.snapshotA.gridOnlyCost - totals.snapshotA.cost) >= 0
                        ? 'border-purple-200 dark:border-purple-700'
                        : 'border-red-200 dark:border-red-700'
                    }`}>
                      <span className={`font-medium ${
                        (totals.snapshotB.gridOnlyCost - totals.snapshotB.cost) - (totals.snapshotA.gridOnlyCost - totals.snapshotA.cost) >= 0
                          ? 'text-purple-700 dark:text-purple-300'
                          : 'text-red-700 dark:text-red-300'
                      }`}>
                        Savings:
                      </span>
                      <span className={`font-bold ${
                        (totals.snapshotB.gridOnlyCost - totals.snapshotB.cost) - (totals.snapshotA.gridOnlyCost - totals.snapshotA.cost) >= 0
                          ? 'text-purple-700 dark:text-purple-300'
                          : 'text-red-700 dark:text-red-300'
                      }`}>
                        {((totals.snapshotB.gridOnlyCost - totals.snapshotB.cost) - (totals.snapshotA.gridOnlyCost - totals.snapshotA.cost)) >= 0 ? '+' : ''}
                        {((totals.snapshotB.gridOnlyCost - totals.snapshotB.cost) - (totals.snapshotA.gridOnlyCost - totals.snapshotA.cost)).toFixed(2)} {currency}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Period-by-Period Comparison Table */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="p-6 border-b border-gray-200 dark:border-gray-700">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                All 96 Periods Comparison
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                Comparing predictions and actuals across all 15-minute intervals
              </p>
            </div>

            <div className="overflow-x-auto">
              <table className="min-w-full text-xs">
                <thead className="bg-gray-50 dark:bg-gray-700/50 sticky top-0">
                  <tr>
                    {/* Period Info */}
                    <th rowSpan={2} className="px-3 py-2 text-left font-semibold text-gray-700 dark:text-gray-300 border-r border-gray-300 dark:border-gray-600">
                      Period
                    </th>
                    <th rowSpan={2} className="px-3 py-2 text-left font-semibold text-gray-700 dark:text-gray-300 border-r-2 border-gray-400 dark:border-gray-500">
                      Time
                    </th>

                    {/* Snapshot A */}
                    <th colSpan={8} className="px-3 py-1 text-center font-semibold text-blue-700 dark:text-blue-300 border-r-2 border-gray-400 dark:border-gray-500">
                      Snapshot A ({formatPeriodTime(selectedPeriodA)})
                    </th>

                    {/* Snapshot B */}
                    <th colSpan={8} className="px-3 py-1 text-center font-semibold text-green-700 dark:text-green-300 border-r-2 border-gray-400 dark:border-gray-500">
                      Snapshot B ({formatPeriodTime(selectedPeriodB)})
                    </th>

                    {/* Delta */}
                    <th colSpan={8} className="px-3 py-1 text-center font-semibold text-purple-700 dark:text-purple-300">
                      Difference (B - A)
                    </th>
                  </tr>
                  <tr className="border-t border-gray-300 dark:border-gray-600">
                    {/* Snapshot A columns */}
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">Solar</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">Cons</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">Batt</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">SOE</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">Import</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">Export</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">Cost</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400 border-r-2 border-gray-400 dark:border-gray-500">Savings</th>

                    {/* Snapshot B columns */}
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">Solar</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">Cons</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">Batt</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">SOE</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">Import</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">Export</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">Cost</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400 border-r-2 border-gray-400 dark:border-gray-500">Savings</th>

                    {/* Delta columns */}
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">ΔSolar</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">ΔCons</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">ΔBatt</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">ΔSOE</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">ΔImport</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">ΔExport</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">ΔCost</th>
                    <th className="px-2 py-1 text-right text-gray-600 dark:text-gray-400">ΔSavings</th>
                  </tr>
                </thead>
                <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                  {comparison.periodComparisons.map((periodComp) => (
                    <tr key={periodComp.period} className="hover:bg-gray-50 dark:hover:bg-gray-700/30">
                      {/* Period Info */}
                      <td className="px-3 py-2 font-medium text-gray-900 dark:text-white border-r border-gray-300 dark:border-gray-600">
                        {periodComp.period}
                      </td>
                      <td className="px-3 py-2 text-gray-600 dark:text-gray-400 border-r-2 border-gray-400 dark:border-gray-500">
                        {formatPeriodTime(periodComp.period)}
                      </td>

                      {/* Snapshot A Data */}
                      <td className="px-2 py-2 text-right text-blue-600 dark:text-blue-400">
                        {renderValue(periodComp.snapshotA.solar)}
                      </td>
                      <td className="px-2 py-2 text-right text-blue-600 dark:text-blue-400">
                        {renderValue(periodComp.snapshotA.consumption)}
                      </td>
                      <td className="px-2 py-2 text-right text-blue-600 dark:text-blue-400">
                        {renderValue(periodComp.snapshotA.batteryAction)}
                      </td>
                      <td className="px-2 py-2 text-right text-blue-600 dark:text-blue-400">
                        {renderValue(periodComp.snapshotA.batterySoe)}
                      </td>
                      <td className="px-2 py-2 text-right text-blue-600 dark:text-blue-400">
                        {renderValue(periodComp.snapshotA.gridImport)}
                      </td>
                      <td className="px-2 py-2 text-right text-blue-600 dark:text-blue-400">
                        {renderValue(periodComp.snapshotA.gridExport)}
                      </td>
                      <td className="px-2 py-2 text-right text-blue-600 dark:text-blue-400">
                        {renderValue(periodComp.snapshotA.cost)}
                      </td>
                      <td className="px-2 py-2 text-right text-blue-600 dark:text-blue-400 border-r-2 border-gray-400 dark:border-gray-500">
                        {renderValue(periodComp.snapshotA.savings)}
                      </td>

                      {/* Snapshot B Data */}
                      <td className="px-2 py-2 text-right text-green-600 dark:text-green-400">
                        {renderValue(periodComp.snapshotB.solar)}
                      </td>
                      <td className="px-2 py-2 text-right text-green-600 dark:text-green-400">
                        {renderValue(periodComp.snapshotB.consumption)}
                      </td>
                      <td className="px-2 py-2 text-right text-green-600 dark:text-green-400">
                        {renderValue(periodComp.snapshotB.batteryAction)}
                      </td>
                      <td className="px-2 py-2 text-right text-green-600 dark:text-green-400">
                        {renderValue(periodComp.snapshotB.batterySoe)}
                      </td>
                      <td className="px-2 py-2 text-right text-green-600 dark:text-green-400">
                        {renderValue(periodComp.snapshotB.gridImport)}
                      </td>
                      <td className="px-2 py-2 text-right text-green-600 dark:text-green-400">
                        {renderValue(periodComp.snapshotB.gridExport)}
                      </td>
                      <td className="px-2 py-2 text-right text-green-600 dark:text-green-400">
                        {renderValue(periodComp.snapshotB.cost)}
                      </td>
                      <td className="px-2 py-2 text-right text-green-600 dark:text-green-400 border-r-2 border-gray-400 dark:border-gray-500">
                        {renderValue(periodComp.snapshotB.savings)}
                      </td>

                      {/* Delta Data */}
                      <td className="px-2 py-2 text-right">{renderValue(periodComp.delta.solar, true)}</td>
                      <td className="px-2 py-2 text-right">{renderValue(periodComp.delta.consumption, true)}</td>
                      <td className="px-2 py-2 text-right">{renderValue(periodComp.delta.batteryAction, true)}</td>
                      <td className="px-2 py-2 text-right">{renderValue(periodComp.delta.batterySoe, true)}</td>
                      <td className="px-2 py-2 text-right">{renderValue(periodComp.delta.gridImport, true)}</td>
                      <td className="px-2 py-2 text-right">{renderValue(periodComp.delta.gridExport, true)}</td>
                      <td className="px-2 py-2 text-right">{renderValue(periodComp.delta.cost, true)}</td>
                      <td className="px-2 py-2 text-right">{renderValue(periodComp.delta.savings, true)}</td>
                    </tr>
                  ))}

                  {/* Totals Row */}
                  <tr className="bg-gray-100 dark:bg-gray-700 font-bold border-t-2 border-gray-400 dark:border-gray-500">
                    <td colSpan={2} className="px-3 py-3 text-left text-gray-900 dark:text-white border-r-2 border-gray-400 dark:border-gray-500">
                      TOTALS
                    </td>

                    {/* Snapshot A Totals */}
                    <td className="px-2 py-3 text-right text-blue-700 dark:text-blue-300">
                      {totals.snapshotA.solar.toFixed(2)} kWh
                    </td>
                    <td className="px-2 py-3 text-right text-blue-700 dark:text-blue-300">
                      {totals.snapshotA.consumption.toFixed(2)} kWh
                    </td>
                    <td className="px-2 py-3 text-right text-blue-700 dark:text-blue-300">
                      {totals.snapshotA.batteryAction.toFixed(2)} kWh
                    </td>
                    <td className="px-2 py-3 text-right text-blue-700 dark:text-blue-300 text-xs">
                      {lastPeriod?.snapshotA.batterySoe.display} (final)
                    </td>
                    <td className="px-2 py-3 text-right text-blue-700 dark:text-blue-300">
                      {totals.snapshotA.gridImport.toFixed(2)} kWh
                    </td>
                    <td className="px-2 py-3 text-right text-blue-700 dark:text-blue-300">
                      {totals.snapshotA.gridExport.toFixed(2)} kWh
                    </td>
                    <td className="px-2 py-3 text-right text-blue-700 dark:text-blue-300">
                      {totals.snapshotA.cost.toFixed(2)} {currency}
                    </td>
                    <td className="px-2 py-3 text-right text-blue-700 dark:text-blue-300 border-r-2 border-gray-400 dark:border-gray-500">
                      {totals.snapshotA.savings.toFixed(2)} {currency}
                    </td>

                    {/* Snapshot B Totals */}
                    <td className="px-2 py-3 text-right text-green-700 dark:text-green-300">
                      {totals.snapshotB.solar.toFixed(2)} kWh
                    </td>
                    <td className="px-2 py-3 text-right text-green-700 dark:text-green-300">
                      {totals.snapshotB.consumption.toFixed(2)} kWh
                    </td>
                    <td className="px-2 py-3 text-right text-green-700 dark:text-green-300">
                      {totals.snapshotB.batteryAction.toFixed(2)} kWh
                    </td>
                    <td className="px-2 py-3 text-right text-green-700 dark:text-green-300 text-xs">
                      {lastPeriod?.snapshotB.batterySoe.display} (final)
                    </td>
                    <td className="px-2 py-3 text-right text-green-700 dark:text-green-300">
                      {totals.snapshotB.gridImport.toFixed(2)} kWh
                    </td>
                    <td className="px-2 py-3 text-right text-green-700 dark:text-green-300">
                      {totals.snapshotB.gridExport.toFixed(2)} kWh
                    </td>
                    <td className="px-2 py-3 text-right text-green-700 dark:text-green-300">
                      {totals.snapshotB.cost.toFixed(2)} {currency}
                    </td>
                    <td className="px-2 py-3 text-right text-green-700 dark:text-green-300 border-r-2 border-gray-400 dark:border-gray-500">
                      {totals.snapshotB.savings.toFixed(2)} {currency}
                    </td>

                    {/* Delta Totals */}
                    <td className={`px-2 py-3 text-right font-bold ${
                      totals.delta.solar > 0.05 ? 'text-green-700 dark:text-green-300' :
                      totals.delta.solar < -0.05 ? 'text-red-700 dark:text-red-300' :
                      'text-gray-700 dark:text-gray-300'
                    }`}>
                      {totals.delta.solar >= 0 ? '+' : ''}{totals.delta.solar.toFixed(2)} kWh
                    </td>
                    <td className={`px-2 py-3 text-right font-bold ${
                      totals.delta.consumption > 0.05 ? 'text-green-700 dark:text-green-300' :
                      totals.delta.consumption < -0.05 ? 'text-red-700 dark:text-red-300' :
                      'text-gray-700 dark:text-gray-300'
                    }`}>
                      {totals.delta.consumption >= 0 ? '+' : ''}{totals.delta.consumption.toFixed(2)} kWh
                    </td>
                    <td className={`px-2 py-3 text-right font-bold ${
                      totals.delta.batteryAction > 0.05 ? 'text-green-700 dark:text-green-300' :
                      totals.delta.batteryAction < -0.05 ? 'text-red-700 dark:text-red-300' :
                      'text-gray-700 dark:text-gray-300'
                    }`}>
                      {totals.delta.batteryAction >= 0 ? '+' : ''}{totals.delta.batteryAction.toFixed(2)} kWh
                    </td>
                    <td className="px-2 py-3 text-right text-purple-700 dark:text-purple-300 text-xs">
                      {lastPeriod && (lastPeriod.snapshotB.batterySoe.value - lastPeriod.snapshotA.batterySoe.value).toFixed(2)} kWh
                    </td>
                    <td className={`px-2 py-3 text-right font-bold ${
                      totals.delta.gridImport > 0.05 ? 'text-green-700 dark:text-green-300' :
                      totals.delta.gridImport < -0.05 ? 'text-red-700 dark:text-red-300' :
                      'text-gray-700 dark:text-gray-300'
                    }`}>
                      {totals.delta.gridImport >= 0 ? '+' : ''}{totals.delta.gridImport.toFixed(2)} kWh
                    </td>
                    <td className={`px-2 py-3 text-right font-bold ${
                      totals.delta.gridExport > 0.05 ? 'text-green-700 dark:text-green-300' :
                      totals.delta.gridExport < -0.05 ? 'text-red-700 dark:text-red-300' :
                      'text-gray-700 dark:text-gray-300'
                    }`}>
                      {totals.delta.gridExport >= 0 ? '+' : ''}{totals.delta.gridExport.toFixed(2)} kWh
                    </td>
                    <td className={`px-2 py-3 text-right font-bold ${
                      totals.delta.cost > 0.05 ? 'text-green-700 dark:text-green-300' :
                      totals.delta.cost < -0.05 ? 'text-red-700 dark:text-red-300' :
                      'text-gray-700 dark:text-gray-300'
                    }`}>
                      {totals.delta.cost >= 0 ? '+' : ''}{totals.delta.cost.toFixed(2)} {currency}
                    </td>
                    <td className={`px-2 py-3 text-right font-bold ${
                      totals.delta.savings > 0.05 ? 'text-green-700 dark:text-green-300' :
                      totals.delta.savings < -0.05 ? 'text-red-700 dark:text-red-300' :
                      'text-gray-700 dark:text-gray-300'
                    }`}>
                      {totals.delta.savings >= 0 ? '+' : ''}{totals.delta.savings.toFixed(2)} {currency}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* Growatt Schedule Comparison */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="p-6 border-b border-gray-200 dark:border-gray-700">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Growatt TOU Schedule Comparison
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                Compare the battery charging/discharging schedules sent to the inverter
              </p>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 p-6">
              {/* Snapshot A Schedule */}
              <div>
                <h4 className="text-sm font-semibold text-blue-700 dark:text-blue-300 mb-3 flex items-center">
                  <span className="bg-blue-100 dark:bg-blue-900/30 px-2 py-1 rounded mr-2">A</span>
                  Snapshot A - {formatPeriodTime(selectedPeriodA)} ({new Date(comparison.snapshotATimestamp).toLocaleTimeString('sv-SE')})
                </h4>
                <div className="space-y-2">
                  {comparison.growattScheduleA && comparison.growattScheduleA.length > 0 ? (
                    comparison.growattScheduleA.map((interval: GrowattInterval, idx: number) => (
                      <div
                        key={idx}
                        className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-lg p-3"
                      >
                        <div className="flex justify-between items-start mb-2">
                          <div className="flex items-center space-x-2">
                            <span className="font-semibold text-gray-900 dark:text-white">
                              {interval.startTime} - {interval.endTime}
                            </span>
                            <span className={`text-xs px-2 py-1 rounded ${
                              interval.enabled
                                ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300'
                                : 'bg-gray-100 dark:bg-gray-900/30 text-gray-600 dark:text-gray-400'
                            }`}>
                              {interval.enabled ? 'Enabled' : 'Disabled'}
                            </span>
                          </div>
                        </div>
                        <div className="text-sm space-y-1">
                          <div className="flex justify-between">
                            <span className="text-gray-600 dark:text-gray-400">Mode:</span>
                            <span className="font-medium text-gray-900 dark:text-white">
                              {interval.battMode === 'battery_first' ? '⚡ Battery First' : '🏠 Load First'}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-gray-600 dark:text-gray-400">Power:</span>
                            <span className="font-medium text-gray-900 dark:text-white">
                              {interval.power}%
                            </span>
                          </div>
                          {interval.acChargeEnabled !== undefined && (
                            <div className="flex justify-between">
                              <span className="text-gray-600 dark:text-gray-400">AC Charge:</span>
                              <span className="font-medium text-gray-900 dark:text-white">
                                {interval.acChargeEnabled ? 'Yes' : 'No'}
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="text-center text-gray-500 dark:text-gray-400 py-8">
                      No schedule data available
                    </div>
                  )}
                </div>
              </div>

              {/* Snapshot B Schedule */}
              <div>
                <h4 className="text-sm font-semibold text-green-700 dark:text-green-300 mb-3 flex items-center">
                  <span className="bg-green-100 dark:bg-green-900/30 px-2 py-1 rounded mr-2">B</span>
                  Snapshot B - {formatPeriodTime(selectedPeriodB)} ({new Date(comparison.snapshotBTimestamp).toLocaleTimeString('sv-SE')})
                </h4>
                <div className="space-y-2">
                  {comparison.growattScheduleB && comparison.growattScheduleB.length > 0 ? (
                    comparison.growattScheduleB.map((interval: GrowattInterval, idx: number) => {
                      // Find matching interval in schedule A for comparison
                      const matchingA = comparison.growattScheduleA?.find(
                        (a: GrowattInterval) => a.startTime === interval.startTime && a.endTime === interval.endTime
                      );
                      const hasChanges = matchingA && (
                        matchingA.battMode !== interval.battMode ||
                        matchingA.power !== interval.power ||
                        matchingA.enabled !== interval.enabled ||
                        matchingA.acChargeEnabled !== interval.acChargeEnabled
                      );

                      return (
                        <div
                          key={idx}
                          className={`border rounded-lg p-3 ${
                            hasChanges
                              ? 'bg-yellow-50 dark:bg-yellow-900/20 border-yellow-300 dark:border-yellow-600'
                              : 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-700'
                          }`}
                        >
                          <div className="flex justify-between items-start mb-2">
                            <div className="flex items-center space-x-2">
                              <span className="font-semibold text-gray-900 dark:text-white">
                                {interval.startTime} - {interval.endTime}
                              </span>
                              <span className={`text-xs px-2 py-1 rounded ${
                                interval.enabled
                                  ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300'
                                  : 'bg-gray-100 dark:bg-gray-900/30 text-gray-600 dark:text-gray-400'
                              }`}>
                                {interval.enabled ? 'Enabled' : 'Disabled'}
                              </span>
                              {hasChanges && (
                                <span className="text-xs px-2 py-1 rounded bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300">
                                  Changed
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="text-sm space-y-1">
                            <div className="flex justify-between">
                              <span className="text-gray-600 dark:text-gray-400">Mode:</span>
                              <span className={`font-medium ${
                                matchingA && matchingA.battMode !== interval.battMode
                                  ? 'text-yellow-700 dark:text-yellow-300'
                                  : 'text-gray-900 dark:text-white'
                              }`}>
                                {interval.battMode === 'battery_first' ? '⚡ Battery First' : '🏠 Load First'}
                              </span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-gray-600 dark:text-gray-400">Power:</span>
                              <span className={`font-medium ${
                                matchingA && matchingA.power !== interval.power
                                  ? 'text-yellow-700 dark:text-yellow-300'
                                  : 'text-gray-900 dark:text-white'
                              }`}>
                                {interval.power}%
                              </span>
                            </div>
                            {interval.acChargeEnabled !== undefined && (
                              <div className="flex justify-between">
                                <span className="text-gray-600 dark:text-gray-400">AC Charge:</span>
                                <span className={`font-medium ${
                                  matchingA && matchingA.acChargeEnabled !== interval.acChargeEnabled
                                    ? 'text-yellow-700 dark:text-yellow-300'
                                    : 'text-gray-900 dark:text-white'
                                }`}>
                                  {interval.acChargeEnabled ? 'Yes' : 'No'}
                                </span>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })
                  ) : (
                    <div className="text-center text-gray-500 dark:text-gray-400 py-8">
                      No schedule data available
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
        );
      })()}
    </div>
  );
};

export default PredictionAnalysisView;
