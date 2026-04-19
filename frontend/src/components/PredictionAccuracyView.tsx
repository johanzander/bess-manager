import React, { useState, useMemo } from 'react';
import { usePredictionSnapshots, useSnapshotComparison } from '../hooks/usePredictionAnalysis';
import { AlertCircle, TrendingUp, ChevronDown } from 'lucide-react';
import ForecastAccuracyCards from './ForecastAccuracyCards';
import ForecastComparisonCharts from './ForecastComparisonCharts';
import SavingsImpactChart from './SavingsImpactChart';

const PredictionAccuracyView: React.FC = () => {
  const { snapshots, loading, error } = usePredictionSnapshots();
  const [selectedPeriod, setSelectedPeriod] = useState<number | null>(null);

  // Auto-select the first (earliest) snapshot when data loads
  useMemo(() => {
    if (snapshots.length > 0 && selectedPeriod === null) {
      setSelectedPeriod(snapshots[0].optimizationPeriod);
    }
  }, [snapshots, selectedPeriod]);

  const { comparison, loading: comparisonLoading, error: comparisonError } =
    useSnapshotComparison(selectedPeriod);

  // Helper function to format period as time string
  const formatPeriodTime = (period: number): string => {
    const hour = Math.floor(period / 4);
    const minute = (period % 4) * 15;
    return `${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`;
  };

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

  return (
    <div className="space-y-6">
      {/* Snapshot Selector */}
      <div className="bg-white dark:bg-gray-800 p-4 rounded-lg shadow border border-gray-200 dark:border-gray-700">
        <div className="flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="flex-1">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Evaluate prediction from
            </label>
            <div className="relative max-w-sm">
              <select
                value={selectedPeriod ?? ''}
                onChange={(e) => setSelectedPeriod(Number(e.target.value))}
                className="w-full px-4 py-2 pr-10 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:ring-2 focus:ring-purple-500 focus:border-purple-500 appearance-none"
              >
                {snapshots.map((snapshot) => (
                  <option key={snapshot.optimizationPeriod} value={snapshot.optimizationPeriod}>
                    {formatPeriodTime(snapshot.optimizationPeriod)} ({new Date(snapshot.snapshotTimestamp).toLocaleTimeString('sv-SE')})
                    {' '}- Predicted savings: {snapshot.predictedDailySavings.text}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400 pointer-events-none" />
            </div>
          </div>
          <div className="text-sm text-gray-500 dark:text-gray-400 max-w-md">
            Comparing the prediction made at{' '}
            <span className="font-medium text-gray-700 dark:text-gray-200">
              {selectedPeriod !== null ? formatPeriodTime(selectedPeriod) : '...'}
            </span>{' '}
            against what actually happened so far today.
          </div>
        </div>
      </div>

      {/* Loading / Error states for comparison */}
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

      {/* Results */}
      {comparison && !comparisonLoading && (
        <>
          {comparison.periodDeviations.length === 0 ? (
            <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-lg p-6">
              <p className="text-blue-800 dark:text-blue-200">
                No actual data available yet for comparison. Results will appear as the day progresses.
              </p>
            </div>
          ) : (
            <>
              {/* Section 1: KPI Cards */}
              <ForecastAccuracyCards comparison={comparison} />

              {/* Section 2: Predicted vs Actual Charts */}
              <ForecastComparisonCharts comparison={comparison} />

              {/* Section 3: Savings Impact */}
              <SavingsImpactChart comparison={comparison} />
            </>
          )}
        </>
      )}
    </div>
  );
};

export default PredictionAccuracyView;
