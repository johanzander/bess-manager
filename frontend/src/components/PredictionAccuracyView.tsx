import React, { useState, useEffect } from 'react';
import { usePredictionSnapshots, useSnapshotComparison } from '../hooks/usePredictionAnalysis';
import { AlertCircle, TrendingUp, ChevronDown } from 'lucide-react';
import ForecastAccuracyCards from './ForecastAccuracyCards';
import ForecastComparisonCharts from './ForecastComparisonCharts';
import SavingsImpactChart from './SavingsImpactChart';

const PredictionAccuracyView: React.FC = () => {
  const { snapshots, loading, error } = usePredictionSnapshots();
  const [selectedPeriod, setSelectedPeriod] = useState<number | null>(null);

  // Auto-select the first (earliest) snapshot when data loads
  useEffect(() => {
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
      {/* Page Header with Snapshot Selector */}
      <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow border border-gray-200 dark:border-gray-700">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
          <div className="mb-4 sm:mb-0">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Forecast Accuracy</h1>
            <p className="text-gray-600 dark:text-gray-300">
              Comparing prediction from{' '}
              <span className="font-medium text-gray-900 dark:text-white">
                {selectedPeriod !== null ? formatPeriodTime(selectedPeriod) : '...'}
              </span>{' '}
              against actual outcomes.
            </p>
          </div>
          <div className="relative">
            <select
              value={selectedPeriod ?? ''}
              onChange={(e) => setSelectedPeriod(Number(e.target.value))}
              className="px-4 py-2 pr-10 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-purple-500 focus:border-purple-500 appearance-none"
            >
              {snapshots.map((snapshot) => (
                <option key={snapshot.optimizationPeriod} value={snapshot.optimizationPeriod}>
                  {formatPeriodTime(snapshot.optimizationPeriod)} — {snapshot.totalExpectedSavings.text}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
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
              {/* Forecast Accuracy cards + Schedule Deviation cards + Savings Comparison */}
              <ForecastAccuracyCards comparison={comparison} />

              {/* Forecast Accuracy charts (solar, consumption) + Schedule Deviation charts (battery, grid) */}
              <ForecastComparisonCharts comparison={comparison} />

              {/* Hourly deviation bar chart */}
              <SavingsImpactChart comparison={comparison} />
            </>
          )}
        </>
      )}
    </div>
  );
};

export default PredictionAccuracyView;
