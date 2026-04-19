import React from 'react';
import { Sun, Home, TrendingUp, AlertCircle } from 'lucide-react';
import { SnapshotComparison } from '../types';

interface ForecastAccuracyCardsProps {
  comparison: SnapshotComparison;
}

interface AccuracyStats {
  accuracy: number;
  totalPredicted: number;
  totalActual: number;
  unit: string;
}

const computeAccuracy = (
  comparison: SnapshotComparison,
  getPredicted: (d: typeof comparison.periodDeviations[0]) => number,
  getActual: (d: typeof comparison.periodDeviations[0]) => number,
): AccuracyStats => {
  let sumAbsError = 0;
  let totalPredicted = 0;
  let totalActual = 0;

  for (const dev of comparison.periodDeviations) {
    const predicted = getPredicted(dev);
    const actual = getActual(dev);
    totalPredicted += predicted;
    totalActual += actual;
    sumAbsError += Math.abs(actual - predicted);
  }

  // nMAE: total absolute error / total actual. Naturally ignores zero-production hours.
  const nMAE = totalActual > 0 ? sumAbsError / totalActual : 0;
  const accuracy = Math.max(0, Math.min(100, (1 - nMAE) * 100));

  const unit = comparison.periodDeviations[0]?.predictedSolar?.unit || 'kWh';
  return { accuracy, totalPredicted, totalActual, unit };
};

const getPrimaryCauseLabel = (cause: string): { label: string; description: string } => {
  switch (cause) {
    case 'consumption':
      return { label: 'Consumption', description: 'Consumption forecast was the main deviation driver' };
    case 'solar':
      return { label: 'Solar', description: 'Solar forecast was the main deviation driver' };
    case 'battery_control':
      return { label: 'Battery', description: 'Battery control diverged from plan' };
    case 'multiple':
      return { label: 'Multiple', description: 'Multiple factors contributed equally' };
    case 'none':
      return { label: 'On Track', description: 'Predictions closely match actuals' };
    default:
      return { label: cause, description: 'Unknown deviation cause' };
  }
};

const ForecastAccuracyCards: React.FC<ForecastAccuracyCardsProps> = ({ comparison }) => {
  const insufficientData = comparison.periodDeviations.length < 4;

  const solar = computeAccuracy(
    comparison,
    (d) => d.predictedSolar.value,
    (d) => d.actualSolar.value,
  );

  const consumption = computeAccuracy(
    comparison,
    (d) => d.predictedConsumption.value,
    (d) => d.actualConsumption.value,
  );

  const savingsActual = comparison.totalActualSavings;
  const savingsPredicted = comparison.totalPredictedSavings;
  const savingsDelta = comparison.savingsDeviation;

  const primaryCause = getPrimaryCauseLabel(comparison.primaryDeviationCause);

  const getAccuracyColor = (accuracy: number): string => {
    if (accuracy >= 90) return 'text-green-600 dark:text-green-400';
    if (accuracy >= 75) return 'text-yellow-600 dark:text-yellow-400';
    return 'text-red-600 dark:text-red-400';
  };

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {/* Solar Forecast Accuracy */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center mb-2">
          <Sun className="h-5 w-5 text-yellow-500 mr-2" />
          <span className="text-sm font-medium text-gray-600 dark:text-gray-400">Solar Accuracy</span>
        </div>
        {insufficientData ? (
          <div className="text-lg font-semibold text-gray-400 dark:text-gray-500">Insufficient data</div>
        ) : (
          <>
            <div className={`text-2xl font-bold ${getAccuracyColor(solar.accuracy)}`}>
              {solar.accuracy.toFixed(0)}%
            </div>
            <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              Predicted {solar.totalPredicted.toFixed(1)} {solar.unit}, actual {solar.totalActual.toFixed(1)} {solar.unit}
            </div>
          </>
        )}
      </div>

      {/* Consumption Forecast Accuracy */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center mb-2">
          <Home className="h-5 w-5 text-red-500 mr-2" />
          <span className="text-sm font-medium text-gray-600 dark:text-gray-400">Consumption Accuracy</span>
        </div>
        {insufficientData ? (
          <div className="text-lg font-semibold text-gray-400 dark:text-gray-500">Insufficient data</div>
        ) : (
          <>
            <div className={`text-2xl font-bold ${getAccuracyColor(consumption.accuracy)}`}>
              {consumption.accuracy.toFixed(0)}%
            </div>
            <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              Predicted {consumption.totalPredicted.toFixed(1)} {consumption.unit}, actual {consumption.totalActual.toFixed(1)} {consumption.unit}
            </div>
          </>
        )}
      </div>

      {/* Savings Result */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center mb-2">
          <TrendingUp className="h-5 w-5 text-green-500 mr-2" />
          <span className="text-sm font-medium text-gray-600 dark:text-gray-400">Savings Result</span>
        </div>
        {insufficientData ? (
          <div className="text-lg font-semibold text-gray-400 dark:text-gray-500">Insufficient data</div>
        ) : (
          <>
            <div className="text-2xl font-bold text-gray-900 dark:text-white">
              {savingsActual.text}
            </div>
            <div className={`text-xs mt-1 font-medium ${
              savingsDelta.value >= 0
                ? 'text-green-600 dark:text-green-400'
                : 'text-red-600 dark:text-red-400'
            }`}>
              {savingsDelta.value >= 0 ? '+' : ''}{savingsDelta.display} {savingsDelta.unit} vs predicted ({savingsPredicted.text})
            </div>
          </>
        )}
      </div>

      {/* Primary Deviation Cause */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center mb-2">
          <AlertCircle className="h-5 w-5 text-purple-500 mr-2" />
          <span className="text-sm font-medium text-gray-600 dark:text-gray-400">Main Deviation</span>
        </div>
        {insufficientData ? (
          <div className="text-lg font-semibold text-gray-400 dark:text-gray-500">Insufficient data</div>
        ) : (
          <>
            <div className="text-2xl font-bold text-purple-600 dark:text-purple-400">
              {primaryCause.label}
            </div>
            <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              {primaryCause.description}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default ForecastAccuracyCards;
